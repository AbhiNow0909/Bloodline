"""Plain-language explanations of a member's findings (the findings are in `history`)."""

import uuid

from pydantic import BaseModel

from app.schemas.chat import DISCLAIMER
from app.schemas.history import InsightKind


class InsightExplanation(BaseModel):
    metric_id: uuid.UUID
    kind: InsightKind  # the finding it explains; shown only while that is still the finding
    text: str


class InsightExplanations(BaseModel):
    explanations: list[InsightExplanation]
    disclaimer: str = DISCLAIMER
