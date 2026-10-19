from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.main import app


def test_health_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "dev"}


def test_health_returns_503_when_database_unreachable(client: TestClient) -> None:
    # A real engine aimed at a closed port, so the connection genuinely fails.
    engine = create_engine(
        "postgresql+psycopg://bloodline:bloodline@127.0.0.1:1/bloodline",
        connect_args={"connect_timeout": 2},
    )

    def unreachable_db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = unreachable_db
    try:
        response = client.get("/health")
    finally:
        engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unreachable", "version": "dev"}


def test_the_version_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_VERSION", "1a2b3c4d")  # set at image build time, as on Render
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "jwt_secret": "s" * 32,
    }

    assert Settings(_env_file=None, **values).app_version == "1a2b3c4d"
