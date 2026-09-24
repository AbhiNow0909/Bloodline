from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.models import Base
from tests.db_helpers import run_alembic

EXPECTED_TABLES = {
    "users",
    "patients",
    "user_patient_access",
    "reports",
    "report_files",
    "metric_dictionary",
    "metrics",
    "report_chunks",
}

VECTOR_EXTENSION_VERSION = text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")


def test_upgrade_creates_all_tables_and_the_vector_extension(engine: Engine) -> None:
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        vector_version = connection.scalar(VECTOR_EXTENSION_VERSION)

    assert tables >= EXPECTED_TABLES
    assert vector_version is not None


def test_models_match_migrations(engine: Engine) -> None:
    # Fails when a model changes without a matching migration (or vice versa).
    # Alembic cannot compare CHECK constraints, so those are covered by test_models.py.
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_server_default": True})
        diff = compare_metadata(context, Base.metadata)

    assert diff == []


def test_downgrade_to_base_then_upgrade_to_head(engine: Engine) -> None:
    try:
        run_alembic(engine, "downgrade", "base")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            assert connection.scalar(VECTOR_EXTENSION_VERSION) is None
    finally:
        # Leave the shared test database migrated for the tests that follow.
        run_alembic(engine, "upgrade", "head")

    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) >= EXPECTED_TABLES
