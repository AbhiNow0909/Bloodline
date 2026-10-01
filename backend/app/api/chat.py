"""Ask the query agent about one family member, or across one family (CLAUDE.md Section 4.3).

Both routes resolve their scope through the ownership checks; the agent's tools can only
read the patient ids of that scope. The model sees members only as labels, never names.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import (
    AgentClientFactoryDep,
    DbSession,
    EmbedderFactoryDep,
    OwnedFamily,
    OwnedPatient,
)
from app.config import get_settings
from app.models import Patient
from app.schemas.chat import ChatReply, ChatRequest, ChatSource
from app.services import history
from app.services.agent import ChatScope, ChatTurn, PrivacyGuardError, ToolContext, answer
from app.services.llm import LLMNotConfiguredError, LLMRequestError, LLMUnavailableError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: {"description": "The AI service rejected the request"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The assistant is busy or not set up"},
}


def _chat(
    scope: ChatScope,
    body: ChatRequest,
    db: DbSession,
    agent_factory: AgentClientFactoryDep,
    embedder_factory: EmbedderFactoryDep,
) -> ChatReply:
    today = datetime.now(history.REPORT_TIMEZONE).date()
    try:
        result = answer(
            client=agent_factory(),
            model=get_settings().agent_model,
            tools=ToolContext(db, embedder_factory(), scope, today),
            history=[ChatTurn(m.role, m.content) for m in body.messages],
            today=today,
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    except LLMUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is busy right now. Please try again in a minute.",
        ) from None
    except LLMRequestError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The assistant could not answer that. Please try again.",
        ) from None
    except PrivacyGuardError:
        logger.error("Chat stopped by the privacy guard (scope: %s)", scope.kind)  # no content
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant could not answer that safely. Try asking without names.",
        ) from None

    names = {member.id: member.display_name for member in scope.members}
    return ChatReply(
        reply=result.reply,
        sources=[
            ChatSource(
                report_id=source.report_id,
                collected_at=source.collected_at,
                lab_name=source.lab_name,
                member_id=source.patient_id,
                member_name=names[source.patient_id],
            )
            for source in result.sources
        ],
    )


@router.post("/patients/{patient_id}/chat", responses=_ERRORS)
def member_chat(
    body: ChatRequest,
    patient: OwnedPatient,
    db: DbSession,
    agent_factory: AgentClientFactoryDep,
    embedder_factory: EmbedderFactoryDep,
) -> ChatReply:
    """Ask about one family member's results. The model knows them only as "the patient"."""
    return _chat(ChatScope.for_member(patient), body, db, agent_factory, embedder_factory)


@router.post(
    "/families/{family_id}/chat",
    responses={**_ERRORS, status.HTTP_409_CONFLICT: {"description": "The family has no members"}},
)
def family_chat(
    body: ChatRequest,
    family: OwnedFamily,
    db: DbSession,
    agent_factory: AgentClientFactoryDep,
    embedder_factory: EmbedderFactoryDep,
) -> ChatReply:
    """Ask across a family ("who has high LDL?"). The model knows members as "Member A", ..."""
    members = list(db.scalars(select(Patient).where(Patient.family_id == family.id)))
    if not members:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Add a family member first.")
    scope = ChatScope.for_family(family.name, members)
    return _chat(scope, body, db, agent_factory, embedder_factory)
