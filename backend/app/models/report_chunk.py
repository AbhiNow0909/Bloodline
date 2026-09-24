import uuid

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

# BAAI/bge-small-en-v1.5 produces 384-dimensional embeddings.
EMBEDDING_DIMENSIONS = 384


class ReportChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A chunk of scrubbed report text and its embedding, for patient-scoped vector search."""

    __tablename__ = "report_chunks"
    __table_args__ = (
        # The report must belong to the same patient as the chunk.
        ForeignKeyConstraint(
            ["report_id", "patient_id"],
            ["reports.id", "reports.patient_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("report_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        # Every vector search filters on patient_id first.
        Index("ix_report_chunks_patient_id", "patient_id"),
        Index(
            "ix_report_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID]
    chunk_index: Mapped[int]
    content: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS))
