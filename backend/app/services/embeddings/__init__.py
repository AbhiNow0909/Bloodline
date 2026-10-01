"""Local embeddings of scrubbed report text and patient-scoped vector search (Phase 12)."""

from app.services.embeddings.chunking import chunk_report
from app.services.embeddings.embedder import Embedder, EmbeddingError, FastEmbedder, get_embedder
from app.services.embeddings.indexing import (
    NotIndexableError,
    index_report,
    index_report_task,
    reports_to_index,
)
from app.services.embeddings.search import ChunkHit, search_report_text

__all__ = [
    "ChunkHit",
    "Embedder",
    "EmbeddingError",
    "FastEmbedder",
    "NotIndexableError",
    "chunk_report",
    "get_embedder",
    "index_report",
    "index_report_task",
    "reports_to_index",
    "search_report_text",
]
