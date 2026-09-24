from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping recovers from connections dropped while Neon scales to zero.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with Session(get_engine()) as session:
        yield session
