import uuid
from datetime import date
from typing import Literal, get_args

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, check_in

Sex = Literal["male", "female"]


class Patient(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A family member whose reports are tracked (the UI says "family member").
    Not a login account; belongs to exactly one family."""

    __tablename__ = "patients"
    __table_args__ = (check_in("sex", get_args(Sex), name="sex_valid"),)

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str]
    # Required: it selects the sex-specific reference range.
    sex: Mapped[str]
    date_of_birth: Mapped[date | None]
