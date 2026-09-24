import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, PastDate, StringConstraints, model_validator

from app.models import Sex

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName
    sex: Sex
    date_of_birth: PastDate | None = None


class PatientUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    sex: Sex | None = None
    date_of_birth: PastDate | None = None  # explicit null clears it

    @model_validator(mode="after")
    def required_fields_are_not_null(self) -> Self:
        for field in ("display_name", "sex"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class PatientRead(BaseModel):
    """A family member."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    family_id: uuid.UUID
    display_name: str
    sex: Sex
    date_of_birth: date | None
    created_at: datetime
