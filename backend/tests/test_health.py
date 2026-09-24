from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app


def test_health_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


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
    assert response.json() == {"status": "error", "database": "unreachable"}
