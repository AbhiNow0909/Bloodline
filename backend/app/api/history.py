"""History over confirmed data: reports, metric catalog, time series, out-of-range values and
the family overview. Every route resolves its scope through an ownership check."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, OwnedFamily, OwnedPatient, OwnedReport
from app.models import CanonicalMetric
from app.schemas.history import (
    CatalogEntry,
    FamilyOverview,
    FlaggedReading,
    MetricHistory,
    Reading,
    ReportSummary,
)
from app.services import history

router = APIRouter(tags=["history"])

DateParam = Annotated[date | None, Query(description="Calendar day, Indian time")]


@router.get("/patients/{patient_id}/reports")
def list_reports(patient: OwnedPatient, db: DbSession) -> list[ReportSummary]:
    """The member's reports, newest first (any status)."""
    return history.list_reports(db, patient.id)


@router.get("/reports/{report_id}/metrics")
def report_metrics(report: OwnedReport, db: DbSession) -> list[Reading]:
    """The values saved from one report (empty until it is confirmed)."""
    return history.report_readings(db, report.id)


@router.get("/patients/{patient_id}/metrics")
def metric_catalog(patient: OwnedPatient, db: DbSession) -> list[CatalogEntry]:
    """Every test the member has results for, with its latest value."""
    return history.metric_catalog(db, patient.id)


@router.get(
    "/patients/{patient_id}/metrics/{metric_id}",
    responses={status.HTTP_404_NOT_FOUND: {}, status.HTTP_422_UNPROCESSABLE_CONTENT: {}},
)
def metric_history(
    metric_id: uuid.UUID,
    patient: OwnedPatient,
    db: DbSession,
    start: DateParam = None,
    end: DateParam = None,
) -> MetricHistory:
    """One test's readings over time, oldest first, for a trend chart."""
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="start must not be after end"
        )
    metric = db.get(CanonicalMetric, metric_id)
    if metric is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Metric not found")
    return history.metric_history(db, patient.id, metric, start=start, end=end)


@router.get("/patients/{patient_id}/out-of-range")
def out_of_range(
    patient: OwnedPatient,
    db: DbSession,
    since: DateParam = None,
    latest_only: Annotated[
        bool, Query(description="Only tests whose latest value is flagged (default)")
    ] = True,
) -> list[FlaggedReading]:
    """Values flagged low or high."""
    return history.out_of_range(db, [patient.id], since=since, latest_only=latest_only)


@router.get("/families/{family_id}/overview")
def family_overview(family: OwnedFamily, db: DbSession) -> FamilyOverview:
    """Every member's tests whose latest value is out of range, side by side."""
    return history.family_overview(db, family)
