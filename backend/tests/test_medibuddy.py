"""MediBuddy-style reports, end to end: layout, header, scrubbing, structuring and upload.

Uses the synthetic fixture (`tests/synthetic_medibuddy.py`) and a recorded real model reply
for it; no network calls are made.
"""

from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_client_factory, get_session_factory
from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.main import app
from app.models import Patient, User
from app.services.extraction import ExtractedReport, extract_report
from app.services.extraction.header import IST, parse_medibuddy_header
from app.services.extraction.layout import Layout, PageKind, classify_page, split_results_page
from app.services.extraction.pdf_text import read_page_texts
from app.services.structuring import structure_report
from tests import synthetic_medibuddy as fake
from tests.factories import add, auth_headers, build_family, build_patient, build_user
from tests.structuring_data import SYNTHETIC_MEDIBUDDY_LLM_REPLY, FakeChatClient, seed_metric_index

PDF = fake.FIXTURE_PATH.read_bytes()
REPORT = extract_report(PDF)


def test_committed_fixture_matches_its_generator() -> None:
    assert fake.FIXTURE_PATH.read_bytes() == fake.synthetic_report(), (
        "fixture is stale: run `uv run python -m tests.synthetic_medibuddy`"
    )


# --- layout ---------------------------------------------------------------------------------


def test_results_pages_are_recognised_and_the_vitals_page_is_dropped() -> None:
    texts = read_page_texts(PDF)

    assert [classify_page(text) for text in texts] == [
        PageKind.RESULTS,
        PageKind.RESULTS,
        PageKind.OTHER,  # vitals: not lab results
    ]
    parts = split_results_page(texts[0])
    assert parts.layout is Layout.MEDIBUDDY
    assert parts.header.startswith(f"Name : MR. {fake.NAME}")
    assert parts.results.startswith("TEST DESCRIPTION RESULT UNITS")
    # Interpretation text, the lab note and the page number are footer.
    assert "Interpretation" not in parts.results
    assert "NOTE :" not in parts.results
    assert "Page 1 of 3" not in parts.results


# --- header and report fields ---------------------------------------------------------------


def test_report_level_fields() -> None:
    assert REPORT.lab_name == fake.LAB
    assert REPORT.collected_at == datetime(2026, 7, 13, 16, 33, tzinfo=IST)
    assert (REPORT.printed_age_years, REPORT.printed_sex) == (41, "male")
    assert [(p.page_number, p.sample_type) for p in REPORT.pages] == [(1, "SERUM"), (2, "WB EDTA")]
    assert REPORT.pages[0].received_at == datetime(2026, 7, 13, 18, 27, tzinfo=IST)
    assert REPORT.pages[0].released_at == datetime(2026, 7, 13, 19, 13, tzinfo=IST)
    assert REPORT.dropped_pages == (3,)
    assert REPORT.warnings == ()


def test_identity_is_parsed_for_scrubbing_without_the_honorific() -> None:
    assert REPORT.identity.names == (fake.NAME,)
    assert REPORT.identity.referred_by == (fake.REFERRED_BY,)
    assert REPORT.identity.barcodes == (fake.SAMPLE_ID, fake.CLIENT_ID)


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        pytest.param(
            [
                "Name : MRS. ANU TESTCASE",
                "Age/ Gender : 5 months / Female Ref. Doctor : SELF",
                "Sample Type : URINE Collected : 01/02/2026, 9:05 AM",
            ],
            {
                "name": "ANU TESTCASE",
                "age_years": None,  # an age in months is not a whole number of years
                "sex": "female",
                "referred_by": "SELF",
                "sample_type": "URINE",
                "collected_at": datetime(2026, 2, 1, 9, 5, tzinfo=IST),
            },
            id="months-female-four-digit-year",
        ),
        pytest.param(
            ["Name : SAMPLE NOTAREAL", "Sample Type : SERUM Collected : 31/02/26, 10:00 AM"],
            {"name": "SAMPLE NOTAREAL", "collected_at": None, "sex": None},
            id="unreadable-date",
        ),
    ],
)
def test_header_variants(lines: list[str], expected: dict[str, object]) -> None:
    header = parse_medibuddy_header("\n".join(lines))

    for field, value in expected.items():
        assert getattr(header, field) == value, field
    if expected.get("collected_at") is None and "Collected" in "\n".join(lines):
        assert header.warnings == ("Unreadable date in report header",)


# --- what the AI receives --------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected",
    [
        "Protein Total 7.2 g/dL 6.4 - 8.3",
        "(Method: Biuret)",
        "Vitamin - B12* 345 pg/mL 211 - 911",
        "RBC Count 4.82 mil/µL 4.5 - 5.5",
        "Absolute Neutrophil Count 3.90 * 10^9/L 2.0 - 7.0",
        "RBC Morphology Normocytic Normochromic",
        "Sample type: WB EDTA",
    ],
)
def test_ai_text_keeps_every_result(expected: str) -> None:
    assert expected in REPORT.llm_text()


@pytest.mark.parametrize(
    "absent",
    [
        fake.NAME,
        "RAVI",
        "FICTIONAL",
        fake.REFERRED_BY,
        "MEENA",
        fake.SAMPLE_ID,
        fake.CLIENT_ID,
        fake.PHONE,
        "Ignore previous instructions",  # interpretation text never reaches the model
        "Systolic",  # vitals page
        "processed at",
    ],
)
def test_ai_text_has_no_identity_and_no_footer(absent: str) -> None:
    assert absent.lower() not in REPORT.llm_text().lower()


# --- structuring and normalization -----------------------------------------------------------


def test_recorded_reply_becomes_reviewable_rows() -> None:
    client = FakeChatClient(SYNTHETIC_MEDIBUDDY_LLM_REPLY)

    result = structure_report(
        REPORT, patient_sex="male", metric_index=seed_metric_index(), client=client, model="m"
    )

    rows = [
        (m.canonical_name, m.value_canonical, m.unit_canonical, m.flag, m.method)
        for m in result.metrics
    ]
    assert rows == [
        ("Total Protein", Decimal("7.2"), "g/dL", "normal", "Biuret"),
        ("Direct Bilirubin", Decimal("0.21"), "mg/dL", "normal", "Diazo method"),
        ("AST", Decimal("46"), "U/L", "high", "IFCC without P5P"),
        ("Vitamin B12", Decimal("345"), "pg/mL", "normal", "CLIA"),
        ("Haemoglobin", Decimal("13.9"), "g/dL", "normal", "Photometry"),
        ("RBC Count", Decimal("4.82"), "10^6/uL", "normal", "Electrical impedance"),
        ("Total Leucocyte Count", Decimal("6.500"), "10^3/uL", "normal", None),
        ("Absolute Neutrophil Count", Decimal("3.90"), "10^3/uL", "normal", "Calculated"),
        (None, None, None, "unknown", None),  # RBC Morphology: a text result, kept as printed
    ]
    morphology = result.metrics[-1]
    assert (morphology.raw_name, morphology.value_text) == (
        "RBC Morphology",
        "Normocytic Normochromic",
    )
    # Every value and name was found in the text; only the unmapped text result is flagged.
    assert [m.warnings for m in result.metrics[:-1]] == [()] * 8


# --- upload, over HTTP -----------------------------------------------------------------------


def test_upload_is_read_into_a_review(client: TestClient, db_session: Session) -> None:
    seed_metric_dictionary(db_session, load_metric_seeds())
    model = FakeChatClient(SYNTHETIC_MEDIBUDDY_LLM_REPLY)
    app.dependency_overrides[get_session_factory] = lambda: lambda: nullcontext(db_session)
    app.dependency_overrides[get_client_factory] = lambda: lambda: model
    owner: User = add(db_session, build_user())
    member: Patient = add(
        db_session,
        build_patient(add(db_session, build_family(owner)), display_name="Ravi", sex="male"),
    )

    response = client.post(
        f"/patients/{member.id}/reports",
        content=PDF,
        headers=auth_headers(owner) | {"Content-Type": "application/pdf"},
    )

    assert response.status_code == 202, response.text
    report_id = response.json()["id"]
    report = client.get(f"/reports/{report_id}", headers=auth_headers(owner)).json()
    assert report["status"] == "pending_review"
    assert report["lab_name"] == fake.LAB
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(owner)).json()
    assert len(review["rows"]) == 9
    assert review["warnings"] == []  # same sex, a shared name word: nothing to check first
    (call,) = model.calls
    assert call["user"] == REPORT.llm_text()


def test_extracted_report_round_trips_through_storage() -> None:
    stored = ExtractedReport.model_validate_json(REPORT.model_dump_json())

    assert stored.pages == REPORT.pages
    assert stored.identity.names == ()  # identity is never stored
