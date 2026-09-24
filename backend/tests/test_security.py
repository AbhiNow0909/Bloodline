import base64
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.config import get_settings
from app.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
PASSWORD = "correct horse battery staple"


def _claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"sub": str(USER_ID), "iat": now, "exp": now + timedelta(hours=1)} | overrides


def _sign(claims: dict[str, Any], key: str | None = None, algorithm: str = ALGORITHM) -> str:
    secret = get_settings().jwt_secret.get_secret_value() if key is None else key
    return jwt.encode(claims, secret, algorithm=algorithm)


def _without(claim: str) -> dict[str, Any]:
    return {k: v for k, v in _claims().items() if k != claim}


def _tampered() -> str:
    """A valid token whose payload is swapped for another user's, keeping the signature."""
    header, _, signature = create_access_token(USER_ID).split(".")
    forged = json.dumps(_claims(sub=str(uuid.uuid4())), default=lambda d: int(d.timestamp()))
    payload = base64.urlsafe_b64encode(forged.encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed
    assert verify_password(PASSWORD, hashed) == (True, None)
    assert verify_password("a different password", hashed)[0] is False


def test_token_round_trip() -> None:
    assert decode_access_token(create_access_token(USER_ID)) == USER_ID


def test_token_lifetime_comes_from_settings() -> None:
    token = create_access_token(USER_ID, now=datetime(2030, 1, 1, tzinfo=UTC))
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["exp"] - claims["iat"] == get_settings().jwt_expire_minutes * 60


INVALID_TOKENS: dict[str, Callable[[], str]] = {
    "expired": lambda: create_access_token(USER_ID, now=datetime.now(UTC) - timedelta(days=2)),
    "wrong secret": lambda: _sign(_claims(), key="another-secret-that-is-long-enough-0123"),
    "unsigned (alg none)": lambda: jwt.encode(_claims(), None, algorithm="none"),
    "other algorithm": lambda: _sign(_claims(), key="k" * 64, algorithm="HS512"),
    "tampered payload": _tampered,
    "missing exp": lambda: _sign(_without("exp")),
    "missing iat": lambda: _sign(_without("iat")),
    "missing sub": lambda: _sign(_without("sub")),
    "subject not a user id": lambda: _sign(_claims(sub="alice")),
    "not a jwt": lambda: "not.a.jwt",
}


@pytest.mark.parametrize("make_token", INVALID_TOKENS.values(), ids=INVALID_TOKENS.keys())
def test_invalid_tokens_are_rejected(make_token: Callable[[], str]) -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(make_token())
