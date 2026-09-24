import getpass
import io

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli import create_user as cli
from app.models import User
from app.security import verify_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def cli_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Run the CLI on the test's rolled-back connection instead of the dev database."""
    monkeypatch.setattr(cli, "get_engine", db_session.connection)
    return db_session


def _user_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User)) or 0


def test_creates_a_user_with_the_password_from_stdin(
    cli_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\n"))

    code = cli.main(["--email", "Carol@Example.test", "--name", "Carol", "--password-stdin"])

    assert code == 0
    assert "created user carol@example.test" in capsys.readouterr().out
    user = cli_session.scalars(select(User).where(User.email == "carol@example.test")).one()
    assert user.display_name == "Carol"
    assert verify_password(PASSWORD, user.password_hash)[0]


def test_prompted_passwords_must_match(
    cli_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter([PASSWORD, "a different password"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))

    code = cli.main(["--email", "carol@example.test", "--name", "Carol"])

    assert code == 1
    assert "passwords do not match" in capsys.readouterr().err
    assert _user_count(cli_session) == 0


@pytest.mark.parametrize(
    ("stdin", "message"),
    [
        pytest.param("short\n", "12 to 1024", id="short-password"),
        pytest.param(f"{PASSWORD}\n", "already exists", id="duplicate-email"),
    ],
)
def test_reports_errors_without_a_traceback(
    cli_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin: str,
    message: str,
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{PASSWORD}\n"))
    cli.main(["--email", "dave@example.test", "--name", "Dave", "--password-stdin"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))

    code = cli.main(["--email", "dave@example.test", "--name", "Dave", "--password-stdin"])

    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert message in err
    assert "Traceback" not in err
