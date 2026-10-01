"""Semantic search over report text, always limited to given family members.

Principle 2 (CLAUDE.md): the hard `patient_id` filter is part of the SQL, never left to
similarity. Callers pass the exact patient ids they resolved through an ownership check: one
member, or the members of one family. Principle 4: this is for free text (methods, notes,
printed ranges); numbers and trends come from the metrics tables.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Report, ReportChunk
from app.services.embeddings.embedder import Embedder

DEFAULT_K = 5
MAX_K = 20
MAX_QUERY_CHARS = 500


@dataclass(frozen=True)
class ChunkHit:
    patient_id: uuid.UUID
    report_id: uuid.UUID
    collected_at: datetime | None
    lab_name: str | None
    chunk_index: int
    content: str
    score: float  # cosine similarity, 1 = same meaning


def search_report_text(
    session: Session,
    embedder: Embedder,
    patient_ids: Collection[uuid.UUID],
    query: str,
    k: int = DEFAULT_K,
) -> list[ChunkHit]:
    """The `k` chunks of these members' reports closest in meaning to `query`, best first."""
    query = " ".join(query.split())[:MAX_QUERY_CHARS]
    ids = list(patient_ids)
    if not ids or not query:
        return []
    k = max(1, min(k, MAX_K))
    vector = embedder.embed_query(query)

    # With a filter, a plain HNSW scan can stop before finding k matching rows. Iterative
    # scans (pgvector >= 0.8) keep going, in exact distance order. Lasts for this transaction.
    session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    distance = ReportChunk.embedding.cosine_distance(vector)
    rows = session.execute(
        select(ReportChunk, Report.collected_at, Report.lab_name, distance)
        .join(Report, Report.id == ReportChunk.report_id)
        .where(ReportChunk.patient_id.in_(ids))
        .order_by(distance, ReportChunk.id)
        .limit(k)
    ).tuples()
    return [
        ChunkHit(
            patient_id=chunk.patient_id,
            report_id=chunk.report_id,
            collected_at=collected_at,
            lab_name=lab_name,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            score=1.0 - float(dist),
        )
        for chunk, collected_at, lab_name, dist in rows
    ]
