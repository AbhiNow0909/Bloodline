"""User accounts: creation (CLI only, no public sign-up) and login verification."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password, spend_verify_time, verify_password

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserError(ValueError):
    """A user account could not be created as requested."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(session: Session, *, email: str, password: str, display_name: str) -> User:
    """Add a new user (flushed, not committed)."""
    email = normalize_email(email)
    display_name = display_name.strip()
    if not _EMAIL_PATTERN.fullmatch(email):
        raise UserError(f"{email!r} is not a valid email address")
    if not display_name:
        raise UserError("display name must not be blank")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise UserError(
            f"password must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters long"
        )
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise UserError(f"a user with email {email} already exists")

    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the user if the credentials are valid, else None.

    Unknown emails and wrong passwords take the same time and give the same result, so
    callers cannot tell which emails have accounts. If the stored hash uses outdated
    parameters it is replaced on the user object; the caller commits.
    """
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        spend_verify_time(password)
        return None
    matches, upgraded_hash = verify_password(password, user.password_hash)
    if not matches:
        return None
    if upgraded_hash is not None:
        user.password_hash = upgraded_hash
    return user
