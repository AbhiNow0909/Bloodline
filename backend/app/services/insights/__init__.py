"""Range flags and trend alerts (computed in code) and their plain-language explanations."""

from app.services.insights.explain import (
    MAX_EXPLAINED,
    SYSTEM_PROMPT,
    ExplanationError,
    explain_insights,
)
from app.services.insights.rules import family_overview, member_insights, series_insight

__all__ = [
    "MAX_EXPLAINED",
    "SYSTEM_PROMPT",
    "ExplanationError",
    "explain_insights",
    "family_overview",
    "member_insights",
    "series_insight",
]
