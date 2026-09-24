from collections.abc import Callable
from pathlib import Path
from typing import Literal

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def run_alembic(engine: Engine, action: Literal["upgrade", "downgrade"], revision: str) -> None:
    """Run an Alembic command on `engine` via env.py's shared-connection hook."""
    config = Config(ALEMBIC_INI)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if action == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)


def _apply_in_savepoint(session: Session, change: Callable[[Session], object]) -> None:
    with session.begin_nested():
        change(session)
        session.flush()


def violated_constraint(session: Session, change: Callable[[Session], object]) -> str | None:
    """Apply `change`, expect the database to reject it, and return the constraint's name.

    The change runs in a SAVEPOINT, so the test's session stays usable afterwards.
    """
    with pytest.raises(IntegrityError) as excinfo:
        _apply_in_savepoint(session, change)
    error = excinfo.value.orig
    assert isinstance(error, psycopg.errors.IntegrityError)
    return error.diag.constraint_name


def violated_by_insert(session: Session, *objects: object) -> str | None:
    return violated_constraint(session, lambda s: s.add_all(objects))
