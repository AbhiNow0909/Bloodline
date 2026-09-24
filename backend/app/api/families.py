"""Families: a user's folders of family members. Only a family's creator can see it; every
`{family_id}` route resolves it through `get_owned_family` (404 for anyone else)."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, OwnedFamily
from app.models import Family, Patient
from app.schemas.family import FamilyRead, FamilyWrite
from app.schemas.patient import PatientCreate, PatientRead

router = APIRouter(prefix="/families", tags=["families"])

_DUPLICATE_NAME = {"description": "You already have a family with this name"}


def _patient_count(db: Session, family_id: uuid.UUID) -> int:
    count = db.scalar(select(func.count()).select_from(Patient).filter_by(family_id=family_id))
    return count or 0


def _to_read(db: Session, family: Family) -> FamilyRead:
    return FamilyRead(
        id=family.id,
        name=family.name,
        created_at=family.created_at,
        patient_count=_patient_count(db, family.id),
    )


def _ensure_name_is_free(db: Session, owner_id: uuid.UUID, name: str) -> None:
    taken = db.scalar(select(Family.id).where(Family.owner_id == owner_id, Family.name == name))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_DUPLICATE_NAME["description"])


@router.get("")
def list_families(user: CurrentUser, db: DbSession) -> list[FamilyRead]:
    """The current user's families, with how many members each has."""
    rows = db.execute(
        select(Family, func.count(Patient.id))
        .outerjoin(Patient, Patient.family_id == Family.id)
        .where(Family.owner_id == user.id)
        .group_by(Family.id)
        .order_by(Family.name)
    ).tuples()
    return [
        FamilyRead(id=f.id, name=f.name, created_at=f.created_at, patient_count=count)
        for f, count in rows
    ]


@router.post(
    "", status_code=status.HTTP_201_CREATED, responses={status.HTTP_409_CONFLICT: _DUPLICATE_NAME}
)
def create_family(body: FamilyWrite, user: CurrentUser, db: DbSession) -> FamilyRead:
    _ensure_name_is_free(db, user.id, body.name)
    family = Family(owner_id=user.id, name=body.name)
    db.add(family)
    db.commit()
    return _to_read(db, family)


@router.get("/{family_id}")
def get_family(family: OwnedFamily, db: DbSession) -> FamilyRead:
    return _to_read(db, family)


@router.patch("/{family_id}", responses={status.HTTP_409_CONFLICT: _DUPLICATE_NAME})
def rename_family(body: FamilyWrite, family: OwnedFamily, db: DbSession) -> FamilyRead:
    if body.name != family.name:
        _ensure_name_is_free(db, family.owner_id, body.name)
        family.name = body.name
        db.commit()
    return _to_read(db, family)


@router.delete("/{family_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family(family: OwnedFamily, db: DbSession) -> Response:
    """Delete the family and, by cascade, its members and all their reports and data."""
    db.delete(family)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{family_id}/patients")
def list_family_patients(family: OwnedFamily, db: DbSession) -> list[PatientRead]:
    """The family's members."""
    patients = db.scalars(
        select(Patient)
        .where(Patient.family_id == family.id)
        .order_by(Patient.display_name, Patient.created_at)
    )
    return [PatientRead.model_validate(patient) for patient in patients]


@router.post("/{family_id}/patients", status_code=status.HTTP_201_CREATED)
def add_family_patient(body: PatientCreate, family: OwnedFamily, db: DbSession) -> PatientRead:
    """Add a member to the family."""
    patient = Patient(family_id=family.id, **body.model_dump())
    db.add(patient)
    db.commit()
    return PatientRead.model_validate(patient)
