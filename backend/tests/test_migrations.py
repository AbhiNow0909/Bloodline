import uuid
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.models import Base
from tests.db_helpers import run_alembic

EXPECTED_TABLES = {
    "users",
    "patients",
    "families",
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


PHASE_3_REVISION = "5eefbab520ce"  # before families existed


def _insert(engine: Engine, sql: str, rows: list[dict[str, Any]]) -> None:
    with engine.begin() as connection:
        connection.execute(text(sql), rows)


def _cleanup(engine: Engine, user_ids: list[uuid.UUID], patient_ids: list[uuid.UUID]) -> None:
    """Return the shared test database to head with the test's rows removed."""
    run_alembic(engine, "upgrade", "head")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM patients WHERE id = ANY(:ids)"), {"ids": patient_ids})
        connection.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})


ADD_USER = (
    "INSERT INTO users (id, email, password_hash, display_name) VALUES (:id, :email, 'x', 'T')"
)
ADD_PATIENT_V3 = "INSERT INTO patients (id, display_name, sex) VALUES (:id, 'Test', 'female')"


def test_upgrade_moves_existing_patients_into_one_family_per_owner(engine: Engine) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    mum, dad, gran = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        run_alembic(engine, "downgrade", PHASE_3_REVISION)
        _insert(
            engine,
            ADD_USER,
            [
                {"id": alice, "email": "alice@example.test"},
                {"id": bob, "email": "bob@example.test"},
            ],
        )
        _insert(engine, ADD_PATIENT_V3, [{"id": mum}, {"id": dad}, {"id": gran}])
        _insert(
            engine,
            "INSERT INTO user_patient_access (user_id, patient_id, role) VALUES (:u, :p, :r)",
            [
                {"u": alice, "p": mum, "r": "owner"},
                {"u": alice, "p": dad, "r": "owner"},
                {"u": bob, "p": gran, "r": "owner"},
                {"u": bob, "p": mum, "r": "viewer"},  # viewers do not get a copy
            ],
        )

        run_alembic(engine, "upgrade", "head")

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT p.id, f.id AS family_id, f.owner_id, f.name "
                    "FROM patients p JOIN families f ON f.id = p.family_id "
                    "WHERE p.id = ANY(:ids)"
                ),
                {"ids": [mum, dad, gran]},
            ).all()
        placed = {row.id: (row.owner_id, row.name) for row in rows}
        assert placed == {
            mum: (alice, "My family"),
            dad: (alice, "My family"),
            gran: (bob, "My family"),
        }
        families = {row.id: row.family_id for row in rows}
        assert families[mum] == families[dad] != families[gran]
    finally:
        _cleanup(engine, [alice, bob], [mum, dad, gran])


def test_downgrade_rebuilds_owner_access_from_families(engine: Engine) -> None:
    owner, family, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        _insert(engine, ADD_USER, [{"id": owner, "email": "owner@example.test"}])
        _insert(
            engine,
            "INSERT INTO families (id, owner_id, name) VALUES (:id, :owner, 'Test Family')",
            [{"id": family, "owner": owner}],
        )
        _insert(
            engine,
            "INSERT INTO patients (id, family_id, display_name, sex) "
            "VALUES (:id, :family, 'Test', 'male')",
            [{"id": member, "family": family}],
        )

        run_alembic(engine, "downgrade", PHASE_3_REVISION)

        with engine.connect() as connection:
            access = connection.execute(
                text("SELECT user_id, role FROM user_patient_access WHERE patient_id = :p"),
                {"p": member},
            ).all()
        assert [tuple(row) for row in access] == [(owner, "owner")]
    finally:
        _cleanup(engine, [owner], [member])


def test_upgrade_refuses_patients_without_an_owner(engine: Engine) -> None:
    orphan = uuid.uuid4()
    run_alembic(engine, "downgrade", PHASE_3_REVISION)
    try:
        _insert(engine, ADD_PATIENT_V3, [{"id": orphan}])

        with pytest.raises(DBAPIError, match="no owner"):
            run_alembic(engine, "upgrade", "head")
    finally:
        _insert(engine, "DELETE FROM patients WHERE id = :id", [{"id": orphan}])
        _cleanup(engine, [], [])
