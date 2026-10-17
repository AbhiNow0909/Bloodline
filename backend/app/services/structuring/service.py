"""Scrubbed report text → reviewable metric rows.

The LLM only segments the text and copies strings. Values, ranges, units, dictionary
matches and flags are all derived here, deterministically, and every copied value is checked
against the source text so a hallucinated number is caught in review, not saved.
"""

from dataclasses import dataclass
from functools import partial

from pydantic import ValidationError

from app.models import Sex
from app.services.extraction import ExtractedReport, PiiLeakError
from app.services.extraction.pii import find_leaks
from app.services.llm import ChatClient, Effort, LLMRefusalError, LLMTooLargeError
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

VALUE_NOT_IN_SOURCE = "The value was not found in the report text: check it against the PDF"
NAME_NOT_IN_SOURCE = "The test name was not found in the report text: check it against the PDF"
UNKNOWN_TEST = "Not in the metric dictionary yet: choose the matching test or keep it as is"
NO_RANGE_CHOSEN = "No printed range matched this patient: check the reference range"


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


# Groq's free tier allows 8,000 tokens a minute per model, counting the text sent (about 3.2
# characters a token, plus ~750 tokens of instructions and schema) and the reply (about as
# long as the text). A large health checkup does not fit in one request, so pages are sent in
# parts of at most this many characters: roughly 4,000-5,000 tokens a part with its reply.
# A page is never split, so a test's name, value, range and method stay together.
MAX_PART_CHARS = 6_000


@dataclass(frozen=True)
class ReportPart:
    page_numbers: tuple[int, ...]  # in the original PDF
    pages: tuple[str, ...]  # each page's scrubbed text, labelled with its sample type

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)

    def single_pages(self) -> list["ReportPart"]:
        return [ReportPart((n,), (p,)) for n, p in zip(self.page_numbers, self.pages, strict=True)]


def report_parts(report: ExtractedReport) -> list[ReportPart]:
    """The text to send, in parts of whole pages, in page order."""
    parts: list[ReportPart] = []
    size = 0
    for number, page in zip(
        (p.page_number for p in report.pages), report.page_llm_texts(), strict=True
    ):
        if parts and size + 2 + len(page) <= MAX_PART_CHARS:  # 2: the blank line between
            last = parts[-1]
            parts[-1] = ReportPart((*last.page_numbers, number), (*last.pages, page))
            size += 2 + len(page)
        else:
            parts.append(ReportPart((number,), (page,)))
            size = len(page)
    return parts


def possibly_missed_warning(page_number: int, names: list[str]) -> str:
    shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
    return (
        f"Page {page_number} may have results that were not read: {shown}. Check them against "
        'the PDF and add any that are missing with "Add a test that was missed".'
    )


def unread_page_warning(page_number: int) -> str:
    return (
        f"The AI could not read page {page_number} of the PDF, so its results are not listed "
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
    # Each value is checked against the part it came from.
    return [
        normalize_test(test, sex=patient_sex, metric_index=metric_index, source_text=text)
        for test in parsed.tests
    ]


# How each request is tried (see `structure_report`): a part of several pages once, cheaply,
# before it is split into pages; a single page cheaply, then with more reasoning, which reads
# pages that the cheap setting declines or breaks (at about three times the tokens).
PART_EFFORTS: tuple[Effort, ...] = ("low",)
PAGE_EFFORTS: tuple[Effort, ...] = ("low", "medium")


def structure_report(
    report: ExtractedReport,
    *,
    patient_sex: Sex,
    metric_index: MetricIndex,
    client: ChatClient,
    model: str,
) -> StructuredReport:
    """Only `report.llm_text()` (scrubbed results) is ever sent to the LLM, in parts of whole
    pages when it is large (`MAX_PART_CHARS`).

    gpt-oss now and then declines a request ("I'm sorry, but I can't help with that"), returns
    JSON in a broken shape, or Groq finds the request too large for the free tier's minute;
    not the same way twice. A part of several pages that fails is read one page at a time; a
    page is tried with low reasoning effort, then medium; a page that still fails is left out
    with a review warning, so the person adds those results from the PDF (the review shows it
    alongside). Any other error (service busy, request rejected) fails the whole report."""
    parts = report_parts(report)
    for part in parts:  # second check, right at the LLM boundary, before anything is sent
        if leaks := find_leaks(part.text, report.identity):
            raise PiiLeakError(f"Identity data found in text meant for the AI ({', '.join(leaks)})")
    structure = partial(
        _structure_part,
        patient_sex=patient_sex,
        metric_index=metric_index,
        client=client,
        model=model,
    )

    def attempt(part: ReportPart) -> list[StructuredMetric] | None:
        for effort in PAGE_EFFORTS if len(part.pages) == 1 else PART_EFFORTS:
            try:
                return structure(part.text, effort=effort)
            except (LLMRefusalError, LLMTooLargeError, StructuringError):
                continue
        return None

    metrics: list[StructuredMetric] = []
    warnings: list[str] = []
    read: list[ReportPart] = []
    pending = list(parts)
    while pending:
        part = pending.pop(0)
        rows = attempt(part)
        if rows is not None:
            metrics += rows
            read.append(part)
        elif len(part.pages) > 1:
            pending[:0] = part.single_pages()
        else:
            warnings.append(unread_page_warning(part.page_numbers[0]))
    if not metrics and warnings:  # no page could be read
        raise StructuringError("The AI could not read this report. Please try again later.")
    for part in read:
        for number, page in zip(part.page_numbers, part.pages, strict=True):
            if names := possibly_missed(page, metrics):
                warnings.append(possibly_missed_warning(number, names))
    if not metrics:
        warnings.append("No test results were found in the report.")
    return StructuredReport(model=model, metrics=tuple(metrics), warnings=tuple(warnings))
