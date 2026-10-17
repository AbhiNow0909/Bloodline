"""Structuring with the LLM replaced at the `ChatClient` boundary."""

import copy
import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from app.models import Sex
from app.services.extraction import ExtractedReport, PiiLeakError, extract_report
from app.services.llm import LLMRefusalError, LLMRequestError, LLMTooLargeError
from app.services.structuring import (
    StructuredReport,
    StructuringError,
    normalize_test,
    service,
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
        "effort": "low",
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
    with pytest.raises(StructuringError, match="could not read this report"):
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


def test_a_unit_copied_into_the_value_is_taken_off() -> None:
    # Thyrocare prints value and unit side by side; the model sometimes copies both as value.
    row = normalize_test(
        _test(raw_name="PLATELET COUNT", technology="HF & EI", value="241 X 10³ / µL",
              unit="X 10³ / µL", reference_ranges=[{"label": None, "text": "150-410"}]),
        sex="male",
        metric_index=INDEX,
        source_text="PLATELET COUNT HF & EI 241 X 10³ / µL 150-410",
    )  # fmt: skip

    assert (row.value_text, row.value_numeric) == ("241", D("241"))
    assert (row.canonical_name, row.value_canonical, row.unit_canonical) == (
        "Platelet Count",
        D("241"),
        "10^3/uL",
    )
    assert (row.flag, row.warnings) == ("normal", ())


@pytest.mark.parametrize(
    ("raw_name", "unit", "expected"),
    [
        ("Nucleated Red Blood Cells", "X 10³ / µL", None),  # Thyrocare's absolute count
        ("Nucleated Red Blood Cells %", "%", "Nucleated RBC"),
        ("Immature Granulocytes (IG)", "X 10³ / µL", None),
        ("Immature Granulocyte Percentage (IG%)", "%", "Immature Granulocytes"),
        ("Neutrophils - Absolute Count", "X 10³ / µL", "Absolute Neutrophil Count"),
    ],
)
def test_a_share_and_an_absolute_count_are_different_tests(
    raw_name: str, unit: str, expected: str | None
) -> None:
    row = normalize_test(
        _test(raw_name=raw_name, value="0.02", unit=unit, technology="Calculated"),
        sex="male",
        metric_index=INDEX,
        source_text=f"{raw_name} 0.02 {unit}",
    )

    assert row.canonical_name == expected


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


# --- large reports: sent in parts of whole pages ----------------------------------------------


class PartwiseClient:
    """Replies to each part with the synthetic tests whose values are printed in that part,
    as the model would. Calls numbered in `broken` (1-based) get a reply in a broken shape, and
    a request containing any of `refuse` is declined, as gpt-oss sometimes does."""

    def __init__(
        self,
        broken: tuple[int, ...] = (),
        refuse: tuple[str, ...] = (),
        refuse_at: tuple[str, ...] = ("low", "medium"),
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.broken = broken
        self.refuse = refuse
        self.refuse_at = refuse_at  # the efforts at which `refuse` applies

    def complete_json(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if len(self.calls) in self.broken:
            return json.dumps({"tests": [], "panel": "CBC", "value": "4.82"})  # seen from gpt-oss
        declined = any(text in kwargs["user"] for text in self.refuse)
        if declined and kwargs["effort"] in self.refuse_at:
            raise LLMRefusalError("The AI service returned something that is not JSON.")
        tests = [t for t in SYNTHETIC_LLM_REPLY["tests"] if t["value"] in kwargs["user"]]
        return json.dumps({"tests": tests})


PAGES = REPORT.page_llm_texts()  # creatinine; microalbumin + ratio; ferritin


def texts(parts: list[service.ReportPart]) -> list[str]:
    return [part.text for part in parts]


def test_a_small_report_is_one_part() -> None:
    (part,) = service.report_parts(REPORT)
    assert part.text == REPORT.llm_text()
    assert part.page_numbers == (3, 4, 5)


def test_parts_are_whole_pages_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_PART_CHARS", len(PAGES[0]) + 2 + len(PAGES[1]))
    parts = service.report_parts(REPORT)
    assert texts(parts) == [f"{PAGES[0]}\n\n{PAGES[1]}", PAGES[2]]
    assert [part.page_numbers for part in parts] == [(3, 4), (5,)]

    # A page longer than the limit is still sent whole, on its own.
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)
    assert texts(service.report_parts(REPORT)) == PAGES


def test_a_large_report_is_structured_part_by_part(monkeypatch: pytest.MonkeyPatch) -> None:
    whole, _ = structure()  # the same report in a single request
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)
    client = PartwiseClient()

    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="test-model"
    )

    # One request per part, each with only that part's text; the rows come back merged, in
    # page order, exactly as from a single request.
    assert [call["user"] for call in client.calls] == PAGES
    assert result == whole
    assert all(not metric.warnings for metric in result.metrics)


def test_each_value_is_checked_against_its_own_part(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)

    # A model answering every part with all four tests: rows not printed in that part are
    # flagged (1 + 2 + 1 printed of 4 + 4 + 4 returned).
    result, client = structure()

    assert len(client.calls) == 3
    flagged = [m for m in result.metrics if VALUE_NOT_IN_SOURCE in m.warnings]
    assert len(result.metrics) - len(flagged) == 4


def test_identity_in_any_part_stops_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)
    last = REPORT.pages[-1]
    leaky_page = last.model_copy(update={"text": last.text + f"\n{fake.NAME}"})
    leaky = REPORT.model_copy(update={"pages": (*REPORT.pages[:-1], leaky_page)})
    client = PartwiseClient()

    with pytest.raises(PiiLeakError):
        structure_report(leaky, patient_sex="female", metric_index=INDEX, client=client, model="m")
    assert client.calls == []  # not even the clean first parts


def test_a_broken_page_is_read_again_with_more_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    whole, _ = structure()
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)
    client = PartwiseClient(broken=(2,))

    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="test-model"
    )

    assert [(call["user"], call["effort"]) for call in client.calls] == [
        (PAGES[0], "low"),
        (PAGES[1], "low"),
        (PAGES[1], "medium"),
        (PAGES[2], "low"),
    ]
    assert result == whole


def test_other_errors_still_fail_the_whole_report() -> None:
    client = FakeChatClient(LLMRequestError("The AI service rejected the request (status 401)."))

    with pytest.raises(LLMRequestError):
        structure_report(REPORT, patient_sex="female", metric_index=INDEX, client=client, model="m")
    assert len(client.calls) == 1  # no retries or splitting for these


def test_a_field_left_out_by_the_model_counts_as_null() -> None:
    reply = copy.deepcopy(SYNTHETIC_LLM_REPLY)
    for test in reply["tests"]:
        del test["panel"]  # as gpt-oss-20b sometimes does on parts without headings

    result, _ = structure(reply)

    whole, _ = structure()
    assert [m.panel for m in result.metrics] == [None] * len(whole.metrics)
    assert [m.value_text for m in result.metrics] == [m.value_text for m in whole.metrics]


def test_a_required_field_left_out_is_still_rejected() -> None:
    reply = copy.deepcopy(SYNTHETIC_LLM_REPLY)
    del reply["tests"][0]["value"]

    with pytest.raises(StructuringError, match="could not read this report"):
        structure(reply)


# --- the model declining a request ------------------------------------------------------------


def test_a_declined_part_is_read_page_by_page() -> None:
    whole, _ = structure()
    client = PartwiseClient(refuse=(PAGES[0] + "\n\n" + PAGES[1],))  # only the whole part

    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="test-model"
    )

    # Asked once as a whole (cheaply), then page by page.
    assert [call["user"] for call in client.calls] == [REPORT.llm_text(), *PAGES]
    assert {call["effort"] for call in client.calls} == {"low"}
    assert result == whole  # same rows, same order, no warnings


def test_a_page_declined_with_little_reasoning_is_read_with_more() -> None:
    whole, _ = structure()
    client = PartwiseClient(refuse=("FERRITIN",), refuse_at=("low",))

    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="test-model"
    )

    ferritin = [call["effort"] for call in client.calls if "FERRITIN" in call["user"]]
    assert ferritin == ["low", "low", "medium"]  # the whole report, then its page twice
    assert result == whole


def test_a_page_still_declined_is_left_out_with_a_review_warning() -> None:
    client = PartwiseClient(refuse=(PAGES[0] + "\n\n" + PAGES[1], "FERRITIN"))

    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="m"
    )

    assert [m.canonical_name for m in result.metrics] == [
        "Urine Creatinine",
        "Urine Microalbumin",
        "Urine Albumin/Creatinine Ratio",
    ]
    assert result.warnings == (service.unread_page_warning(5),)
    assert "page 5" in result.warnings[0]
    assert "Add a test that was missed" in result.warnings[0]


def test_a_report_the_model_declines_entirely_fails() -> None:
    client = PartwiseClient(refuse=("Sample type",))

    with pytest.raises(StructuringError, match="could not read this report"):
        structure_report(REPORT, patient_sex="female", metric_index=INDEX, client=client, model="m")
    assert len(client.calls) == 7  # the whole report, then each of its three pages, twice each


def test_a_part_too_large_for_the_free_tier_is_read_page_by_page() -> None:
    whole, _ = structure()

    class TooLargeForWholeReport(PartwiseClient):
        def complete_json(self, **kwargs: Any) -> str:
            if kwargs["user"] == REPORT.llm_text():
                self.calls.append(kwargs)
                raise LLMTooLargeError("The text was too large for the AI service's free tier.")
            return super().complete_json(**kwargs)

    client = TooLargeForWholeReport()
    result = structure_report(
        REPORT, patient_sex="female", metric_index=INDEX, client=client, model="test-model"
    )

    assert [call["user"] for call in client.calls] == [REPORT.llm_text(), *PAGES]  # no 2nd try
    assert result == whole


def test_a_page_too_large_even_alone_is_treated_like_a_declined_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "MAX_PART_CHARS", 10)
    client = FakeChatClient(LLMTooLargeError("The text was too large for the AI service."))

    with pytest.raises(StructuringError, match="could not read this report"):
        structure_report(REPORT, patient_sex="female", metric_index=INDEX, client=client, model="m")
    assert [call["effort"] for call in client.calls] == ["low", "medium"] * 3
