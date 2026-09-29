"""Structuring with the LLM replaced at the `ChatClient` boundary."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from app.models import Sex
from app.services.extraction import ExtractedReport, PiiLeakError, extract_report
from app.services.structuring import (
    StructuredReport,
    StructuringError,
    normalize_test,
    structure_report,
)
from app.services.structuring.prompt import SYSTEM_PROMPT
from app.services.structuring.schemas import LLM_REPORT_SCHEMA, LlmRange, LlmReport, LlmTest
from app.services.structuring.service import (
    NAME_NOT_IN_SOURCE,
    NO_RANGE_CHOSEN,
    UNKNOWN_TEST,
    VALUE_NOT_IN_SOURCE,
)
from tests import synthetic_pdf as fake
from tests.structuring_data import SYNTHETIC_LLM_REPLY, FakeChatClient, seed_metric_index
from tests.synthetic_pdf import FIXTURE_PATH

REPORT = extract_report(FIXTURE_PATH.read_bytes())
INDEX = seed_metric_index()


def structure(
    reply: dict[str, Any] | str = SYNTHETIC_LLM_REPLY,
    *,
    sex: Sex = "female",
    report: ExtractedReport = REPORT,
) -> tuple[StructuredReport, FakeChatClient]:
    client = FakeChatClient(reply)
    result = structure_report(
        report, patient_sex=sex, metric_index=INDEX, client=client, model="test-model"
    )
    return result, client


def D(text: str) -> Decimal:  # noqa: N802 - reads like a literal
    return Decimal(text)


def _assert_strict(schema: dict[str, Any], model: type[BaseModel]) -> None:
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(model.model_fields)
    assert set(schema["required"]) == set(model.model_fields)


def test_llm_schema_is_strict_and_matches_the_models() -> None:
    tests = LLM_REPORT_SCHEMA["properties"]["tests"]["items"]
    ranges = tests["properties"]["reference_ranges"]["items"]

    _assert_strict(LLM_REPORT_SCHEMA, LlmReport)
    _assert_strict(tests, LlmTest)
    _assert_strict(ranges, LlmRange)
    LlmReport.model_validate(SYNTHETIC_LLM_REPLY)  # the recorded reply fits the models


def test_the_llm_receives_only_the_scrubbed_text() -> None:
    _, client = structure()

    (call,) = client.calls
    assert call == {
        "model": "test-model",
        "system": SYSTEM_PROMPT,
        "user": REPORT.llm_text(),
        "schema_name": "lab_report",
        "schema": LLM_REPORT_SCHEMA,
    }
    everything_sent = json.dumps(call).lower()
    for value in (fake.NAME, fake.REFERRED_BY, fake.URINE_BARCODE, fake.PHONE, fake.EMAIL):
        assert value.lower() not in everything_sent


def test_synthetic_report_becomes_reviewable_rows() -> None:
    result, _ = structure()

    rows = [
        (
            m.raw_name,
            m.canonical_name,
            m.value_numeric,
            m.value_canonical,
            m.unit_canonical,
            m.reference_label,
            m.reference_low,
            m.reference_high,
            m.flag,
        )
        for m in result.metrics
    ]
    assert rows == [
        ("CREATININE - URINE", "Urine Creatinine", D("84.20"), D("84.20"), "mg/dL",
         "Female", D("28"), D("217"), "normal"),
        ("URINARY MICROALBUMIN", "Urine Microalbumin", D("12.6"), D("12.6"), "mg/L",
         "Adults", None, D("30"), "normal"),
        ("URI. ALBUMIN/CREATININE RATIO (UA/C)", "Urine Albumin/Creatinine Ratio", D("15.0"),
         D("15.0"), "mg/g", "Adults", None, D("30"), "normal"),
        ("FERRITIN", "Ferritin", D("48.3"), D("48.3"), "ng/mL",
         "Women", D("4.63"), D("204.00"), "normal"),
    ]  # fmt: skip
    assert all(m.warnings == () for m in result.metrics)
    assert result.warnings == ()


def test_printed_details_are_kept_for_review() -> None:
    result, _ = structure()
    creatinine = result.metrics[0]

    assert creatinine.value_text == "84.20"
    assert creatinine.unit == "mg/dL"
    assert creatinine.reference_text == "Male: 39 - 259 mg/dl\nFemale: 28 - 217 mg/dl"
    assert creatinine.technology == "PHOTOMETRY"
    assert creatinine.method == "Creatinine Jaffe Method, Rate-Blanked and Compensated"
    assert creatinine.sample_type == "URINE"
    assert result.metrics[1].panel == "DIABETES SCREEN (URINE)"


def test_a_male_patient_gets_the_male_ranges() -> None:
    result, _ = structure(sex="male")

    creatinine, ferritin = result.metrics[0], result.metrics[3]
    assert (creatinine.reference_label, creatinine.reference_low) == ("Male", D("39"))
    assert (ferritin.reference_label, ferritin.reference_high) == ("Men", D("274.66"))


def test_a_value_the_llm_made_up_is_flagged_for_review() -> None:
    reply = json.loads(json.dumps(SYNTHETIC_LLM_REPLY))
    reply["tests"][0]["value"] = "48.20"  # not printed anywhere in the report

    result, _ = structure(reply)

    assert VALUE_NOT_IN_SOURCE in result.metrics[0].warnings


def test_decimals_serialize_exactly() -> None:
    result, _ = structure()

    stored = result.model_dump(mode="json")["metrics"][0]
    assert (stored["value_numeric"], stored["reference_high"]) == ("84.20", "217")


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("not json at all", id="not-json"),
        pytest.param({"results": []}, id="wrong-key"),
        pytest.param({"tests": [{"raw_name": "FERRITIN"}]}, id="missing-fields"),
    ],
)
def test_a_reply_with_the_wrong_shape_is_rejected(reply: dict[str, Any] | str) -> None:
    with pytest.raises(StructuringError, match="unexpected shape"):
        structure(reply)


def test_no_tests_found_is_a_warning() -> None:
    result, _ = structure({"tests": []})

    assert result.metrics == ()
    assert result.warnings == ("No test results were found in the report.",)


def test_identity_in_the_text_stops_before_any_llm_call() -> None:
    first = REPORT.pages[0]
    leaky_page = first.model_copy(update={"text": first.text + f"\n{fake.NAME}"})
    leaky = REPORT.model_copy(update={"pages": (leaky_page,)})
    client = FakeChatClient(SYNTHETIC_LLM_REPLY)

    with pytest.raises(PiiLeakError):
        structure_report(leaky, patient_sex="female", metric_index=INDEX, client=client, model="m")
    assert client.calls == []


def _test(**fields: Any) -> LlmTest:
    base: dict[str, Any] = {
        "raw_name": "VITAMIN K2",
        "panel": None,
        "technology": "CLIA",
        "value": "1.2",
        "unit": "ng/mL",
        "reference_ranges": [{"label": None, "text": "0.1 - 2.2"}],
        "method": None,
        "sample_type": "SERUM",
    }
    return LlmTest.model_validate(base | fields)


def test_unknown_tests_are_kept_but_unmapped() -> None:
    row = normalize_test(
        _test(), sex="female", metric_index=INDEX, source_text="VITAMIN K2 CLIA 1.2 ng/mL"
    )

    assert (row.canonical_metric_id, row.canonical_name, row.value_canonical) == (None, None, None)
    assert row.flag == "normal"  # still flagged against its printed range
    assert row.warnings == (UNKNOWN_TEST,)


def test_qualitative_results_are_kept_as_text() -> None:
    row = normalize_test(
        _test(raw_name="URINE GLUCOSE", value="Negative", unit=None,
              reference_ranges=[{"label": None, "text": "Negative"}]),
        sex="female",
        metric_index=INDEX,
        source_text="URINE GLUCOSE Negative Negative",
    )  # fmt: skip

    assert (row.value_text, row.value_numeric, row.flag) == ("Negative", None, "unknown")
    assert row.reference_text == "Negative"
    assert NO_RANGE_CHOSEN not in row.warnings


def test_an_analyte_specific_unit_is_not_converted() -> None:
    row = normalize_test(
        _test(raw_name="FASTING BLOOD SUGAR", value="5.2", unit="mmol/L",
              reference_ranges=[{"label": None, "text": "3.9 - 5.6"}]),
        sex="female",
        metric_index=INDEX,
        source_text="FASTING BLOOD SUGAR 5.2 mmol/L",
    )  # fmt: skip

    assert row.canonical_name == "Fasting Blood Glucose"
    assert (row.value_canonical, row.unit_canonical) == (None, None)
    assert row.warnings == ("Unit mmol/L was not converted to mg/dL",)
    assert row.flag == "normal"  # flagged in the printed unit against the printed range


def test_a_name_missing_from_the_text_is_flagged() -> None:
    row = normalize_test(_test(), sex="female", metric_index=INDEX, source_text="1.2 ng/mL")

    assert NAME_NOT_IN_SOURCE in row.warnings
