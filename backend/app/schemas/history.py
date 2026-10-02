"""Read models for confirmed history. Shared by the API and (from Phase 13) the agent's tools."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import MetricFlag
from app.schemas.patient import PatientRead
from app.schemas.report import ReportRead


class MetricInfo(BaseModel):
    """A dictionary entry: what the marker is and its canonical unit."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str
    category: str
    canonical_unit: str
    description: str | None


class Reading(BaseModel):
    """One confirmed value, as printed and in the canonical unit."""

    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    report_id: uuid.UUID
    collected_at: datetime
    canonical_metric_id: uuid.UUID | None
    raw_name: str
    value_text: str | None
    value_numeric: Decimal | None
    unit: str | None
    value_canonical: Decimal | None
    unit_canonical: str | None
    reference_low: Decimal | None  # in the printed unit
    reference_high: Decimal | None
    reference_text: str | None
    flag: MetricFlag


class HistoryPoint(Reading):
    """A reading on a chart: the range converted to the canonical unit for the shaded band."""

    reference_low_canonical: Decimal | None
    reference_high_canonical: Decimal | None


class MetricHistory(BaseModel):
    metric: MetricInfo
    points: list[HistoryPoint]  # oldest first


class CatalogEntry(BaseModel):
    """A test the member has results for. Unmapped tests (not in the dictionary) are listed
    under their printed name, with `metric` null."""

    metric: MetricInfo | None
    name: str
    reading_count: int
    first_collected_at: datetime
    latest: Reading


class FlaggedReading(Reading):
    """An out-of-range reading, labelled with the test's name."""

    name: str
    category: str | None


class ReportSummary(ReportRead):
    metric_count: int
    flagged_count: int  # readings flagged low or high


# What a member's results show, computed in code (CLAUDE.md Section 4.4), most important first:
# the latest result is outside the lab's range; it moved back into the range since the previous
# result; or, still within the range, it changed a lot across the last few results.
InsightKind = Literal["outside_range", "big_change", "back_in_range"]


class InsightResult(BaseModel):
    """One result an insight refers to."""

    model_config = ConfigDict(from_attributes=True)

    report_id: uuid.UUID
    collected_at: datetime
    value_text: str | None  # as printed
    unit: str | None  # as printed
    value_canonical: Decimal | None  # in the test's standard unit (`MetricInfo.canonical_unit`)
    flag: MetricFlag


class Insight(BaseModel):
    patient_id: uuid.UUID
    kind: InsightKind
    metric: MetricInfo
    latest: InsightResult
    # The previous result; for `big_change`, the first of the results compared.
    compared_with: InsightResult | None
    results_compared: int  # results from `compared_with` to `latest`, both included
    change: Decimal | None  # latest - compared_with, in the standard unit
    percent_change: float | None
    # For `outside_range`: how many of the latest results in a row are on the same side.
    outside_in_a_row: int
    # The latest result's range, in the standard unit.
    reference_low: Decimal | None
    reference_high: Decimal | None


class MemberOverview(BaseModel):
    patient: PatientRead
    latest_report_at: datetime | None  # most recent confirmed collection time
    tracked_metric_count: int
    out_of_range: list[FlaggedReading]  # tests whose latest value is flagged
    insights: list[Insight] = []


class FamilyOverview(BaseModel):
    family_id: uuid.UUID
    name: str
    members: list[MemberOverview]
