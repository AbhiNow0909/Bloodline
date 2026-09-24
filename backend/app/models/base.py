import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint and index names, so migrations can refer to them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this as a plain class attribute
        str: Text(),
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=-1)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=1)


def check_in(column: str, allowed: Iterable[str], name: str) -> CheckConstraint:
    """CHECK constraint restricting a text column to fixed values (used instead of PG enums)."""
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)
