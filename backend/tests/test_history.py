"""History over confirmed data: reports, catalog, time series, out-of-range, family overview."""

import hashlib
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.models import CanonicalMetric, Family, Metric, Patient, Report, User
from app.services import history
from app.services.extraction.header import IST
from tests.factories import add, add_family, auth_headers, build_family, build_patient, build_user


def D(text: str) -> Decimal:  # noqa: N802 - reads like a literal
    return Decimal(text)


@pytest.fixture
def dictionary(db_session: Session) -> dict[str, CanonicalMetric]:
    seed_metric_dictionary(db_session, load_metric_seeds())
    return {m.canonical_name: m for m in db_session.scalars(select(CanonicalMetric))}


@pytest.fixture
def alice(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def family(db_session: Session, alice: User) -> Family:
    return add(db_session, build_family(alice, name="Sharma Family"))


@pytest.fixture
def mum(db_session: Session, family: Family) -> Patient:
    return add(db_session, build_patient(family, display_name="Mum", sex="female"))


@pytest.fixture
def dad(db_session: Session, family: Family) -> Patient:
    return add(db_session, build_patient(family, display_name="Dad", sex="male"))


def record(
    session: Session,
    patient: Patient,
    when: datetime,
    *readings: dict[str, Any],
    status: str = "confirmed",
) -> Report:
    """A report collected at `when` with the given readings (flags as confirm would set)."""
    report = add(
        session,
        Report(
            patient_id=patient.id,
            file_sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            status=status,
            collected_at=when if status == "confirmed" else None,
        ),
    )
    for reading in readings:
        fields: dict[str, Any] = {
            "patient_id": patient.id,
            "report_id": report.id,
            "collected_at": when,
            "raw_name": "TEST",
            "value_text": str(reading.get("value_numeric", "1")),
            "flag": "normal",
        } | reading
        add(session, Metric(**fields))
    return report


def at(year: int, month: int, day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def ferritin(d: dict[str, CanonicalMetric], value: str, flag: str) -> dict[str, Any]:
    return {
        "canonical_metric_id": d["Ferritin"].id,
        "raw_name": "FERRITIN",
        "value_numeric": D(value),
        "unit": "ng/mL",
        "value_canonical": D(value),
        "unit_canonical": "ng/mL",
        "reference_low": D("4.63"),
        "reference_high": D("204.00"),
        "flag": flag,
    }


def creatinine(d: dict[str, CanonicalMetric], value: str, flag: str) -> dict[str, Any]:
    return {
        "canonical_metric_id": d["Creatinine"].id,
        "raw_name": "CREATININE",
        "value_numeric": D(value),
        "unit": "mg/dL",
        "value_canonical": D(value),
        "unit_canonical": "mg/dL",
        "reference_low": D("0.6"),
        "reference_high": D("1.1"),
        "flag": flag,
    }


# --- reports -------------------------------------------------------------------------------


def test_reports_are_listed_newest_first_with_counts(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
    dad: Patient,
) -> None:
    january = record(
        db_session, mum, at(2025, 1, 10),
        ferritin(dictionary, "3.1", "low"), creatinine(dictionary, "0.9", "normal"),
    )  # fmt: skip
    march = record(db_session, mum, at(2025, 3, 10), ferritin(dictionary, "40", "normal"))
    uploading = record(db_session, mum, at(2025, 4, 1), status="processing")
    record(db_session, dad, at(2025, 5, 1), creatinine(dictionary, "2.0", "high"))

    listed = client.get(f"/patients/{mum.id}/reports", headers=auth_headers(alice)).json()

    # An unconfirmed report has no collection time yet; it sorts by upload time (now).
    assert [(r["id"], r["metric_count"], r["flagged_count"]) for r in listed] == [
        (str(uploading.id), 0, 0),
        (str(march.id), 1, 0),
        (str(january.id), 2, 1),
    ]


def test_a_reports_values(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
) -> None:
    confirmed = record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    pending = record(db_session, mum, at(2025, 2, 1), status="pending_review")

    values = client.get(f"/reports/{confirmed.id}/metrics", headers=auth_headers(alice)).json()
    none_yet = client.get(f"/reports/{pending.id}/metrics", headers=auth_headers(alice)).json()

    assert [(v["raw_name"], v["value_numeric"], v["flag"]) for v in values] == [
        ("FERRITIN", "3.1", "low")
    ]
    assert none_yet == []


# --- catalog -------------------------------------------------------------------------------


def test_catalog_lists_each_test_with_its_latest_reading(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
    dad: Patient,
) -> None:
    record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    record(
        db_session, mum, at(2025, 3, 10),
        ferritin(dictionary, "40", "normal"), creatinine(dictionary, "0.9", "normal"),
        {"raw_name": "MYSTERY INDEX", "value_numeric": D("7"), "value_text": "7"},
    )  # fmt: skip
    record(db_session, dad, at(2025, 6, 1), ferritin(dictionary, "500", "high"))

    catalog = client.get(f"/patients/{mum.id}/metrics", headers=auth_headers(alice)).json()

    summary = [
        (e["name"], e["metric"] and e["metric"]["category"], e["reading_count"],
         e["latest"]["value_numeric"], e["latest"]["flag"])
        for e in catalog
    ]  # fmt: skip
    assert summary == [
        ("Ferritin", "Iron Studies", 2, "40", "normal"),
        ("Creatinine", "Kidney Function", 1, "0.9", "normal"),
        ("MYSTERY INDEX", None, 1, "7", "normal"),  # unmapped tests come last
    ]
    first_seen = datetime.fromisoformat(catalog[0]["first_collected_at"])
    assert first_seen == at(2025, 1, 10)
    assert catalog[0]["metric"]["description"]  # what the marker relates to, for explanations


# --- time series ---------------------------------------------------------------------------


def test_history_is_oldest_first_with_ranges_in_the_canonical_unit(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
) -> None:
    albumin = dictionary["Albumin"]  # canonical unit g/dL
    base = {"canonical_metric_id": albumin.id, "raw_name": "ALBUMIN", "flag": "normal"}
    record(db_session, mum, at(2025, 3, 1), base | {
        "value_numeric": D("4.1"), "unit": "g/dL", "value_canonical": D("4.1"),
        "unit_canonical": "g/dL", "reference_low": D("3.5"), "reference_high": D("5.2"),
    })  # fmt: skip
    record(db_session, mum, at(2025, 1, 1), base | {
        "value_numeric": D("45"), "unit": "g/L", "value_canonical": D("4.5"),
        "unit_canonical": "g/dL", "reference_low": D("35"), "reference_high": D("50"),
    })  # fmt: skip

    result = client.get(
        f"/patients/{mum.id}/metrics/{albumin.id}", headers=auth_headers(alice)
    ).json()

    assert result["metric"]["canonical_unit"] == "g/dL"
    points = [
        (p["value_numeric"], p["unit"], p["value_canonical"],
         p["reference_low_canonical"], p["reference_high_canonical"])
        for p in result["points"]
    ]  # fmt: skip
    assert points == [
        ("45", "g/L", "4.5", "3.5", "5.0"),  # January, printed in g/L
        ("4.1", "g/dL", "4.1", "3.5", "5.2"),  # March
    ]


def test_date_filters_are_inclusive_calendar_days_in_indian_time(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
) -> None:
    for when, value in [
        (at(2024, 12, 31, 23, 50), "10"),
        (at(2025, 1, 1, 0, 10), "11"),
        (at(2025, 1, 31, 23, 50), "12"),
        (at(2025, 2, 1, 0, 10), "13"),
    ]:
        record(db_session, mum, when, ferritin(dictionary, value, "normal"))
    url = f"/patients/{mum.id}/metrics/{dictionary['Ferritin'].id}"

    january = client.get(
        url, params={"start": "2025-01-01", "end": "2025-01-31"}, headers=auth_headers(alice)
    ).json()

    assert [p["value_numeric"] for p in january["points"]] == ["11", "12"]


def test_history_errors_and_empty_series(
    client: TestClient, dictionary: dict[str, CanonicalMetric], alice: User, mum: Patient
) -> None:
    url = f"/patients/{mum.id}/metrics"
    headers = auth_headers(alice)

    unknown = client.get(f"{url}/{uuid.uuid4()}", headers=headers)
    backwards = client.get(
        f"{url}/{dictionary['Ferritin'].id}",
        params={"start": "2025-02-01", "end": "2025-01-01"},
        headers=headers,
    )
    never_tested = client.get(f"{url}/{dictionary['TSH'].id}", headers=headers)

    assert unknown.status_code == 404
    assert backwards.status_code == 422
    assert never_tested.status_code == 200
    assert never_tested.json()["points"] == []


# --- out of range --------------------------------------------------------------------------


def test_out_of_range_defaults_to_what_is_flagged_now(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    mum: Patient,
) -> None:
    record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    record(
        db_session, mum, at(2025, 3, 10),
        ferritin(dictionary, "40", "normal"),  # recovered
        creatinine(dictionary, "1.4", "high"),
        {"raw_name": "NOTE", "value_text": "Haemolysed", "flag": "unknown"},
    )  # fmt: skip
    url, headers = f"/patients/{mum.id}/out-of-range", auth_headers(alice)

    now = client.get(url, headers=headers).json()
    ever = client.get(url, params={"latest_only": "false"}, headers=headers).json()
    since_march = client.get(
        url, params={"latest_only": "false", "since": "2025-03-01"}, headers=headers
    ).json()

    assert [(r["name"], r["flag"]) for r in now] == [("Creatinine", "high")]
    assert [(r["name"], r["flag"]) for r in ever] == [("Ferritin", "low"), ("Creatinine", "high")]
    assert [r["name"] for r in since_march] == ["Creatinine"]


def test_services_read_exactly_the_patients_given(
    db_session: Session, dictionary: dict[str, CanonicalMetric], mum: Patient, dad: Patient
) -> None:
    record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    record(db_session, dad, at(2025, 1, 12), creatinine(dictionary, "1.9", "high"))
    stranger = add(db_session, build_patient(add_family(db_session)))
    record(db_session, stranger, at(2025, 1, 15), creatinine(dictionary, "2.5", "high"))

    def patients(ids: list[uuid.UUID]) -> set[uuid.UUID]:
        return {r.patient_id for r in history.out_of_range(db_session, ids)}

    assert patients([mum.id]) == {mum.id}
    assert patients([mum.id, dad.id]) == {mum.id, dad.id}
    assert patients([]) == set()
    assert {e.latest.patient_id for e in history.metric_catalog(db_session, dad.id)} == {dad.id}


# --- family overview -----------------------------------------------------------------------


def test_family_overview_shows_each_members_latest_out_of_range_values(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    alice: User,
    family: Family,
    mum: Patient,
    dad: Patient,
) -> None:
    record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    record(db_session, mum, at(2025, 3, 10), creatinine(dictionary, "1.4", "high"))
    record(db_session, dad, at(2025, 2, 1), ferritin(dictionary, "80", "normal"))
    add(db_session, build_patient(family, display_name="Baby", sex="female"))  # no reports yet
    other = add(db_session, build_patient(add_family(db_session), display_name="Stranger"))
    record(db_session, other, at(2025, 1, 1), ferritin(dictionary, "1", "low"))

    overview = client.get(f"/families/{family.id}/overview", headers=auth_headers(alice)).json()

    assert overview["name"] == "Sharma Family"
    members = {m["patient"]["display_name"]: m for m in overview["members"]}
    assert list(members) == ["Baby", "Dad", "Mum"]
    assert [(r["name"], r["flag"]) for r in members["Mum"]["out_of_range"]] == [
        ("Ferritin", "low"),
        ("Creatinine", "high"),
    ]
    assert members["Mum"]["tracked_metric_count"] == 2
    assert datetime.fromisoformat(members["Mum"]["latest_report_at"]) == at(2025, 3, 10)
    assert members["Dad"]["out_of_range"] == []
    assert (members["Baby"]["tracked_metric_count"], members["Baby"]["latest_report_at"]) == (
        0,
        None,
    )


def test_history_routes_are_private_to_the_family_owner(
    client: TestClient,
    db_session: Session,
    dictionary: dict[str, CanonicalMetric],
    family: Family,
    mum: Patient,
) -> None:
    report = record(db_session, mum, at(2025, 1, 10), ferritin(dictionary, "3.1", "low"))
    bob = auth_headers(add(db_session, build_user()))
    ferritin_id = dictionary["Ferritin"].id

    for url in (
        f"/patients/{mum.id}/reports",
        f"/reports/{report.id}/metrics",
        f"/patients/{mum.id}/metrics",
        f"/patients/{mum.id}/metrics/{ferritin_id}",
        f"/patients/{mum.id}/out-of-range",
        f"/families/{family.id}/overview",
    ):
        assert client.get(url, headers=bob).status_code == 404, url
        assert client.get(url).status_code == 401, url


def test_day_start_is_midnight_in_indian_time() -> None:
    assert history.day_start(date(2025, 1, 1)) == datetime(2025, 1, 1, tzinfo=IST)
