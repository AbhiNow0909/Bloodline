from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are stored normalized, so uniqueness is case-insensitive.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    display_name: Mapped[str]
