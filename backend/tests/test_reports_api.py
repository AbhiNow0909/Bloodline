"""Upload → background processing → review → confirm, over HTTP.

Background processing runs on the test's own session (rolled back afterwards) and with the
LLM faked at the `ChatClient` boundary, so no network calls are made.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_client_factory, get_embedder_factory, get_session_factory
from app.api.reports import get_max_upload_bytes
from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.main import app
from app.models import Family, Metric, Patient, Report, ReportChunk, User
from app.services.embeddings import search_report_text
from app.services.extraction.header import IST
from tests import synthetic_pdf as fake
from tests.embedding_helpers import BrokenEmbedder, FakeEmbedder
from tests.factories import add, add_family, auth_headers, build_family, build_patient, build_user
from tests.structuring_data import FakeChatClient
from tests.synthetic_pdf import FIXTURE_PATH

PDF = FIXTURE_PATH.read_bytes()


@pytest.fixture
def alice(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def bob(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def member(db_session: Session, alice: User) -> Patient:
    family = add(db_session, build_family(alice))
    return add(db_session, build_patient(family, display_name="Asha", sex="female"))


@pytest.fixture
def llm(client: TestClient, db_session: Session) -> FakeChatClient:
    """Seeded metric dictionary, background tasks on the test session, and a fake LLM."""
    seed_metric_dictionary(db_session, load_metric_seeds())
    fake_llm = FakeChatClient()
    app.dependency_overrides[get_session_factory] = lambda: lambda: nullcontext(db_session)
    app.dependency_overrides[get_client_factory] = lambda: lambda: fake_llm
    return fake_llm


def upload(
    client: TestClient,
    user: User,
    patient_id: uuid.UUID,
    body: bytes | Iterator[bytes] = PDF,
    content_type: str = "application/pdf",
) -> httpx2.Response:
    headers = auth_headers(user) | {"Content-Type": content_type}
    return client.post(f"/patients/{patient_id}/reports", content=body, headers=headers)


def processed(client: TestClient, user: User, member: Patient) -> dict[str, Any]:
    """Upload the synthetic report; the background task has run when the call returns."""
    response = upload(client, user, member.id)
    assert response.status_code == 202, response.text
    report: dict[str, Any] = client.get(
        f"/reports/{response.json()['id']}", headers=auth_headers(user)
    ).json()
    return report


def confirm_body(review: dict[str, Any]) -> dict[str, Any]:
    """Confirm every extracted row as the review screen would submit it, unchanged."""
    keys = ("raw_name", "canonical_metric_id", "value_text", "unit", "reference_low",
            "reference_high", "reference_text", "sample_type", "method")  # fmt: skip
    return {"metrics": [{key: row[key] for key in keys} for row in review["rows"]]}


# --- upload and processing -----------------------------------------------------------------


def test_upload_is_processed_into_a_review(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient
) -> None:
    response = upload(client, alice, member.id)

    assert response.status_code == 202
    assert response.json()["status"] == "processing"  # the response is sent before processing
    report_id = response.json()["id"]

    report = client.get(f"/reports/{report_id}", headers=auth_headers(alice)).json()
    assert report["status"] == "pending_review"
    assert report["lab_name"] == "Thyrocare"
    assert datetime.fromisoformat(report["collected_at"]) == datetime(2025, 3, 3, 8, 15, tzinfo=IST)

    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    assert [row["canonical_name"] for row in review["rows"]] == [
        "Urine Creatinine",
        "Urine Microalbumin",
        "Urine Albumin/Creatinine Ratio",
        "Ferritin",
    ]
    assert review["rows"][0]["value_numeric"] == "84.20"  # exact decimal, as a string
    assert review["rows"][0]["reference_label"] == "Female"
    assert (review["printed_age_years"], review["printed_sex"]) == (58, "female")
    assert review["sample_types"] == ["SERUM", "URINE"]
    assert review["warnings"] == []  # "Asha" matches the printed name; sexes match


def test_only_scrubbed_text_reaches_the_llm_or_the_database(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]

    (call,) = llm.calls
    stored = json.dumps(db_session.get_one(Report, uuid.UUID(report_id)).raw_extraction)
    for value in (fake.NAME, *fake.NAME.split(), fake.URINE_BARCODE, fake.REFERRED_BY, fake.PHONE):
        assert value.lower() not in call["user"].lower()
        assert value.lower() not in stored.lower()
    assert "CREATININE - URINE PHOTOMETRY 84.20 mg/dL" in stored  # scrubbed text kept for RAG


@pytest.mark.parametrize(
    ("content_type", "body", "expected_status"),
    [
        pytest.param("text/plain", PDF, 415, id="wrong-content-type"),
        pytest.param("multipart/form-data; boundary=x", PDF, 415, id="multipart"),
        pytest.param("application/pdf", b"", 422, id="empty"),
        pytest.param("application/pdf", b"GIF89a not a pdf", 422, id="not-a-pdf"),
        pytest.param("application/pdf; charset=binary", PDF, 202, id="parameters-allowed"),
    ],
)
def test_upload_validation(
    client: TestClient,
    llm: FakeChatClient,
    alice: User,
    member: Patient,
    content_type: str,
    body: bytes,
    expected_status: int,
) -> None:
    response = upload(client, alice, member.id, body=body, content_type=content_type)

    assert response.status_code == expected_status, response.text


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "streamed"])
def test_uploads_over_the_size_limit_are_refused(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient, chunked: bool
) -> None:
    app.dependency_overrides[get_max_upload_bytes] = lambda: 1024
    body: bytes | Iterator[bytes] = iter([PDF[:800], PDF[800:]]) if chunked else PDF

    response = upload(client, alice, member.id, body=body)

    assert response.status_code == 413
    assert llm.calls == []


def test_the_same_file_twice_is_a_duplicate_for_that_member_only(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    first = upload(client, alice, member.id).json()
    sibling = add(db_session, build_patient(db_session.get_one(Family, member.family_id)))

    again = upload(client, alice, member.id)

    assert again.status_code == 409
    assert again.json()["detail"]["report_id"] == first["id"]
    assert upload(client, alice, sibling.id).status_code == 202


def test_uploads_need_access_to_the_member(
    client: TestClient, llm: FakeChatClient, alice: User, bob: User, member: Patient
) -> None:
    assert upload(client, bob, member.id).status_code == 404
    unauthenticated = client.post(
        f"/patients/{member.id}/reports", content=PDF, headers={"Content-Type": "application/pdf"}
    )
    assert unauthenticated.status_code == 401
    assert llm.calls == []


# --- review and confirm --------------------------------------------------------------------


def _report(db_session: Session, member: Patient, status: str) -> Report:
    return add(db_session, Report(patient_id=member.id, file_sha256="a" * 64, status=status))


@pytest.mark.parametrize("status", ["processing", "failed", "confirmed"])
def test_review_is_only_for_reports_awaiting_review(
    client: TestClient, db_session: Session, alice: User, member: Patient, status: str
) -> None:
    report = _report(db_session, member, status)

    response = client.get(f"/reports/{report.id}/review", headers=auth_headers(alice))

    assert response.status_code == 409


def test_confirm_saves_the_reviewed_rows_to_history(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()

    response = client.post(
        f"/reports/{report_id}/confirm", json=confirm_body(review), headers=auth_headers(alice)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    metrics = db_session.scalars(
        select(Metric).where(Metric.report_id == uuid.UUID(report_id)).order_by(Metric.raw_name)
    ).all()
    assert [(m.raw_name, m.value_numeric, m.value_canonical, m.unit_canonical, m.flag)
            for m in metrics] == [
        ("CREATININE - URINE", Decimal("84.20"), Decimal("84.20"), "mg/dL", "normal"),
        ("FERRITIN", Decimal("48.3"), Decimal("48.3"), "ng/mL", "normal"),
        ("URI. ALBUMIN/CREATININE RATIO (UA/C)", Decimal("15.0"), Decimal("15.0"), "mg/g",
         "normal"),
        ("URINARY MICROALBUMIN", Decimal("12.6"), Decimal("12.6"), "mg/L", "normal"),
    ]  # fmt: skip
    assert {m.patient_id for m in metrics} == {member.id}
    assert {m.collected_at for m in metrics} == {datetime(2025, 3, 3, 8, 15, tzinfo=IST)}
    assert (
        client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).status_code == 409
    )


def test_confirming_indexes_the_report_text_for_search(
    client: TestClient,
    llm: FakeChatClient,
    db_session: Session,
    alice: User,
    member: Patient,
    embedder: FakeEmbedder,
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    client.post(
        f"/reports/{report_id}/confirm", json=confirm_body(review), headers=auth_headers(alice)
    )

    chunks = db_session.scalars(
        select(ReportChunk)
        .where(ReportChunk.report_id == uuid.UUID(report_id))
        .order_by(ReportChunk.chunk_index)
    ).all()
    assert [c.content for c in chunks] == embedder.passages
    assert len(chunks) == 3
    assert {c.patient_id for c in chunks} == {member.id}
    # Only scrubbed text was embedded and stored.
    for value in (fake.NAME, fake.REFERRED_BY, fake.PHONE, fake.EMAIL, fake.URINE_BARCODE):
        assert all(value not in c.content for c in chunks)

    # The saved text is now searchable. (Ranking quality is the real model's job; the fake
    # bag-of-words model is only exact about which chunks can be found.)
    hits = search_report_text(db_session, embedder, [member.id], "ferritin", k=3)
    assert {h.report_id for h in hits} == {uuid.UUID(report_id)}
    assert any("FERRITIN C.M.I.A 48.3 ng/mL" in h.content for h in hits)


def test_saving_values_does_not_depend_on_the_search_index(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    app.dependency_overrides[get_embedder_factory] = lambda: BrokenEmbedder
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()

    response = client.post(
        f"/reports/{report_id}/confirm", json=confirm_body(review), headers=auth_headers(alice)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    count = select(func.count()).where(Metric.report_id == uuid.UUID(report_id))
    assert db_session.scalar(count) == 4
    chunks = select(func.count()).where(ReportChunk.report_id == uuid.UUID(report_id))
    assert db_session.scalar(chunks) == 0


def test_corrections_are_recomputed_on_the_server(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    body = confirm_body(review)
    body["metrics"][0]["value_text"] = "250.0"  # corrected by the user: above 217
    body["metrics"][2]["canonical_metric_id"] = None  # the user un-maps a row
    body["metrics"] = body["metrics"][:3]  # ... and removes one

    client.post(f"/reports/{report_id}/confirm", json=body, headers=auth_headers(alice))

    rows = {m.raw_name: m for m in db_session.scalars(select(Metric))}
    assert len(rows) == 3
    corrected = rows["CREATININE - URINE"]
    assert (corrected.value_numeric, corrected.value_canonical, corrected.flag) == (
        Decimal("250.0"),
        Decimal("250.0"),
        "high",
    )
    unmapped = rows["URI. ALBUMIN/CREATININE RATIO (UA/C)"]
    assert (unmapped.canonical_metric_id, unmapped.value_canonical) == (None, None)


CONFIRM_ERRORS = [
    pytest.param(
        lambda b: b["metrics"][0].update(canonical_metric_id=str(uuid.uuid4())),
        id="unknown-dictionary-entry",
    ),
    pytest.param(lambda b: b["metrics"][0].update(reference_low="300"), id="low-above-high"),
    pytest.param(lambda b: b["metrics"][0].update(reference_high="1e400"), id="absurd-bound"),
    pytest.param(lambda b: b["metrics"][0].update(flag="normal"), id="client-sent-flag"),
    pytest.param(lambda b: b["metrics"][0].update(value_text="   "), id="blank-value"),
    pytest.param(lambda b: b.update(metrics=[]), id="no-rows"),
    pytest.param(lambda b: b.update(collected_at="2999-01-01T00:00:00+05:30"), id="future-date"),
    pytest.param(
        lambda b: b.update(collected_at="2025-03-03T08:15:00"), id="date-without-time-zone"
    ),
]


@pytest.mark.parametrize("change", CONFIRM_ERRORS)
def test_confirm_validation(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient, change: Any
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    body = confirm_body(review)
    change(body)

    response = client.post(f"/reports/{report_id}/confirm", json=body, headers=auth_headers(alice))

    assert response.status_code == 422, response.text


def test_confirm_needs_a_date_when_the_report_had_none(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    db_session.get_one(Report, uuid.UUID(report_id)).collected_at = None
    db_session.flush()
    body = confirm_body(review)

    missing = client.post(f"/reports/{report_id}/confirm", json=body, headers=auth_headers(alice))
    body["collected_at"] = "2025-03-01T09:00:00+05:30"
    given = client.post(f"/reports/{report_id}/confirm", json=body, headers=auth_headers(alice))

    assert missing.status_code == 422
    assert "collection date" in missing.json()["detail"]
    assert given.status_code == 200
    assert datetime.fromisoformat(given.json()["collected_at"]) == datetime(
        2025, 3, 1, 9, 0, tzinfo=IST
    )


def test_a_report_can_only_be_confirmed_once(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    url, body = f"/reports/{report_id}/confirm", confirm_body(review)

    assert client.post(url, json=body, headers=auth_headers(alice)).status_code == 200
    assert client.post(url, json=body, headers=auth_headers(alice)).status_code == 409


# --- retry, file, delete, dictionary ------------------------------------------------------


def test_a_failed_report_can_be_retried(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient
) -> None:
    llm.reply = RuntimeError("provider blew up")
    report = processed(client, alice, member)
    assert (report["status"], report["failure_reason"]) == (
        "failed",
        "Processing failed unexpectedly. Please try again.",
    )
    llm.reply = FakeChatClient().reply  # the provider recovers

    retried = client.post(f"/reports/{report['id']}/retry", headers=auth_headers(alice))

    assert retried.status_code == 202
    after = client.get(f"/reports/{report['id']}", headers=auth_headers(alice)).json()
    assert (after["status"], after["failure_reason"]) == ("pending_review", None)
    again = client.post(f"/reports/{report['id']}/retry", headers=auth_headers(alice))
    assert again.status_code == 409


def test_the_original_pdf_can_be_downloaded(
    client: TestClient, llm: FakeChatClient, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]

    response = client.get(f"/reports/{report_id}/file", headers=auth_headers(alice))

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_deleting_a_report_removes_its_metrics(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    report_id = processed(client, alice, member)["id"]
    review = client.get(f"/reports/{report_id}/review", headers=auth_headers(alice)).json()
    client.post(
        f"/reports/{report_id}/confirm", json=confirm_body(review), headers=auth_headers(alice)
    )

    assert client.delete(f"/reports/{report_id}", headers=auth_headers(alice)).status_code == 204
    assert client.get(f"/reports/{report_id}", headers=auth_headers(alice)).status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Metric)) == 0


REPORT_ROUTES = [
    pytest.param("GET", "", id="status"),
    pytest.param("GET", "/review", id="review"),
    pytest.param("POST", "/confirm", id="confirm"),
    pytest.param("POST", "/retry", id="retry"),
    pytest.param("GET", "/file", id="file"),
    pytest.param("DELETE", "", id="delete"),
]


@pytest.mark.parametrize(("method", "suffix"), REPORT_ROUTES)
def test_other_users_cannot_tell_a_report_exists(
    client: TestClient,
    llm: FakeChatClient,
    alice: User,
    bob: User,
    member: Patient,
    method: str,
    suffix: str,
) -> None:
    report_id = processed(client, alice, member)["id"]
    body = {"metrics": [{"raw_name": "X", "value_text": "1"}]}

    alices = client.request(
        method, f"/reports/{report_id}{suffix}", json=body, headers=auth_headers(bob)
    )
    missing = client.request(
        method, f"/reports/{uuid.uuid4()}{suffix}", json=body, headers=auth_headers(bob)
    )

    assert alices.status_code == missing.status_code == 404
    assert alices.json() == missing.json() == {"detail": "Report not found"}
    assert client.get(f"/reports/{report_id}", headers=auth_headers(alice)).json()["status"] == (
        "pending_review"
    )


def test_metric_dictionary_lists_every_known_test(
    client: TestClient, db_session: Session, alice: User
) -> None:
    seed_metric_dictionary(db_session, load_metric_seeds())

    response = client.get("/metric-dictionary", headers=auth_headers(alice))

    assert response.status_code == 200
    names = {entry["canonical_name"] for entry in response.json()}
    assert {"Haemoglobin", "Ferritin", "Urine Albumin/Creatinine Ratio"} <= names
    assert client.get("/metric-dictionary").status_code == 401


def test_other_families_are_unaffected_by_uploads(
    client: TestClient, llm: FakeChatClient, db_session: Session, alice: User, member: Patient
) -> None:
    other_member = add(db_session, build_patient(add_family(db_session)))

    processed(client, alice, member)

    assert db_session.scalar(select(func.count()).select_from(Report).filter_by(
        patient_id=other_member.id)) == 0  # fmt: skip
