"""Run once when the server starts, before it takes requests.

Usage (the Docker image runs it before uvicorn):

    python -m app.cli.startup

Reports are read inside the server process, so a report being read when the server stopped
(a deploy, a restart, or Render's free tier going to sleep) would stay "being read" forever.
They are marked failed with a message saying so; the person can then try reading it again.
"""

import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_engine
from app.services.ingestion import fail_interrupted_reports


def main() -> int:
    try:
        with Session(get_engine()) as session:
            count = fail_interrupted_reports(session)
    except SQLAlchemyError as exc:
        # Never stop the server from starting; /health reports a database it cannot reach.
        print(f"startup: interrupted reports not checked ({type(exc).__name__})", file=sys.stderr)
        return 0
    print(f"startup: {count} interrupted report(s) marked as failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
