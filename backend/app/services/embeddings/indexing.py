"""Index a confirmed report's scrubbed text for vector search (CLAUDE.md Section 4.1, step 8).

Runs as a background task right after a report is confirmed, with its own session, so saving
values stays fast on a small CPU and a problem with the embedding model never stops a user
from saving their results. Indexing is idempotent: it replaces the report's chunks, so a
report can be re-indexed at any time (`python -m app.cli.rag reindex`).
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.models import Report, ReportChunk
from app.services.embeddings.chunking import chunk_report
from app.services.embeddings.embedder import Embedder
from app.services.ingestion import StoredProcessing

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


class NotIndexableError(Exception):
    """Only confirmed reports with stored text can be indexed."""


def index_report(session: Session, report: Report, embedder: Embedder) -> int:
    """Replace the report's chunks with fresh ones from its stored scrubbed text. Returns how
    many chunks were stored. The caller commits."""
    if report.status != "confirmed" or report.raw_extraction is None:
        raise NotIndexableError(f"Report {report.id} is {report.status}, not confirmed.")
    stored = StoredProcessing.model_validate(report.raw_extraction)
    texts = chunk_report(stored.extraction.pages)
    # Embed first: if the model fails, the report keeps whatever chunks it had.
    vectors = embedder.embed_passages(texts)
    session.execute(delete(ReportChunk).where(ReportChunk.report_id == report.id))
    session.add_all(
        ReportChunk(
            patient_id=report.patient_id,
            report_id=report.id,
            chunk_index=index,
            content=content,
            embedding=vector,
        )
        for index, (content, vector) in enumerate(zip(texts, vectors, strict=True))
    )
    session.flush()
    return len(texts)


def index_report_task(
    report_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    embedder_factory: Callable[[], Embedder],
) -> None:
    """Background task after confirm. Failures are logged (report id and error type only:
    database errors can carry the report text in their parameters) and never raised."""
    with session_factory() as session:
        report = session.get(Report, report_id)
        if report is None or report.status != "confirmed":
            return  # deleted meanwhile
        try:
            count = index_report(session, report, embedder_factory())
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Could not index report %s (%s)", report_id, type(exc).__name__)
            return
    logger.info("Indexed report %s: %d chunks", report_id, count)


def reports_to_index(session: Session, *, include_indexed: bool = False) -> list[uuid.UUID]:
    """Confirmed reports, oldest first: by default only those without chunks yet."""
    statement = select(Report.id).where(Report.status == "confirmed")
    if not include_indexed:
        statement = statement.where(~exists().where(ReportChunk.report_id == Report.id))
    return list(session.scalars(statement.order_by(Report.created_at)))
