"""`python -m app.cli.rag`: reindex reports and try a search."""

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli import rag as cli
from app.models import ReportChunk
from app.services.embeddings import EmbeddingError, index_report
from tests.embedding_helpers import FakeEmbedder, add_confirmed_report
from tests.factories import add_patient


@pytest.fixture
def cli_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Run the CLI on the test's rolled-back connection, with the fake embedding model."""
    monkeypatch.setattr(cli, "get_engine", db_session.connection)
    monkeypatch.setattr(cli, "get_embedder", FakeEmbedder)
    return db_session


def _chunk_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ReportChunk)) or 0


def test_reindex_indexes_only_reports_without_chunks_unless_asked(
    cli_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    patient = add_patient(cli_session)
    done = add_confirmed_report(cli_session, patient)
    index_report(cli_session, done, FakeEmbedder())
    add_confirmed_report(cli_session, patient)

    assert cli.main(["reindex"]) == 0
    assert capsys.readouterr().out == "indexed 1 report (3 chunks)\n"
    assert _chunk_count(cli_session) == 6

    assert cli.main(["reindex"]) == 0
    assert capsys.readouterr().out == "indexed 0 reports (0 chunks)\n"

    assert cli.main(["reindex", "--all"]) == 0
    assert capsys.readouterr().out == "indexed 2 reports (6 chunks)\n"
    assert _chunk_count(cli_session) == 6


def test_search_prints_one_members_matching_text(
    cli_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    patient = add_patient(cli_session)
    other = add_patient(cli_session)
    for member in (patient, other):
        index_report(cli_session, add_confirmed_report(cli_session, member), FakeEmbedder())

    assert cli.main(["search", "--member", str(patient.id), "--k", "1", "ferritin"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("--- ")
    assert "2025-03-03" in out
    assert out.count("--- ") == 1


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["search", "--member", str(uuid.uuid4()), "ferritin"], "no family member with that id"),
    ],
)
def test_search_errors(
    cli_session: Session, capsys: pytest.CaptureFixture[str], argv: Sequence[str], message: str
) -> None:
    assert cli.main(argv) == 1
    assert message in capsys.readouterr().err


def test_a_missing_model_is_reported_without_a_traceback(
    cli_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Missing:
        def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
            raise EmbeddingError("The embedding model BAAI/bge-small-en-v1.5 could not be loaded.")

        def embed_query(self, text: str) -> list[float]:
            raise EmbeddingError("The embedding model BAAI/bge-small-en-v1.5 could not be loaded.")

    monkeypatch.setattr(cli, "get_embedder", Missing)
    add_confirmed_report(cli_session, add_patient(cli_session))

    assert cli.main(["reindex"]) == 1
    assert "could not be loaded" in capsys.readouterr().err
