"""Create a login account. There is no public sign-up; accounts are made with this command.

Usage (from backend/, or inside the api container):

    python -m app.cli.create_user --email you@example.com --name "Your Name"

The password is prompted for (twice) and never accepted as an argument, so it does not end
up in shell history. For scripts, pipe it in with --password-stdin.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db import get_engine
from app.services.users import MIN_PASSWORD_LENGTH, UserError, create_user


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.create_user", description="Create a Bloodline login account."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="display name shown in the app")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of stdin instead of prompting",
    )
    return parser.parse_args(argv)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass(f"Password (at least {MIN_PASSWORD_LENGTH} characters): ")
    if getpass.getpass("Repeat password: ") != password:
        raise UserError("passwords do not match")
    return password


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        password = _read_password(args.password_stdin)
        with Session(get_engine()) as session, session.begin():
            user = create_user(session, email=args.email, password=password, display_name=args.name)
            email, user_id = user.email, user.id
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created user {email} (id {user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
