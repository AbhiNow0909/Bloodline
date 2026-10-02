"""Shared FastAPI dependencies: database session, current user, and access to families,
family members (patients) and their reports through family ownership."""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, get_engine
from app.models import Family, Patient, Report, User
from app.security import decode_access_token
from app.services.embeddings import Embedder, get_embedder
from app.services.llm import (
    AgentClient,
    ChatClient,
    get_agent_client,
    get_explanation_client,
    get_structuring_client,
)

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


def get_owned_family(family_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Family:
    """Resolve `{family_id}` for the current user. Every route with `{family_id}` in its path
    must depend on this (a test enforces it).

    Only a family's creator can see it; for anyone else it is a 404, exactly like a family
    that does not exist, so its existence is never revealed.
    """
    family = db.scalar(select(Family).where(Family.id == family_id, Family.owner_id == user.id))
    if family is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Family not found")
    return family


OwnedFamily = Annotated[Family, Depends(get_owned_family)]


def get_owned_patient(patient_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Patient:
    """Resolve `{patient_id}` for the current user: the patient's family must be theirs.
    Every route with `{patient_id}` in its path must depend on this (a test enforces it).

    Missing access is a 404, identical to a nonexistent id.
    """
    patient = db.scalar(
        select(Patient)
        .join(Family, Family.id == Patient.family_id)
        .where(Patient.id == patient_id, Family.owner_id == user.id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


OwnedPatient = Annotated[Patient, Depends(get_owned_patient)]


def get_owned_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Report:
    """Resolve `{report_id}` for the current user: the report's family member must be in one
    of their families. Every route with `{report_id}` in its path must depend on this (a test
    enforces it). Missing access is a 404, identical to a nonexistent id.
    """
    report = db.scalar(
        select(Report)
        .join(Patient, Patient.id == Report.patient_id)
        .join(Family, Family.id == Patient.family_id)
        .where(Report.id == report_id, Family.owner_id == user.id)
    )
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


OwnedReport = Annotated[Report, Depends(get_owned_report)]


# --- background processing (overridden in tests) ------------------------------------------


def get_session_factory() -> Callable[[], AbstractContextManager[Session]]:
    """Background tasks open their own session; the request's is closed before they run."""
    return lambda: Session(get_engine())


def get_client_factory() -> Callable[[], ChatClient]:
    """Resolved inside the task, so a missing GROQ_API_KEY fails the report, not the upload."""
    return get_structuring_client


def get_agent_client_factory() -> Callable[[], AgentClient]:
    """Resolved inside the chat route, so a missing GROQ_API_KEY becomes a clear 503."""
    return get_agent_client


def get_explanation_client_factory() -> Callable[[], ChatClient]:
    """Resolved inside the explain route, so a missing GROQ_API_KEY becomes a clear 503."""
    return get_explanation_client


def get_embedder_factory() -> Callable[[], Embedder]:
    """Resolved inside the indexing task: the model is loaded only when first needed."""
    return get_embedder


SessionFactoryDep = Annotated[
    Callable[[], AbstractContextManager[Session]], Depends(get_session_factory)
]
ClientFactoryDep = Annotated[Callable[[], ChatClient], Depends(get_client_factory)]
EmbedderFactoryDep = Annotated[Callable[[], Embedder], Depends(get_embedder_factory)]
AgentClientFactoryDep = Annotated[Callable[[], AgentClient], Depends(get_agent_client_factory)]
ExplanationClientFactoryDep = Annotated[
    Callable[[], ChatClient], Depends(get_explanation_client_factory)
]
