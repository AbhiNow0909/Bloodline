import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Family(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A group of family members owned by one user (a folder, in the app's file-system
    model). Only its owner can see it, its members, or anything under them."""

    __tablename__ = "families"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]
