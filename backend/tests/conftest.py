from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.main import app
from tests.db_helpers import run_alembic

# Hosts where the suite may create and drop its test database (local Docker, CI service).
LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine for a dedicated test database, recreated and migrated once per test run.

    Its name is the DATABASE_URL database plus `_test`, so tests never touch dev data.
    """
    admin_url = make_url(get_settings().database_url)
    if admin_url.host not in LOCAL_DB_HOSTS:
        pytest.exit(
            f"Refusing to create a test database on non-local host {admin_url.host!r}. "
            "Point DATABASE_URL at the local Docker database to run tests.",
            returncode=2,
        )
    assert admin_url.database, "DATABASE_URL must name a database"
    test_url = admin_url.set(database=f"{admin_url.database}_test")

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    quoted_name = admin_engine.dialect.identifier_preparer.quote(f"{admin_url.database}_test")
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
        connection.exec_driver_sql(f"CREATE DATABASE {quoted_name}")
    admin_engine.dispose()

    test_engine = create_engine(test_url)
    run_alembic(test_engine, "upgrade", "head")
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose changes, including commits, are rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """API client whose requests use the test's rolled-back session."""

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
