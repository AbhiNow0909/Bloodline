"""The report ingestion pipeline (CLAUDE.md Section 4.1) and the confirm step.

`process_report` runs as a FastAPI background task after the upload response is sent. It
gets only the report id and opens its own session (request-scoped sessions are closed before
background tasks run). Every failure ends in status `failed` with a message that is safe to
show the user; nothing is left half-written.
"""

import logging
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import CanonicalMetric, Metric, Patient, Report, ReportFile, Sex
from app.schemas.report import ConfirmReport
from app.services.extraction import ExtractedReport, ExtractionError, extract_report
from app.services.llm import ChatClient, Effort, LLMError
from app.services.normalization import Bounds, compute_flag, convert, load_metric_index
from app.services.normalization.values import parse_number
from app.services.structuring import StructuredReport, StructuringError, structure_report

logger = logging.getLogger(__name__)

# A fresh `Session` in production (closed on exit); tests lend their own via nullcontext.
SessionFactory = Callable[[], AbstractContextManager[Session]]
ClientFactory = Callable[[], ChatClient]

UNEXPECTED_FAILURE = "Processing failed unexpectedly. Please try again."
INTERRUPTED = "Reading this report was interrupted (the server restarted). Please try again."

# One report is read at a time: reports that need the AI share its per-minute token limit,
# and two at once used to push each other's pages over it.
_ONE_AT_A_TIME = threading.Lock()


class StoredProcessing(BaseModel):
    """What `reports.raw_extraction` holds while a report awaits review. Only scrubbed text
    and derived data: the printed identity is excluded from `ExtractedReport` dumps."""

    version: Literal[1] = 1
    extraction: ExtractedReport
    structured: StructuredReport
    warnings: list[str]


# --- mismatch warnings ---------------------------------------------------------------------


def _age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def _name_words(name: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", name.casefold()) if len(word) >= 2}


def member_mismatch_warnings(extracted: ExtractedReport, patient: Patient) -> list[str]:
    """Hints that the report may belong to someone else. They never contain the printed name,
    which is not stored anywhere."""
    warnings = []
    if extracted.printed_sex is not None and extracted.printed_sex != patient.sex:
        warnings.append(
            f"The report is for a {extracted.printed_sex} patient, but this family member is "
            f"recorded as {patient.sex}. Check it was uploaded for the right person; reference "
            f"ranges were chosen for {patient.sex}."
        )
    printed_age, birth, collected = (
        extracted.printed_age_years,
        patient.date_of_birth,
        extracted.collected_at,
    )
    if (
        printed_age is not None
        and birth is not None
        and collected is not None
        and abs(_age_on(birth, collected.date()) - printed_age) > 1
    ):
        warnings.append(
            "The age printed on the report does not match this family member's date of birth."
        )
    display_words = _name_words(patient.display_name)
    if extracted.identity.names and not any(
        _name_words(name) & display_words for name in extracted.identity.names
    ):
        warnings.append(
            "The name printed on the report does not match this family member's name. "
            "Check it was uploaded for the right person."
        )
    return warnings


# --- background processing -----------------------------------------------------------------


class _ClientWhenNeeded:
    """The AI client, created only when a page needs the AI: most reports are read from their
    tables alone, so a missing GROQ_API_KEY only matters for the pages that do."""

    def __init__(self, factory: ClientFactory) -> None:
        self._factory = factory
        self._client: ChatClient | None = None

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        effort: Effort = "low",
    ) -> str:
        if self._client is None:
            self._client = self._factory()
        return self._client.complete_json(
            model=model,
            system=system,
            user=user,
            schema_name=schema_name,
            schema=schema,
            effort=effort,
        )


def _process(session: Session, report: Report, client_factory: ClientFactory, model: str) -> None:
    pdf = session.get_one(ReportFile, report.id).content
    patient = session.get_one(Patient, report.patient_id)

    extracted = extract_report(pdf)
    structured = structure_report(
        extracted,
        patient_sex=cast(Sex, patient.sex),  # guaranteed by ck_patients_sex_valid
        metric_index=load_metric_index(session),
        client=_ClientWhenNeeded(client_factory),
        model=model,
    )
    logger.info(
        "Report %s read: %d pages, %d rows, %d review warnings",
        report.id,
        len(extracted.pages),
        len(structured.metrics),
        len(structured.warnings),
    )
    warnings = [
        *extracted.warnings,
        *member_mismatch_warnings(extracted, patient),
        *structured.warnings,
    ]
    stored = StoredProcessing(extraction=extracted, structured=structured, warnings=warnings)

    report.lab_name = extracted.lab_name
    report.collected_at = extracted.collected_at
    report.raw_extraction = stored.model_dump(mode="json")
    report.status = "pending_review"
    report.failure_reason = None


def _mark_failed(session: Session, report_id: uuid.UUID, reason: str) -> None:
    session.rollback()
    report = session.get(Report, report_id)
    if report is not None:  # it may have been deleted while processing
        report.status = "failed"
        report.failure_reason = reason
        report.raw_extraction = None
        session.commit()


def process_report(
    report_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    client_factory: ClientFactory,
    model: str,
) -> None:
    with _ONE_AT_A_TIME, session_factory() as session:
        report = session.get(Report, report_id)
        if report is None or report.status != "processing":
            return
        try:
            _process(session, report, client_factory, model)
            session.commit()
        except (ExtractionError, LLMError, StructuringError) as exc:
            _mark_failed(session, report_id, str(exc))
        except Exception:
            logger.exception("Unexpected error while processing report %s", report_id)
            _mark_failed(session, report_id, UNEXPECTED_FAILURE)


def fail_interrupted_reports(session: Session) -> int:
    """Reports left "processing" when the server stopped (a restart, a deploy, or Render's
    free tier sleeping) are never finished: reading runs inside the server. Run when the
    server starts, before it takes requests, they are marked failed so they can be retried.
    Returns how many."""
    interrupted = session.scalars(
        update(Report)
        .where(Report.status == "processing")
        .values(status="failed", failure_reason=INTERRUPTED, raw_extraction=None)
        .returning(Report.id)
    ).all()
    session.commit()
    return len(interrupted)


# --- confirm -------------------------------------------------------------------------------


class ReportStateError(Exception):
    """The report is not in a state that allows this action (→ 409)."""


class ConfirmError(ValueError):
    """The reviewed data cannot be saved (→ 422). The message is safe to show."""


def confirm_report(
    session: Session, report: Report, body: ConfirmReport, *, now: datetime | None = None
) -> list[Metric]:
    """Write the reviewed rows as `metrics`. Every number is derived here from the reviewed
    text and bounds; nothing computed by the client or the LLM is trusted."""
    if report.status != "pending_review":
        raise ReportStateError(f"This report is not waiting for review (status: {report.status}).")
    collected_at = body.collected_at or report.collected_at
    if collected_at is None:
        raise ConfirmError("The collection date could not be read from the report; enter it.")
    if now is not None and collected_at > now:
        raise ConfirmError("The collection date is in the future.")

    wanted = {m.canonical_metric_id for m in body.metrics if m.canonical_metric_id is not None}
    definitions = {
        definition.id: definition
        for definition in session.scalars(
            select(CanonicalMetric).where(CanonicalMetric.id.in_(wanted))
        )
    }
    if wanted - definitions.keys():
        raise ConfirmError("A row refers to a test that is not in the metric dictionary.")

    metrics = []
    for row in body.metrics:
        value = parse_number(row.value_text)
        definition = (
            definitions[row.canonical_metric_id] if row.canonical_metric_id is not None else None
        )
        value_canonical = (
            convert(value, row.unit, definition.canonical_unit)
            if definition is not None and value is not None
            else None
        )
        metrics.append(
            Metric(
                patient_id=report.patient_id,
                report_id=report.id,
                canonical_metric_id=row.canonical_metric_id,
                raw_name=row.raw_name,
                value_numeric=value,
                value_text=row.value_text,
                unit=row.unit,
                value_canonical=value_canonical,
                unit_canonical=definition.canonical_unit
                if definition is not None and value_canonical is not None
                else None,
                reference_low=row.reference_low,
                reference_high=row.reference_high,
                reference_text=row.reference_text,
                flag=compute_flag(value, Bounds(row.reference_low, row.reference_high)),
                sample_type=row.sample_type,
                method=row.method,
                collected_at=collected_at,
            )
        )
    session.add_all(metrics)
    report.collected_at = collected_at
    report.status = "confirmed"
    # The scrubbed text in raw_extraction is indexed for search after commit
    # (app.services.embeddings.index_report_task).
    return metrics
