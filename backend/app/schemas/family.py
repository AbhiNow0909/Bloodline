import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

FamilyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class FamilyWrite(BaseModel):
    """Body for creating or renaming a family."""

    model_config = ConfigDict(extra="forbid")

    name: FamilyName


class FamilyRead(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    patient_count: int
