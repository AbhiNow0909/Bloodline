"""Password hashing (Argon2id via pwdlib) and access tokens (HS256 JWTs via PyJWT)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

_password_hash = PasswordHash.recommended()
# Raise (instead of only warning) if the signing key is shorter than HS256 requires.
_jwt = jwt.PyJWT(options={"enforce_minimum_key_length": True})
# Verified against when an email is unknown, so a login takes the same time either way.
_DUMMY_HASH = _password_hash.hash("dummy password for constant-time login failures")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (matches, new_hash). new_hash is set when the stored hash uses outdated
    parameters and should be replaced.

    An unreadable stored hash counts as a mismatch (after the same amount of work), so it
    can neither crash login nor reveal through a different response that the account exists.
    """
    try:
        return _password_hash.verify_and_update(password, password_hash)
    except UnknownHashError:
        logger.warning("Stored password hash has an unrecognized format")
        spend_verify_time(password)
        return False, None


def spend_verify_time(password: str) -> None:
    """Do the work of one failed verification (used when no user matches)."""
    _password_hash.verify(password, _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID, *, now: datetime | None = None) -> str:
    settings = get_settings()
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return _jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id of a valid token. Raises `jwt.InvalidTokenError` otherwise
    (bad signature, wrong algorithm, expired, missing claims, malformed subject)."""
    claims = _jwt.decode(
        token,
        get_settings().jwt_secret.get_secret_value(),
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )
    try:
        return uuid.UUID(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError("token subject is not a user id") from exc
