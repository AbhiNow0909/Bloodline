"""End to end: synthetic Thyrocare-style PDF → scrubbed text + header fields."""

from datetime import datetime

import pytest

from app.services.extraction import (
    ExtractedReport,
    PiiLeakError,
    UnsupportedLayoutError,
    extract_report,
    pipeline,
)
from app.services.extraction.header import IST
from tests import synthetic_pdf as fake
from tests.synthetic_pdf import FIXTURE_PATH, build_pdf, lines


@pytest.fixture(scope="module")
def report() -> ExtractedReport:
    return extract_report(FIXTURE_PATH.read_bytes())


def test_keeps_results_pages_and_drops_the_rest(report: ExtractedReport) -> None:
    assert [(p.page_number, p.sample_type) for p in report.pages] == [
        (3, "URINE"),
        (4, "URINE"),
        (5, "SERUM"),
    ]
    assert report.dropped_pages == (1, 2, 6)


def test_report_level_fields(report: ExtractedReport) -> None:
    assert report.lab_name == "Thyrocare"
    assert report.collected_at == datetime(2025, 3, 3, 8, 15, tzinfo=IST)
    assert (report.printed_age_years, report.printed_sex) == (58, "female")
    assert report.warnings == ()


@pytest.mark.parametrize(
    "expected",
    [
        "Sample type: URINE\nTEST NAME TECHNOLOGY VALUE UNITS",
        "CREATININE - URINE PHOTOMETRY 84.20 mg/dL",
        "Male: 39 - 259 mg/dl\nFemale: 28 - 217 mg/dl",
        "DIABETES SCREEN (URINE)",
        "URINARY MICROALBUMIN PHOTOMETRY 12.6 µg/mL",
        "Adults: Less than 30 µg/ml",
        "Adults : Less than 30 µg/mg of Creatinine",
        "Sample type: SERUM",
        "Women: 4.63 - 204.00 ng/ml",
    ],
)
def test_llm_text_keeps_results_ranges_and_units(report: ExtractedReport, expected: str) -> None:
    assert expected in report.llm_text()


IDENTITY_VALUES = [
    fake.NAME,
    *fake.NAME.split(),
    fake.AGE_SEX,
    fake.REFERRED_BY,
    "SUNIL",
    "NOTREAL",
    fake.URINE_BARCODE,
    fake.SERUM_BARCODE,
    fake.PHONE,
    fake.EMAIL,
    "Imaginary Lane",
    "Fakenagar",
    "Testpur",
    "FAKESTATE",
    "400000",
    *fake.SIGNING_DOCTORS,
    "SYN Tower",
    "03 Mar 2025",
    "Patient Name",
    "Referred By",
    "Address",
]


@pytest.mark.parametrize("value", IDENTITY_VALUES)
def test_llm_text_contains_no_identity(report: ExtractedReport, value: str) -> None:
    assert value.lower() not in report.llm_text().lower()


def test_identity_stays_on_the_backend_and_is_never_serialized(report: ExtractedReport) -> None:
    assert report.identity.names == (fake.NAME,)
    assert report.identity.barcodes == (fake.URINE_BARCODE, fake.SERUM_BARCODE)

    stored = report.model_dump_json()
    for value in (fake.NAME, fake.REFERRED_BY, fake.URINE_BARCODE):
        assert value not in stored
        assert value not in repr(report)


def test_pages_for_different_patients_raise_a_warning() -> None:
    other = lines(
        *fake.results_header("SERUM", "ZZ000001", name="RAVI OTHERPERSON"),
        "FERRITIN C.M.I.A 48.3 ng/mL",
    )
    pdf = build_pdf([fake.creatinine_page(), other])

    report = extract_report(pdf)

    assert "Results pages show different patient names" in report.warnings
    assert report.identity.names == (fake.NAME, "RAVI OTHERPERSON")


def test_a_pdf_without_results_pages_is_unsupported() -> None:
    pdf = build_pdf([fake.cover_page(), fake.conditions_page()])

    with pytest.raises(UnsupportedLayoutError, match="No results pages found"):
        extract_report(pdf)


def test_fails_closed_if_scrubbing_misses_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "scrub_text", lambda text, identity: text)  # a broken scrubber

    with pytest.raises(PiiLeakError) as excinfo:
        extract_report(FIXTURE_PATH.read_bytes())

    message = str(excinfo.value)
    assert "name" in message
    assert fake.NAME.split()[0] not in message  # the error itself never carries identity
