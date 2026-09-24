import uuid
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, check_in

ReportStatus = Literal["processing", "pending_review", "confirmed", "failed"]


class Report(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        # Duplicate-upload detection is per patient, so it never reveals other patients' data.
        UniqueConstraint("patient_id", "file_sha256"),
        # Target of the composite foreign keys that keep metrics/chunks on the same patient.
        UniqueConstraint("id", "patient_id"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="file_sha256_hex"),
        check_in("status", get_args(ReportStatus), name="status_valid"),
        Index("ix_reports_patient_id_collected_at", "patient_id", "collected_at"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    lab_name: Mapped[str | None]
    collected_at: Mapped[datetime | None]
    file_sha256: Mapped[str]
    status: Mapped[str] = mapped_column(default="processing", server_default="processing")
    failure_reason: Mapped[str | None]
    raw_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReportFile(Base):
    """The original PDF, kept apart from `reports` so listing reports never loads file bytes."""

    __tablename__ = "report_files"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)
