"""Maintain and try out the report-text search index.

Usage (from backend/, or inside the api container):

    python -m app.cli.rag reindex          # index confirmed reports that have no chunks yet
    python -m app.cli.rag reindex --all    # rebuild every confirmed report's chunks
    python -m app.cli.rag search --member <member id> "how was ferritin measured"

`reindex` is for reports confirmed before indexing existed, or after a failed background
index, or after changing the chunking or the model. `search` is a developer tool: it prints
the matching report text for one family member, so run it only on your own data.
"""

import argparse
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Patient, Report
from app.services.embeddings import (
    EmbeddingError,
    get_embedder,
    index_report,
    reports_to_index,
    search_report_text,
)
from app.services.embeddings.search import MAX_K


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.rag", description="Index and search report text."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    reindex = commands.add_parser("reindex", help="index confirmed reports for search")
    reindex.add_argument(
        "--all", action="store_true", help="rebuild every report, not just unindexed ones"
    )
    search = commands.add_parser("search", help="search one family member's report text")
    search.add_argument("--member", required=True, type=uuid.UUID, help="family member id")
    search.add_argument("--k", type=int, default=5, choices=range(1, MAX_K + 1), metavar="K")
    search.add_argument("query")
    return parser.parse_args(argv)


def _reindex(session: Session, *, include_indexed: bool) -> int:
    report_ids = reports_to_index(session, include_indexed=include_indexed)
    embedder = get_embedder()
    chunks = 0
    for report_id in report_ids:
        report = session.get_one(Report, report_id)
        chunks += index_report(session, report, embedder)
        session.commit()  # one report at a time: progress survives an interruption
    reports = "report" if len(report_ids) == 1 else "reports"
    print(f"indexed {len(report_ids)} {reports} ({chunks} chunks)")
    return 0


def _search(session: Session, member_id: uuid.UUID, query: str, k: int) -> int:
    if session.get(Patient, member_id) is None:
        print("error: no family member with that id", file=sys.stderr)
        return 1
    hits = search_report_text(session, get_embedder(), [member_id], query, k)
    if not hits:
        print("no indexed report text for this member")
    for hit in hits:
        when = hit.collected_at.date().isoformat() if hit.collected_at else "date unknown"
        print(f"--- {hit.score:.3f}  {when}  report {hit.report_id}  chunk {hit.chunk_index}")
        print(hit.content)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with Session(get_engine()) as session:
            if args.command == "reindex":
                return _reindex(session, include_indexed=args.all)
            return _search(session, args.member, args.query, args.k)
    except EmbeddingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
