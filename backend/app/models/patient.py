import uuid
from datetime import date
from typing import Literal, get_args

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, check_in

Sex = Literal["male", "female"]
AccessRole = Literal["owner", "viewer"]


class Patient(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A family member whose reports are tracked. Not a login account."""

    __tablename__ = "patients"
    __table_args__ = (check_in("sex", get_args(Sex), name="sex_valid"),)

    display_name: Mapped[str]
    # Required: it selects the sex-specific reference range.
    sex: Mapped[str]
    date_of_birth: Mapped[date | None]


class UserPatientAccess(CreatedAtMixin, Base):
    """Which users may see (viewer) or manage (owner) which patients."""

    __tablename__ = "user_patient_access"
    __table_args__ = (check_in("role", get_args(AccessRole), name="role_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str]
