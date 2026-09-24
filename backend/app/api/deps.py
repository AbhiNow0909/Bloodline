"""Shared FastAPI dependencies: database session, current user, patient access."""

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Patient, User, UserPatientAccess
from app.security import decode_access_token

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid or expired token") from None
    user = db.get(User, user_id)
    if user is None:  # deleted since the token was issued
        raise _unauthorized("Invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(frozen=True)
class PatientAccess:
    patient: Patient
    role: str


def get_patient_access(patient_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PatientAccess:
    """Resolve `{patient_id}` for the current user.

    Every route with `{patient_id}` in its path must depend on this (a test enforces it).
    Missing access is a 404, not a 403, so other patients' existence is never revealed.
    """
    row = (
        db.execute(
            select(Patient, UserPatientAccess.role)
            .join(UserPatientAccess, UserPatientAccess.patient_id == Patient.id)
            .where(Patient.id == patient_id, UserPatientAccess.user_id == user.id)
        )
        .tuples()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    patient, role = row
    return PatientAccess(patient=patient, role=role)


PatientAccessDep = Annotated[PatientAccess, Depends(get_patient_access)]


def require_owner(access: PatientAccessDep) -> PatientAccess:
    if access.role != "owner":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Only an owner of this patient can do this"
        )
    return access


OwnerAccess = Annotated[PatientAccess, Depends(require_owner)]
