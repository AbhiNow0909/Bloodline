"""Scrubbed report text → reviewable metric rows.

The LLM only segments the text and copies strings. Values, ranges, units, dictionary
matches and flags are all derived here, deterministically, and every copied value is checked
against the source text so a hallucinated number is caught in review, not saved.
"""

import logging
from collections.abc import Callable
from functools import partial

from pydantic import ValidationError

from app.models import Sex
from app.services.extraction import ExtractedReport, PiiLeakError
from app.services.extraction.pii import find_leaks
from app.services.llm import ChatClient, Effort, LLMError, LLMRefusalError, LLMTooLargeError
from app.services.normalization import (
    MetricIndex,
    RangeLine,
    compute_flag,
    convert,
    parse_number,
    select_range,
)
from app.services.structuring.completeness import possibly_missed
from app.services.structuring.prompt import SYSTEM_PROMPT
from app.services.structuring.schemas import (
    LLM_REPORT_SCHEMA,
    LlmReport,
    LlmTest,
    StructuredMetric,
    StructuredReport,
    StructuringError,
)
from app.services.structuring.table_reader import read_table

VALUE_NOT_IN_SOURCE = "The value was not found in the report text: check it against the PDF"
NAME_NOT_IN_SOURCE = "The test name was not found in the report text: check it against the PDF"
UNKNOWN_TEST = "Not in the metric dictionary yet: choose the matching test or keep it as is"
NO_RANGE_CHOSEN = "No printed range matched this patient: check the reference range"

logger = logging.getLogger(__name__)


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clean_name(raw_name: str, technology: str | None) -> str:
    """Models sometimes append the TECHNOLOGY column to the name ("… (UA/C) CALCULATED")."""
    name = " ".join(raw_name.split())
    if technology and _squash(name).endswith(" " + _squash(technology)):
        name = name[: -len(" ".join(technology.split()))].rstrip()
    return name


def _without_unit(value: str, unit: str | None) -> str:
    """The model sometimes copies the unit into the value too ("2.65 X 10³ / µL")."""
    value = " ".join(value.split())
    if unit and unit.strip():
        unit = " ".join(unit.split())
        if value.casefold().endswith(" " + unit.casefold()):
            return value[: -len(unit)].rstrip()
    return value


def normalize_test(
    test: LlmTest, *, sex: Sex, metric_index: MetricIndex, source_text: str
) -> StructuredMetric:
    warnings: list[str] = []
    raw_name = _clean_name(test.raw_name, test.technology)
    source = _squash(source_text)
    if _squash(test.value) not in source:
        warnings.append(VALUE_NOT_IN_SOURCE)
    if _squash(raw_name) not in source:
        warnings.append(NAME_NOT_IN_SOURCE)

    printed_value = _without_unit(test.value, test.unit)
    value = parse_number(printed_value)
    ranges = [RangeLine(label=r.label, text=r.text) for r in test.reference_ranges]
    chosen = select_range(ranges, sex)
    if ranges and chosen is None and value is not None:  # qualitative results need no bounds
        warnings.append(NO_RANGE_CHOSEN)

    entry = metric_index.match(raw_name, test.sample_type, test.unit)
    value_canonical = unit_canonical = None
    if entry is None:
        warnings.append(UNKNOWN_TEST)
    elif value is not None:
        value_canonical = convert(value, test.unit, entry.canonical_unit)
        if value_canonical is None:
            warnings.append(
                f"Unit {test.unit or '(none)'} was not converted to {entry.canonical_unit}"
            )
        else:
            unit_canonical = entry.canonical_unit

    return StructuredMetric(
        raw_name=raw_name,
        panel=test.panel,
        technology=test.technology,
        method=test.method,
        sample_type=test.sample_type,
        value_text=printed_value,
        value_numeric=value,
        unit=test.unit,
        canonical_metric_id=entry.id if entry else None,
        canonical_name=entry.canonical_name if entry else None,
        value_canonical=value_canonical,
        unit_canonical=unit_canonical,
        reference_text="\n".join(f"{r.label}: {r.text}" if r.label else r.text for r in ranges)
        or None,
        reference_low=chosen.bounds.low if chosen else None,
        reference_high=chosen.bounds.high if chosen else None,
        reference_label=chosen.label if chosen else None,
        flag=compute_flag(value, chosen.bounds if chosen else None),
        warnings=tuple(warnings),
    )


def possibly_missed_warning(page_number: int, names: list[str]) -> str:
    shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
    return (
        f"Page {page_number} may have results that were not read: {shown}. Check them against "
        'the PDF and add any that are missing with "Add a test that was missed".'
    )


def unread_page_warning(page_number: int) -> str:
    return (
        f"Page {page_number} of the PDF could not be read, so its results are not listed "
        'here. Add them from the PDF with "Add a test that was missed".'
    )


def _structure_part(
    text: str,
    *,
    patient_sex: Sex,
    metric_index: MetricIndex,
    client: ChatClient,
    model: str,
    effort: Effort,
) -> list[StructuredMetric]:
    reply = client.complete_json(
        model=model,
        system=SYSTEM_PROMPT,
        user=text,
        schema_name="lab_report",
        schema=LLM_REPORT_SCHEMA,
        effort=effort,
    )
    try:
        parsed = LlmReport.model_validate_json(reply)
    except ValidationError as exc:
        raise StructuringError("The AI returned the results in an unexpected shape.") from exc
    # Each value is checked against the page it came from.
    return [
        normalize_test(test, sex=patient_sex, metric_index=metric_index, source_text=text)
        for test in parsed.tests
    ]


# How the AI reads a page: with low reasoning effort, then more, which reads pages that low
# effort declines or breaks (at about three times the tokens).
PAGE_EFFORTS: tuple[Effort, ...] = ("low", "medium")
# These mean the AI cannot read this page. Any other error (busy, daily limit used up, request
# rejected, no key) means it cannot read any page now.
_PAGE_FAILURES = (LLMRefusalError, LLMTooLargeError, StructuringError)


def _read_with_ai(
    text: str, page_number: int, structure: Callable[..., list[StructuredMetric]]
) -> list[StructuredMetric] | None:
    for effort in PAGE_EFFORTS:
        try:
            return structure(text, effort=effort)
        except _PAGE_FAILURES as exc:
            logger.warning(
                "The AI could not read page %d (%s, %s effort)",
                page_number,
                type(exc).__name__,
                effort,
            )
    return None


def structure_report(
    report: ExtractedReport,
    *,
    patient_sex: Sex,
    metric_index: MetricIndex,
    client: ChatClient,
    model: str,
) -> StructuredReport:
    """Reviewable rows for the report's results.

    Each page's results table is read from the positions of its words (`read_table`), with no
    AI. Only a page whose table could not be read completely (no rows, or a line that looks
    like a result left over) is given to the AI: one page at a time, only its scrubbed text
    (`page_llm_texts`). gpt-oss now and then declines a page or breaks the JSON, so a page is
    tried with low reasoning effort, then medium. A page the AI cannot read keeps the rows read
    from its table, with a review warning naming what may be missing; the person adds it from
    the PDF, which the review shows alongside. The report fails only if nothing could be read.
    """
    readings = [read_table(page) for page in report.pages]
    texts = report.page_llm_texts()
    for_ai = {i for i, reading in enumerate(readings) if not reading.tests or reading.unread}
    for i in sorted(for_ai):  # a second check, right at the LLM boundary, before any request
        if leaks := find_leaks(texts[i], report.identity):
            raise PiiLeakError(f"Identity data found in text meant for the AI ({', '.join(leaks)})")
    structure = partial(
        _structure_part,
        patient_sex=patient_sex,
        metric_index=metric_index,
        client=client,
        model=model,
    )

    metrics: list[StructuredMetric] = []
    warnings: list[str] = []
    warned: set[int] = set()
    unavailable: LLMError | None = None  # the AI service cannot be used now: stop asking it
    for i, (page, reading) in enumerate(zip(report.pages, readings, strict=True)):
        number = page.page_number
        if i in for_ai and unavailable is None:
            try:
                rows = _read_with_ai(texts[i], number, structure)
            except LLMError as exc:
                logger.warning(
                    "The AI could not be used for page %d (%s)", number, type(exc).__name__
                )
                unavailable, rows = exc, None
            if rows is not None:
                metrics += rows
                continue
        metrics += [
            normalize_test(test, sex=patient_sex, metric_index=metric_index, source_text=texts[i])
            for test in reading.tests
        ]
        if i in for_ai:
            warned.add(number)
            if reading.tests:
                warnings.append(possibly_missed_warning(number, list(reading.unread)))
            else:
                warnings.append(unread_page_warning(number))
    if not metrics:
        if unavailable is not None:
            raise unavailable
        if warnings:  # no page could be read
            raise StructuringError("The AI could not read this report. Please try again later.")
        return StructuredReport(
            model=model, metrics=(), warnings=("No test results were found in the report.",)
        )
    for page, text in zip(report.pages, texts, strict=True):
        if page.page_number not in warned and (names := possibly_missed(text, metrics)):
            warnings.append(possibly_missed_warning(page.page_number, names))
    return StructuredReport(model=model, metrics=tuple(metrics), warnings=tuple(warnings))
