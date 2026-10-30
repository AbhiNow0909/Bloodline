"""The background pipeline and the mismatch warnings, called directly."""

import hashlib
import threading
import time
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.cli import startup
from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.models import Patient, Report, ReportFile
from app.services import ingestion
from app.services.extraction import extract_report
from app.services.ingestion import (
    INTERRUPTED,
    UNEXPECTED_FAILURE,
    StoredProcessing,
    fail_interrupted_reports,
    member_mismatch_warnings,
    process_report,
)
from app.services.llm import ChatClient, LLMNotConfiguredError, LLMUnavailableError
from tests import synthetic_pdf as fake
from tests.factories import add, add_family, build_patient
from tests.structuring_data import FakeChatClient
from tests.synthetic_pdf import FIXTURE_PATH, build_pdf

PDF = FIXTURE_PATH.read_bytes()
EXTRACTED = extract_report(PDF)
# The same report printed without column gaps: only the AI can read its pages.
AI_ONLY_PDF = fake.synthetic_report(columns=False)


def _pending(session: Session, pdf: bytes = PDF, *, sex: str = "female") -> Report:
    """A committed report in `processing`, as the upload endpoint leaves it."""
    patient = add(session, build_patient(add_family(session), display_name="Asha", sex=sex))
    report = add(
        session,
        Report(patient_id=patient.id, file_sha256=hashlib.sha256(pdf).hexdigest()),
    )
    add(session, ReportFile(report_id=report.id, content=pdf))
    seed_metric_dictionary(session, load_metric_seeds())
    session.commit()
    return report


def _process(session: Session, report: Report, client: ChatClient | Exception) -> Report:
    def client_factory() -> ChatClient:
        if isinstance(client, Exception):
            raise client
        return client

    report_id = report.id
    process_report(
        report_id,
        session_factory=lambda: nullcontext(session),
        client_factory=client_factory,
        model="m",
    )
    return session.get_one(Report, report_id)


def test_success_stores_scrubbed_extraction_and_rows(db_session: Session) -> None:
    report = _process(db_session, _pending(db_session), FakeChatClient())

    assert (report.status, report.failure_reason) == ("pending_review", None)
    stored = StoredProcessing.model_validate(report.raw_extraction)
    assert len(stored.structured.metrics) == 4
    assert stored.extraction.identity.names == ()  # never stored
    assert [p.page_number for p in stored.extraction.pages] == [3, 4, 5]
    assert all(page.table == () for page in stored.extraction.pages)  # not stored either


def test_a_report_read_from_its_tables_needs_no_ai_key(db_session: Session) -> None:
    no_key = LLMNotConfiguredError("GROQ_API_KEY is not set, so reports cannot be structured.")

    report = _process(db_session, _pending(db_session), no_key)

    assert (report.status, report.failure_reason) == ("pending_review", None)
    stored = StoredProcessing.model_validate(report.raw_extraction)
    assert len(stored.structured.metrics) == 4


def test_pages_only_the_ai_can_read_are_read_by_it(db_session: Session) -> None:
    client = FakeChatClient()

    report = _process(db_session, _pending(db_session, AI_ONLY_PDF), client)

    assert report.status == "pending_review"
    assert len(client.calls) == 3  # one per page


@pytest.mark.parametrize(
    ("pdf", "client", "reason"),
    [
        pytest.param(
            build_pdf([fake.cover_page(), fake.conditions_page()]),
            FakeChatClient(),
            "No results pages found",
            id="unsupported-layout",
        ),
        pytest.param(
            build_pdf([fake.cover_page(), []]),
            FakeChatClient(),
            "scanned/image PDF not supported yet",
            id="scanned-page",
        ),
        pytest.param(
            AI_ONLY_PDF,
            LLMNotConfiguredError("GROQ_API_KEY is not set, so reports cannot be structured."),
            "GROQ_API_KEY is not set",
            id="llm-not-configured",
        ),
        pytest.param(
            AI_ONLY_PDF,
            FakeChatClient(LLMUnavailableError("The AI service is busy. Please try again.")),
            "busy",
            id="llm-busy",
        ),
        pytest.param(
            AI_ONLY_PDF, FakeChatClient("{}"), "could not read this report", id="bad-llm-reply"
        ),
        pytest.param(
            AI_ONLY_PDF, FakeChatClient(RuntimeError("boom")), UNEXPECTED_FAILURE, id="bug"
        ),
    ],
)
def test_failures_end_in_failed_with_a_safe_message(
    db_session: Session, pdf: bytes, client: ChatClient | Exception, reason: str
) -> None:
    report = _process(db_session, _pending(db_session, pdf), client)

    assert report.status == "failed"
    assert report.failure_reason is not None
    assert reason in report.failure_reason
    assert report.raw_extraction is None
    assert "boom" not in report.failure_reason  # internal details stay in the logs


def test_a_report_deleted_before_processing_is_ignored(db_session: Session) -> None:
    report = _pending(db_session)
    report_id = report.id
    db_session.delete(report)
    db_session.commit()

    process_report(
        report_id,
        session_factory=lambda: nullcontext(db_session),
        client_factory=FakeChatClient,
        model="m",
    )

    assert db_session.get(Report, report_id) is None


def test_reports_are_read_one_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two uploads at once used to share the AI's per-minute token limit and push each other's
    # pages over it.
    running: list[int] = []
    overlaps: list[int] = []

    def slow_process(*args: Any) -> None:
        running.append(1)
        overlaps.append(len(running))
        time.sleep(0.05)
        running.pop()

    monkeypatch.setattr(ingestion, "_process", slow_process)
    session = SimpleNamespace(
        get=lambda *a: SimpleNamespace(status="processing"), commit=lambda: None
    )

    def read() -> None:
        process_report(
            object(),  # type: ignore[arg-type]
            session_factory=lambda: nullcontext(session),  # type: ignore[arg-type]
            client_factory=FakeChatClient,
            model="m",
        )

    threads = [threading.Thread(target=read) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlaps == [1, 1, 1]


def test_reports_left_processing_by_a_stopped_server_are_marked_failed(
    db_session: Session,
) -> None:
    interrupted = _pending(db_session)
    waiting = _process(db_session, _pending(db_session), FakeChatClient())

    assert fail_interrupted_reports(db_session) == 1

    db_session.refresh(interrupted)
    assert (interrupted.status, interrupted.failure_reason) == ("failed", INTERRUPTED)
    assert waiting.status == "pending_review"  # reports in other states are left alone
    # "Try reading it again" puts it back in processing, and it is read as usual.
    interrupted.status = "processing"
    db_session.commit()
    assert _process(db_session, interrupted, FakeChatClient()).status == "pending_review"


def test_the_startup_command_marks_interrupted_reports(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pending(db_session)
    monkeypatch.setattr(startup, "get_engine", lambda: None)
    monkeypatch.setattr(startup, "Session", lambda engine: nullcontext(db_session))

    assert startup.main() == 0
    assert "1 interrupted report(s) marked as failed" in capsys.readouterr().out


def test_the_startup_command_never_stops_the_server_from_starting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreachable() -> None:
        raise OperationalError("connect", {}, Exception("database is not reachable"))

    monkeypatch.setattr(startup, "get_engine", unreachable)

    assert startup.main() == 0
    assert "interrupted reports not checked (OperationalError)" in capsys.readouterr().err


def test_reports_not_in_processing_are_left_alone(db_session: Session) -> None:
    report = _pending(db_session)
    report.status = "confirmed"
    db_session.commit()
    client = FakeChatClient()

    assert _process(db_session, report, client).status == "confirmed"
    assert client.calls == []


def _member(**fields: object) -> Patient:
    return Patient(**({"display_name": "Asha", "sex": "female"} | fields))


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        pytest.param(_member(), [], id="matches"),
        pytest.param(_member(display_name="asha verma"), [], id="shares-a-name"),
        pytest.param(_member(date_of_birth=date(1966, 6, 1)), [], id="age-matches"),
        pytest.param(_member(sex="male"), ["recorded as male"], id="sex-differs"),
        pytest.param(_member(display_name="Mum"), ["name printed"], id="nickname"),
        pytest.param(_member(date_of_birth=date(1990, 1, 1)), ["age printed"], id="age-differs"),
    ],
)
def test_mismatch_warnings(member: Patient, expected: list[str]) -> None:
    warnings = member_mismatch_warnings(EXTRACTED, member)

    assert len(warnings) == len(expected)
    for fragment, warning in zip(expected, warnings, strict=True):
        assert fragment in warning
        assert fake.NAME.split()[1].lower() not in warning.lower()  # printed name never shown
