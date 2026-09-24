from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.security import create_access_token
from app.services.users import create_user
from tests.factories import add, auth_headers, build_user

PASSWORD = "correct horse battery staple"


@pytest.fixture
def alice(db_session: Session) -> User:
    return create_user(
        db_session, email="alice@example.test", password=PASSWORD, display_name="Alice Example"
    )


def _login(client: TestClient, email: str, password: str) -> Any:
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_returns_a_token_that_works(client: TestClient, alice: User) -> None:
    response = _login(client, "alice@example.test", PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().jwt_expire_minutes * 60
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == {
        "id": str(alice.id),
        "email": "alice@example.test",
        "display_name": "Alice Example",
    }


def test_login_email_is_case_insensitive(client: TestClient, alice: User) -> None:
    assert _login(client, " Alice@Example.TEST ", PASSWORD).status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client: TestClient, alice: User) -> None:
    wrong_password = _login(client, "alice@example.test", "a different password")
    unknown_email = _login(client, "nobody@example.test", PASSWORD)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Invalid email or password"}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"email": "alice@example.test"}, id="missing-password"),
        pytest.param({"email": "alice@example.test", "password": "x" * 1025}, id="huge-password"),
        pytest.param({"email": "a@b.c", "password": PASSWORD, "remember": True}, id="extra-field"),
    ],
)
def test_login_rejects_malformed_requests(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/auth/login", json=body).status_code == 422


def test_me_requires_a_bearer_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param("Basic YWxpY2U6cGFzc3dvcmQ=", id="basic-scheme"),
        pytest.param("Bearer not-a-token", id="garbage-token"),
    ],
)
def test_me_rejects_bad_credentials(client: TestClient, authorization: str) -> None:
    assert client.get("/auth/me", headers={"Authorization": authorization}).status_code == 401


def test_me_rejects_an_expired_token(client: TestClient, alice: User) -> None:
    token = create_access_token(alice.id, now=datetime.now(UTC) - timedelta(days=2))

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_me_rejects_the_token_of_a_deleted_user(
    client: TestClient, db_session: Session, alice: User
) -> None:
    headers = auth_headers(alice)
    db_session.delete(alice)
    db_session.flush()

    assert client.get("/auth/me", headers=headers).status_code == 401


def test_validation_errors_never_echo_the_submitted_password(client: TestClient) -> None:
    secret = "my-secret-password-" + "x" * 1024

    response = client.post("/auth/login", json={"email": "a@example.test", "password": secret})

    assert response.status_code == 422
    assert "my-secret-password" not in response.text
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "password"]
    assert "input" not in error


def test_unreadable_stored_hash_fails_like_a_wrong_password(
    client: TestClient, db_session: Session
) -> None:
    add(db_session, build_user(email="broken@example.test", password_hash="not-a-real-hash"))

    broken = _login(client, "broken@example.test", PASSWORD)
    unknown = _login(client, "nobody@example.test", PASSWORD)

    assert broken.status_code == unknown.status_code == 401
    assert broken.json() == unknown.json()
