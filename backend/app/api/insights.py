"""A member's findings (range flags and trend alerts, computed in code) and their plain-language
explanations (written by the model on request). Every route resolves its scope through an
ownership check."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, ExplanationClientFactoryDep, OwnedPatient
from app.config import get_settings
from app.schemas.history import Insight
from app.schemas.insights import InsightExplanations
from app.services import insights
from app.services.agent import ChatScope, PrivacyGuardError
from app.services.llm import LLMNotConfiguredError, LLMRequestError, LLMUnavailableError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["insights"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: {"description": "The AI service could not write them"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The AI service is busy or not set up"},
}


@router.get("/patients/{patient_id}/insights")
def member_insights(patient: OwnedPatient, db: DbSession) -> list[Insight]:
    """What the member's results show, most important first: tests whose latest result is
    outside the lab's range, results still within the range that changed a lot across the
    last few results, and results back within the range."""
    return insights.member_insights(db, [patient.id])[patient.id]


@router.post("/patients/{patient_id}/insights/explain", responses=_ERRORS)
def explain_member_insights(
    patient: OwnedPatient, db: DbSession, client_factory: ExplanationClientFactoryDep
) -> InsightExplanations:
    """Plain-language explanations of the member's current findings (at most
    `MAX_EXPLAINED`). The model sees only facts about each test, never a name."""
    found = insights.member_insights(db, [patient.id])[patient.id]
    if not found:
        return InsightExplanations(explanations=[])
    try:
        explanations = insights.explain_insights(
            client_factory(), get_settings().agent_model, ChatScope.for_member(patient), found
        )
    except LLMNotConfiguredError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not set, so explanations are not available.",
        ) from None
    except LLMUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is busy right now. Please try again in a minute.",
        ) from None
    except (LLMRequestError, insights.ExplanationError):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="The explanations could not be written. Please try again.",
        ) from None
    except PrivacyGuardError:
        logger.error("Explanations stopped by the privacy guard")  # no content
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The explanations could not be written safely.",
        ) from None
    return InsightExplanations(explanations=explanations)
