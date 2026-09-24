"""Builders for model instances with synthetic, clearly fake data.

`build_*` returns an unsaved object; `add` persists it (flush only, so ids exist).
Parents must be added before building children, because ids are assigned at flush.
"""

import hashlib
import itertools
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
    User,
)
from app.security import create_access_token

_sequence = itertools.count(1)


def add[T: Base](session: Session, instance: T) -> T:
    session.add(instance)
    session.flush()
    return instance


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def build_user(**overrides: Any) -> User:
    n = next(_sequence)
    fields: dict[str, Any] = {
        "email": f"user{n}@example.test",
        "password_hash": "not-a-real-hash",
        "display_name": f"Test User {n}",
    }
    return User(**(fields | overrides))


def build_family(owner: User, **overrides: Any) -> Family:
    fields: dict[str, Any] = {"owner_id": owner.id, "name": f"Test Family {next(_sequence)}"}
    return Family(**(fields | overrides))


def build_patient(family: Family, **overrides: Any) -> Patient:
    fields: dict[str, Any] = {
        "family_id": family.id,
        "display_name": f"Test Patient {next(_sequence)}",
        "sex": "female",
    }
    return Patient(**(fields | overrides))


def add_family(session: Session, owner: User | None = None, **overrides: Any) -> Family:
    """A persisted family, with a new owner unless one is given."""
    return add(session, build_family(owner or add(session, build_user()), **overrides))


def add_patient(session: Session, family: Family | None = None, **overrides: Any) -> Patient:
    """A persisted family member, in a new family (with a new owner) unless one is given."""
    return add(session, build_patient(family or add_family(session), **overrides))


def build_report(patient: Patient, **overrides: Any) -> Report:
    fields: dict[str, Any] = {
        "patient_id": patient.id,
        "file_sha256": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
    }
    return Report(**(fields | overrides))


def build_canonical_metric(**overrides: Any) -> CanonicalMetric:
    fields: dict[str, Any] = {
        "canonical_name": f"Test Marker {next(_sequence)}",
        "category": "Test Panel",
        "canonical_unit": "mg/dL",
        "description": "Synthetic marker used only in tests.",
    }
    return CanonicalMetric(**(fields | overrides))


def build_metric(report: Report, **overrides: Any) -> Metric:
    fields: dict[str, Any] = {
        "patient_id": report.patient_id,
        "report_id": report.id,
        "raw_name": "HAEMOGLOBIN",
        "value_numeric": Decimal("13.5"),
        "unit": "g/dL",
        "collected_at": datetime(2025, 1, 15, 8, 0, tzinfo=UTC),
    }
    return Metric(**(fields | overrides))


def build_chunk(report: Report, **overrides: Any) -> ReportChunk:
    fields: dict[str, Any] = {
        "patient_id": report.patient_id,
        "report_id": report.id,
        "chunk_index": 0,
        "content": "Synthetic report text used only in tests.",
        "embedding": [0.0] * (EMBEDDING_DIMENSIONS - 1) + [1.0],
    }
    return ReportChunk(**(fields | overrides))
