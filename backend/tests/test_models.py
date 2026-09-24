from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.models import (
    EMBEDDING_DIMENSIONS,
    Base,
    CanonicalMetric,
    Family,
    Metric,
    Patient,
    Report,
    ReportChunk,
    ReportFile,
    User,
)
from tests.db_helpers import violated_by_insert, violated_constraint
from tests.factories import (
    add,
    add_family,
    add_patient,
    build_canonical_metric,
    build_chunk,
    build_family,
    build_metric,
    build_patient,
    build_report,
    build_user,
)

SYNTHETIC_PDF = b"%PDF-1.7\n% synthetic test file, not a real report\n"
IST = timezone(timedelta(hours=5, minutes=30))


def _report(session: Session) -> Report:
    return add(session, build_report(add_patient(session)))


def test_create_read_update_delete_round_trip(db_session: Session) -> None:
    user = add(db_session, build_user())
    family = add(db_session, build_family(user, name="Synthetic Family"))
    patient = add(db_session, build_patient(family, sex="male", date_of_birth=date(1970, 1, 1)))
    marker = add(db_session, build_canonical_metric(aliases=["TM", "Test-M"]))
    report = add(
        db_session,
        build_report(patient, lab_name="Synthetic Lab", raw_extraction={"tests": [{"n": 1}]}),
    )
    add(db_session, ReportFile(report_id=report.id, content=SYNTHETIC_PDF))
    metric = add(db_session, build_metric(report, canonical_metric_id=marker.id))
    add(db_session, build_chunk(report))
    db_session.commit()
    db_session.expire_all()

    stored_report = db_session.get_one(Report, report.id)
    assert stored_report.status == "processing"  # server default
    assert stored_report.raw_extraction == {"tests": [{"n": 1}]}
    assert db_session.get_one(ReportFile, report.id).content == SYNTHETIC_PDF
    stored_family = db_session.get_one(Family, family.id)
    assert (stored_family.owner_id, stored_family.name) == (user.id, "Synthetic Family")
    assert db_session.get_one(Patient, patient.id).family_id == family.id
    assert db_session.get_one(CanonicalMetric, marker.id).aliases == ["TM", "Test-M"]
    stored_metric = db_session.get_one(Metric, metric.id)
    assert stored_metric.canonical_metric_id == marker.id
    assert stored_metric.flag == "unknown"  # server default

    stored_report.status = "pending_review"
    db_session.commit()
    db_session.expire_all()
    assert db_session.get_one(Report, report.id).status == "pending_review"

    db_session.delete(stored_metric)
    db_session.commit()
    assert db_session.get(Metric, metric.id) is None


def test_values_round_trip_without_loss(db_session: Session) -> None:
    collected_at = datetime(2025, 3, 14, 8, 30, tzinfo=IST)
    embedding = [i / EMBEDDING_DIMENSIONS for i in range(EMBEDDING_DIMENSIONS)]
    report = _report(db_session)
    metric = add(
        db_session,
        build_metric(
            report,
            value_numeric=Decimal("5.60"),
            reference_low=Decimal("0.50"),
            reference_high=Decimal("5.50"),
            collected_at=collected_at,
        ),
    )
    chunk = add(db_session, build_chunk(report, embedding=embedding))
    db_session.expire_all()

    stored = db_session.get_one(Metric, metric.id)
    assert str(stored.value_numeric) == "5.60"  # printed precision kept exactly
    assert str(stored.reference_low) == "0.50"
    assert stored.collected_at == collected_at
    assert stored.collected_at.tzinfo is not None
    assert db_session.get_one(ReportChunk, chunk.id).embedding == pytest.approx(embedding)


def test_embedding_must_have_384_dimensions(db_session: Session) -> None:
    report = _report(db_session)

    with pytest.raises(DataError, match="expected 384 dimensions"):
        add(db_session, build_chunk(report, embedding=[0.1] * (EMBEDDING_DIMENSIONS - 1)))


CHECK_VIOLATIONS: dict[str, tuple[Callable[[Session], Base], str]] = {
    "sex outside male/female": (
        lambda s: build_patient(add_family(s), sex="other"),
        "ck_patients_sex_valid",
    ),
    "email not lowercase": (
        lambda s: build_user(email="Someone@Example.test"),
        "ck_users_email_lowercase",
    ),
    "unknown report status": (
        lambda s: build_report(add_patient(s), status="archived"),
        "ck_reports_status_valid",
    ),
    "file hash not sha256 hex": (
        lambda s: build_report(add_patient(s), file_sha256="not-a-hash"),
        "ck_reports_file_sha256_hex",
    ),
    "unknown metric flag": (
        lambda s: build_metric(_report(s), flag="critical"),
        "ck_metrics_flag_valid",
    ),
    "metric without a value": (
        lambda s: build_metric(_report(s), value_numeric=None, value_text=None),
        "ck_metrics_has_value",
    ),
    "reference low above high": (
        lambda s: build_metric(
            _report(s), reference_low=Decimal("10"), reference_high=Decimal("5")
        ),
        "ck_metrics_reference_range_ordered",
    ),
    "negative chunk index": (
        lambda s: build_chunk(_report(s), chunk_index=-1),
        "ck_report_chunks_chunk_index_non_negative",
    ),
}


@pytest.mark.parametrize(
    ("build_invalid", "constraint"), CHECK_VIOLATIONS.values(), ids=CHECK_VIOLATIONS.keys()
)
def test_check_constraints_reject_invalid_values(
    db_session: Session, build_invalid: Callable[[Session], Base], constraint: str
) -> None:
    assert violated_by_insert(db_session, build_invalid(db_session)) == constraint


def test_email_is_unique(db_session: Session) -> None:
    add(db_session, build_user(email="same@example.test"))

    constraint = violated_by_insert(db_session, build_user(email="same@example.test"))

    assert constraint == "uq_users_email"


def test_family_name_is_unique_per_owner(db_session: Session) -> None:
    owner = add(db_session, build_user())
    add(db_session, build_family(owner, name="Sharma Family"))

    constraint = violated_by_insert(db_session, build_family(owner, name="Sharma Family"))
    assert constraint == "uq_families_owner_id_name"

    # Another user may use the same name for their own family.
    add_family(db_session, name="Sharma Family")


def test_duplicate_upload_is_detected_per_patient_only(db_session: Session) -> None:
    patient = add_patient(db_session)
    other_patient = add_patient(db_session)
    first = add(db_session, build_report(patient))

    constraint = violated_by_insert(
        db_session, build_report(patient, file_sha256=first.file_sha256)
    )
    assert constraint == "uq_reports_patient_id_file_sha256"

    # The same file for a different patient is allowed, so dedupe never reveals other patients.
    add(db_session, build_report(other_patient, file_sha256=first.file_sha256))


def test_canonical_name_is_unique(db_session: Session) -> None:
    add(db_session, build_canonical_metric(canonical_name="Duplicate Marker"))

    constraint = violated_by_insert(
        db_session, build_canonical_metric(canonical_name="Duplicate Marker")
    )

    assert constraint == "uq_metric_dictionary_canonical_name"


def test_chunk_index_is_unique_per_report(db_session: Session) -> None:
    report = _report(db_session)
    add(db_session, build_chunk(report, chunk_index=0))

    constraint = violated_by_insert(db_session, build_chunk(report, chunk_index=0))

    assert constraint == "uq_report_chunks_report_id_chunk_index"


def test_metric_cannot_point_at_another_patients_report(db_session: Session) -> None:
    alice = add_patient(db_session)
    bob = add_patient(db_session)
    alices_report = add(db_session, build_report(alice))

    constraint = violated_by_insert(db_session, build_metric(alices_report, patient_id=bob.id))

    assert constraint == "fk_metrics_report_id_patient_id_reports"


def test_chunk_cannot_point_at_another_patients_report(db_session: Session) -> None:
    alice = add_patient(db_session)
    bob = add_patient(db_session)
    alices_report = add(db_session, build_report(alice))

    constraint = violated_by_insert(db_session, build_chunk(alices_report, patient_id=bob.id))

    assert constraint == "fk_report_chunks_report_id_patient_id_reports"


def _count(session: Session, model: type[Base], **filters: object) -> int:
    query = select(func.count()).select_from(model).filter_by(**filters)
    return session.scalar(query) or 0


def _add_member_with_data(session: Session, family: Family) -> tuple[Patient, Report]:
    patient = add(session, build_patient(family))
    report = add(session, build_report(patient))
    add(session, ReportFile(report_id=report.id, content=SYNTHETIC_PDF))
    add(session, build_metric(report))
    add(session, build_chunk(report))
    return patient, report


def _assert_member_data_gone(session: Session, patient: Patient, report: Report) -> None:
    assert session.get(Patient, patient.id) is None
    assert _count(session, Report, patient_id=patient.id) == 0
    assert _count(session, ReportFile, report_id=report.id) == 0
    assert _count(session, Metric, patient_id=patient.id) == 0
    assert _count(session, ReportChunk, patient_id=patient.id) == 0


def test_deleting_a_patient_removes_all_their_data(db_session: Session) -> None:
    family = add_family(db_session)
    patient, report = _add_member_with_data(db_session, family)
    _, sibling_report = _add_member_with_data(db_session, family)

    db_session.delete(patient)
    db_session.flush()
    db_session.expunge_all()

    _assert_member_data_gone(db_session, patient, report)
    assert db_session.get(Family, family.id) is not None
    assert db_session.get(Report, sibling_report.id) is not None


def test_deleting_a_family_removes_its_members_and_their_data(db_session: Session) -> None:
    owner = add(db_session, build_user())
    family = add(db_session, build_family(owner))
    other_family = add(db_session, build_family(owner))
    patient, report = _add_member_with_data(db_session, family)
    _, other_report = _add_member_with_data(db_session, other_family)

    db_session.delete(family)
    db_session.flush()
    db_session.expunge_all()

    _assert_member_data_gone(db_session, patient, report)
    assert db_session.get(User, owner.id) is not None
    assert db_session.get(Report, other_report.id) is not None


def test_deleting_a_user_removes_their_families(db_session: Session) -> None:
    user = add(db_session, build_user())
    family = add(db_session, build_family(user))
    patient, report = _add_member_with_data(db_session, family)
    other_family = add_family(db_session)

    db_session.delete(user)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(Family, family.id) is None
    _assert_member_data_gone(db_session, patient, report)
    assert db_session.get(Family, other_family.id) is not None


def test_dictionary_entry_in_use_cannot_be_deleted(db_session: Session) -> None:
    marker = add(db_session, build_canonical_metric())
    add(db_session, build_metric(_report(db_session), canonical_metric_id=marker.id))

    constraint = violated_constraint(db_session, lambda s: s.delete(marker))

    assert constraint == "fk_metrics_canonical_metric_id_metric_dictionary"
