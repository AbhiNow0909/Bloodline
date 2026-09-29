import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models import ReportStatus, Sex
from app.services.structuring import StructuredMetric


class ReportRead(BaseModel):
    """A report's status and summary; poll this after uploading."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    status: ReportStatus
    lab_name: str | None
    collected_at: datetime | None
    failure_reason: str | None
    created_at: datetime


class ReportReview(BaseModel):
    """Everything the review screen needs: extracted rows next to the original PDF."""

    report: ReportRead
    printed_age_years: int | None
    printed_sex: Sex | None
    sample_types: list[str]
    warnings: list[str]
    rows: list[StructuredMetric]


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Value = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
# Lab bounds never need more than 18 significant digits; this also rejects 1e400.
Bound = Annotated[Decimal, Field(max_digits=18, decimal_places=6)]


class ConfirmedMetric(BaseModel):
    """One reviewed row. Values are text as reviewed; the server derives every number."""

    model_config = ConfigDict(extra="forbid")

    raw_name: Name
    canonical_metric_id: uuid.UUID | None = None
    value_text: Value
    unit: Short | None = None
    reference_low: Bound | None = None
    reference_high: Bound | None = None
    reference_text: Long | None = None
    sample_type: Short | None = None
    method: Long | None = None

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        low, high = self.reference_low, self.reference_high
        if low is not None and high is not None and low > high:
            raise ValueError("reference_low must not be above reference_high")
        return self


class ConfirmReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: AwareDatetime | None = Field(
        default=None, description="Needed if the report's collection time could not be read"
    )
    metrics: list[ConfirmedMetric] = Field(min_length=1, max_length=500)


class DuplicateReport(BaseModel):
    detail: str
    report_id: uuid.UUID


class MetricDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str
    category: str
    canonical_unit: str
    aliases: list[str]
    description: str | None
