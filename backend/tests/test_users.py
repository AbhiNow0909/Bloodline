import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.orm import Session

from app.services.users import UserError, authenticate, create_user
from tests.factories import add, build_user

PASSWORD = "correct horse battery staple"


def test_create_user_normalizes_input_and_hashes_the_password(db_session: Session) -> None:
    user = create_user(
        db_session, email="  Alice@Example.TEST ", password=PASSWORD, display_name="  Alice  "
    )

    assert user.email == "alice@example.test"
    assert user.display_name == "Alice"
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


@pytest.mark.parametrize(
    ("email", "password", "display_name", "message"),
    [
        pytest.param("not-an-email", PASSWORD, "Alice", "not a valid email", id="bad-email"),
        pytest.param("a b@example.test", PASSWORD, "Alice", "not a valid email", id="space"),
        pytest.param("a@example.test", "too short", "Alice", "12 to 1024", id="short-password"),
        pytest.param("a@example.test", "x" * 1025, "Alice", "12 to 1024", id="long-password"),
        pytest.param("a@example.test", PASSWORD, "   ", "display name", id="blank-name"),
    ],
)
def test_create_user_rejects_invalid_input(
    db_session: Session, email: str, password: str, display_name: str, message: str
) -> None:
    with pytest.raises(UserError, match=message):
        create_user(db_session, email=email, password=password, display_name=display_name)


def test_create_user_rejects_duplicate_email_in_any_case(db_session: Session) -> None:
    create_user(db_session, email="alice@example.test", password=PASSWORD, display_name="Alice")

    with pytest.raises(UserError, match="already exists"):
        create_user(db_session, email="ALICE@example.test", password=PASSWORD, display_name="A")


def test_authenticate(db_session: Session) -> None:
    user = create_user(
        db_session, email="alice@example.test", password=PASSWORD, display_name="Alice"
    )

    assert authenticate(db_session, " ALICE@example.test", PASSWORD) is user
    assert authenticate(db_session, "alice@example.test", "a different password") is None
    assert authenticate(db_session, "nobody@example.test", PASSWORD) is None


def test_authenticate_upgrades_an_outdated_hash(db_session: Session) -> None:
    weak_hasher = Argon2Hasher(time_cost=1, memory_cost=8192, parallelism=1)
    weak_hash = PasswordHash((weak_hasher,)).hash(PASSWORD)
    user = add(db_session, build_user(password_hash=weak_hash))

    assert authenticate(db_session, user.email, PASSWORD) is user
    assert user.password_hash != weak_hash
    assert user.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
