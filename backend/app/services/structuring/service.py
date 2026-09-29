"""Scrubbed report text → reviewable metric rows.

The LLM only segments the text and copies strings. Values, ranges, units, dictionary
matches and flags are all derived here, deterministically, and every copied value is checked
against the source text so a hallucinated number is caught in review, not saved.
"""

from pydantic import ValidationError

from app.models import Sex
from app.services.extraction import ExtractedReport, PiiLeakError
from app.services.extraction.pii import find_leaks
from app.services.llm import ChatClient
from app.services.normalization import (
    MetricIndex,
    RangeLine,
    compute_flag,
    convert,
    parse_number,
    select_range,
)
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

    value = parse_number(test.value)
    ranges = [RangeLine(label=r.label, text=r.text) for r in test.reference_ranges]
    chosen = select_range(ranges, sex)
    if ranges and chosen is None and value is not None:  # qualitative results need no bounds
        warnings.append(NO_RANGE_CHOSEN)

    entry = metric_index.match(raw_name, test.sample_type)
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
        value_text=test.value,
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


def structure_report(
    report: ExtractedReport,
    *,
    patient_sex: Sex,
    metric_index: MetricIndex,
    client: ChatClient,
    model: str,
) -> StructuredReport:
    """Only `report.llm_text()` (scrubbed results) is ever sent to the LLM."""
    text = report.llm_text()
    if leaks := find_leaks(text, report.identity):  # second check, right at the LLM boundary
        raise PiiLeakError(f"Identity data found in text meant for the AI ({', '.join(leaks)})")

    reply = client.complete_json(
        model=model,
        system=SYSTEM_PROMPT,
        user=text,
        schema_name="lab_report",
        schema=LLM_REPORT_SCHEMA,
    )
    try:
        parsed = LlmReport.model_validate_json(reply)
    except ValidationError as exc:
        raise StructuringError("The AI returned the results in an unexpected shape.") from exc

    metrics = tuple(
        normalize_test(test, sex=patient_sex, metric_index=metric_index, source_text=text)
        for test in parsed.tests
    )
    warnings = () if metrics else ("No test results were found in the report.",)
    return StructuredReport(model=model, metrics=metrics, warnings=warnings)
