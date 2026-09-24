import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, check_in

MetricFlag = Literal["low", "normal", "high", "unknown"]


class CanonicalMetric(UUIDPrimaryKeyMixin, Base):
    """One entry of the metric dictionary: a biomarker and the names labs print for it."""

    __tablename__ = "metric_dictionary"

    canonical_name: Mapped[str] = mapped_column(unique=True)
    category: Mapped[str]
    canonical_unit: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    description: Mapped[str | None]
    loinc_code: Mapped[str | None]


class Metric(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One confirmed reading of one biomarker (long format: one row per value)."""

    __tablename__ = "metrics"
    __table_args__ = (
        # The report must belong to the same patient as the metric.
        ForeignKeyConstraint(
            ["report_id", "patient_id"],
            ["reports.id", "reports.patient_id"],
            ondelete="CASCADE",
        ),
        check_in("flag", get_args(MetricFlag), name="flag_valid"),
        CheckConstraint("value_numeric IS NOT NULL OR value_text IS NOT NULL", name="has_value"),
        CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR reference_low <= reference_high",
            name="reference_range_ordered",
        ),
        Index(
            "ix_metrics_patient_id_canonical_metric_id_collected_at",
            "patient_id",
            "canonical_metric_id",
            "collected_at",
        ),
        Index("ix_metrics_report_id", "report_id"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID]
    # Null when the printed name is not in the dictionary yet; surfaced in review.
    canonical_metric_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("metric_dictionary.id", ondelete="RESTRICT")
    )
    raw_name: Mapped[str]
    # As printed on the report.
    value_numeric: Mapped[Decimal | None]
    value_text: Mapped[str | None]
    unit: Mapped[str | None]
    # Converted to the dictionary's canonical unit, when a conversion is known.
    value_canonical: Mapped[Decimal | None]
    unit_canonical: Mapped[str | None]
    reference_low: Mapped[Decimal | None]
    reference_high: Mapped[Decimal | None]
    reference_text: Mapped[str | None]
    flag: Mapped[str] = mapped_column(default="unknown", server_default="unknown")
    sample_type: Mapped[str | None]
    method: Mapped[str | None]
    collected_at: Mapped[datetime]
