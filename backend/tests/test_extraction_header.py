from datetime import UTC, datetime, timedelta

import pytest

from app.models import Sex
from app.services.extraction.header import IST, ParsedHeader, parse_header
from app.services.extraction.layout import split_results_page
from app.services.extraction.pdf_text import read_page_texts
from tests.synthetic_pdf import FIXTURE_PATH


def test_parses_the_two_column_results_header() -> None:
    page = read_page_texts(FIXTURE_PATH.read_bytes())[2]

    header = parse_header(split_results_page(page).header)

    assert header == ParsedHeader(
        name="ASHA FICTIONAL",
        age_years=58,
        sex="female",
        referred_by="DR SUNIL NOTREAL",
        sample_type="URINE",
        barcode="ZZ123456",
        collected_at=datetime(2025, 3, 3, 8, 15, tzinfo=IST),
        received_at=datetime(2025, 3, 3, 13, 40, tzinfo=IST),
        released_at=datetime(2025, 3, 4, 10, 5, tzinfo=IST),
    )


@pytest.mark.parametrize(
    ("line", "name", "age", "sex"),
    [
        pytest.param(
            "Patient Name : ASHA FICTIONAL(58Y/F) Sample Collected on (SCT): 03 Mar 2025 08:15",
            "ASHA FICTIONAL",
            58,
            "female",
            id="merged-with-right-column",
        ),
        pytest.param("Patient Name : RAVI TEST ( 7 Y / M )", "RAVI TEST", 7, "male", id="spaced"),
        pytest.param(
            "Patient Name : NO AGE PRINTED Sample Collected on (SCT): 03 Mar 2025 08:15",
            "NO AGE PRINTED",
            None,
            None,
            id="no-age-sex",
        ),
    ],
)
def test_patient_line_variants(line: str, name: str, age: int | None, sex: Sex | None) -> None:
    header = parse_header(line)

    assert (header.name, header.age_years, header.sex) == (name, age, sex)


def test_missing_fields_are_none_not_errors() -> None:
    header = parse_header("Referred By : SELF Sample Received on (SRT) : 03 Mar 2025 13:40")

    assert header.referred_by == "SELF"
    assert header.received_at == datetime(2025, 3, 3, 13, 40, tzinfo=IST)
    assert header.name is None
    assert header.sample_type is None
    assert header.collected_at is None


def test_times_are_indian_local_time() -> None:
    header = parse_header("Sample Collected on (SCT): 03 Mar 2025 08:15")

    assert header.collected_at is not None
    assert header.collected_at.utcoffset() == timedelta(hours=5, minutes=30)
    assert header.collected_at == datetime(2025, 3, 3, 2, 45, tzinfo=UTC)


def test_an_impossible_date_is_a_warning_not_a_crash() -> None:
    header = parse_header("Sample Collected on (SCT): 31 Feb 2025 08:15")

    assert header.collected_at is None
    assert header.warnings == ("Unreadable date in report header",)


@pytest.mark.parametrize("surname", ["TEST", "TESTS", "SAMPLE", "REPORT"])
def test_surnames_that_look_like_labels_are_kept_whole(surname: str) -> None:
    header = parse_header(
        f"Patient Name : RAVI {surname} Sample Collected on (SCT): 03 Mar 2025 08:15\n"
        f"Referred By : DR ASHOK {surname} Sample Received on (SRT) : 03 Mar 2025 13:40"
    )

    assert header.name == f"RAVI {surname}"
    assert header.referred_by == f"DR ASHOK {surname}"
