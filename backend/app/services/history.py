"""Read-side queries over confirmed history.

Every function takes the exact patient ids it may read. Callers resolve those through the
ownership checks (`get_owned_patient`, or the members of a `get_owned_family`), so nothing
here can widen the scope. The agent's tools (Phase 13) rely on the same contract.
"""

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Text, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.models import CanonicalMetric, Family, Metric, Patient, Report
from app.schemas.history import (
    CatalogEntry,
    FamilyOverview,
    FlaggedReading,
    HistoryPoint,
    MemberOverview,
    MetricHistory,
    MetricInfo,
    Reading,
    ReportSummary,
)
from app.schemas.patient import PatientRead
from app.schemas.report import ReportRead
from app.services.extraction.header import IST
from app.services.normalization import convert

# Report dates are calendar days in the labs' (Indian) local time.
REPORT_TIMEZONE = IST
FLAGGED = ("low", "high")

# One series per test: its dictionary entry when mapped, otherwise its printed name.
_SERIES = case(
    (Metric.canonical_metric_id.is_not(None), cast(Metric.canonical_metric_id, Text)),
    else_=literal("raw:") + Metric.raw_name,
).label("series")


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, REPORT_TIMEZONE)


def _latest_per_series(session: Session, patient_ids: Collection[uuid.UUID]) -> list[Metric]:
    """Each patient's most recent reading of each test (Postgres DISTINCT ON)."""
    if not patient_ids:
        return []
    statement = (
        select(Metric)
        .where(Metric.patient_id.in_(patient_ids))
        .distinct(Metric.patient_id, _SERIES)
        .order_by(Metric.patient_id, _SERIES, Metric.collected_at.desc(), Metric.created_at.desc())
    )
    return list(session.scalars(statement))


def _definitions(session: Session, metrics: Iterable[Metric]) -> dict[uuid.UUID, CanonicalMetric]:
    ids = {m.canonical_metric_id for m in metrics if m.canonical_metric_id is not None}
    if not ids:
        return {}
    rows = session.scalars(select(CanonicalMetric).where(CanonicalMetric.id.in_(ids)))
    return {definition.id: definition for definition in rows}


def _flagged(metric: Metric, definitions: dict[uuid.UUID, CanonicalMetric]) -> FlaggedReading:
    definition = definitions.get(metric.canonical_metric_id) if metric.canonical_metric_id else None
    return FlaggedReading(
        **Reading.model_validate(metric).model_dump(),
        name=definition.canonical_name if definition else metric.raw_name,
        category=definition.category if definition else None,
    )


def _by_category_and_name(item: FlaggedReading | CatalogEntry) -> tuple[bool, str, str]:
    category = (
        item.category
        if isinstance(item, FlaggedReading)
        else (item.metric.category if item.metric else None)
    )
    return (category is None, category or "", item.name.casefold())


# --- reports ---------------------------------------------------------------------------------


def list_reports(session: Session, patient_id: uuid.UUID) -> list[ReportSummary]:
    """Every report of the member, newest first, with how many values are flagged."""
    counts = (
        select(
            Metric.report_id,
            func.count().label("metric_count"),
            func.count().filter(Metric.flag.in_(FLAGGED)).label("flagged_count"),
        )
        .where(Metric.patient_id == patient_id)
        .group_by(Metric.report_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Report,
            func.coalesce(counts.c.metric_count, 0),
            func.coalesce(counts.c.flagged_count, 0),
        )
        .outerjoin(counts, counts.c.report_id == Report.id)
        .where(Report.patient_id == patient_id)
        .order_by(
            func.coalesce(Report.collected_at, Report.created_at).desc(),
            Report.created_at.desc(),
        )
    ).tuples()
    return [
        ReportSummary(
            **ReportRead.model_validate(report).model_dump(),
            metric_count=metric_count,
            flagged_count=flagged_count,
        )
        for report, metric_count, flagged_count in rows
    ]


def report_readings(session: Session, report_id: uuid.UUID) -> list[Reading]:
    """The confirmed values of one report (empty until it is confirmed)."""
    metrics = session.scalars(
        select(Metric).where(Metric.report_id == report_id).order_by(Metric.raw_name)
    )
    return [Reading.model_validate(metric) for metric in metrics]


# --- metrics -------------------------------------------------------------------------------


def metric_catalog(session: Session, patient_id: uuid.UUID) -> list[CatalogEntry]:
    """Every test the member has results for, with its latest reading."""
    latest = _latest_per_series(session, [patient_id])
    stats = {
        series: (count, first)
        for series, count, first in session.execute(
            select(_SERIES, func.count(), func.min(Metric.collected_at))
            .where(Metric.patient_id == patient_id)
            .group_by(_SERIES)
        ).tuples()
    }
    definitions = _definitions(session, latest)
    entries = []
    for metric in latest:
        definition = (
            definitions.get(metric.canonical_metric_id) if metric.canonical_metric_id else None
        )
        # Same key as `_SERIES` in SQL.
        series = (
            str(metric.canonical_metric_id)
            if metric.canonical_metric_id is not None
            else f"raw:{metric.raw_name}"
        )
        count, first = stats[series]
        entries.append(
            CatalogEntry(
                metric=MetricInfo.model_validate(definition) if definition else None,
                name=definition.canonical_name if definition else metric.raw_name,
                reading_count=count,
                first_collected_at=first,
                latest=Reading.model_validate(metric),
            )
        )
    return sorted(entries, key=_by_category_and_name)


def _to_canonical(bound: Decimal | None, unit: str | None, canonical_unit: str) -> Decimal | None:
    return None if bound is None else convert(bound, unit, canonical_unit)


def metric_history(
    session: Session,
    patient_id: uuid.UUID,
    metric: CanonicalMetric,
    *,
    start: date | None = None,
    end: date | None = None,
) -> MetricHistory:
    """One test's readings, oldest first, with ranges also in the canonical unit."""
    statement = select(Metric).where(
        Metric.patient_id == patient_id, Metric.canonical_metric_id == metric.id
    )
    if start is not None:
        statement = statement.where(Metric.collected_at >= day_start(start))
    if end is not None:
        statement = statement.where(Metric.collected_at < day_start(end + timedelta(days=1)))
    points = [
        HistoryPoint(
            **Reading.model_validate(row).model_dump(),
            reference_low_canonical=_to_canonical(
                row.reference_low, row.unit, metric.canonical_unit
            ),
            reference_high_canonical=_to_canonical(
                row.reference_high, row.unit, metric.canonical_unit
            ),
        )
        for row in session.scalars(statement.order_by(Metric.collected_at, Metric.created_at))
    ]
    return MetricHistory(metric=MetricInfo.model_validate(metric), points=points)


def out_of_range(
    session: Session,
    patient_ids: Collection[uuid.UUID],
    *,
    since: date | None = None,
    latest_only: bool = True,
) -> list[FlaggedReading]:
    """Readings flagged low or high. By default only tests whose latest value is flagged
    (what is out of range now); with `latest_only=False`, every flagged reading."""
    if latest_only:
        metrics = [m for m in _latest_per_series(session, patient_ids) if m.flag in FLAGGED]
    elif patient_ids:
        metrics = list(
            session.scalars(
                select(Metric)
                .where(Metric.patient_id.in_(patient_ids), Metric.flag.in_(FLAGGED))
                .order_by(Metric.collected_at.desc())
            )
        )
    else:
        metrics = []
    if since is not None:
        metrics = [m for m in metrics if m.collected_at >= day_start(since)]
    definitions = _definitions(session, metrics)
    readings = [_flagged(metric, definitions) for metric in metrics]
    return sorted(readings, key=lambda r: (*_by_category_and_name(r), -r.collected_at.timestamp()))


# --- family ----------------------------------------------------------------------------------


def family_overview(session: Session, family: Family) -> FamilyOverview:
    """Each member's tests whose latest value is out of range, side by side."""
    members = list(
        session.scalars(
            select(Patient)
            .where(Patient.family_id == family.id)
            .order_by(Patient.display_name, Patient.created_at)
        )
    )
    ids = [member.id for member in members]
    latest = _latest_per_series(session, ids)
    definitions = _definitions(session, latest)
    tracked: dict[uuid.UUID, int] = defaultdict(int)
    flagged: dict[uuid.UUID, list[FlaggedReading]] = defaultdict(list)
    for metric in latest:
        tracked[metric.patient_id] += 1
        if metric.flag in FLAGGED:
            flagged[metric.patient_id].append(_flagged(metric, definitions))
    last_report: dict[uuid.UUID, datetime | None] = {}
    if ids:
        rows = session.execute(
            select(Report.patient_id, func.max(Report.collected_at))
            .where(Report.patient_id.in_(ids), Report.status == "confirmed")
            .group_by(Report.patient_id)
        ).tuples()
        # .all(): a Result has .keys(), so dict(result) would treat it as a mapping.
        last_report = dict(rows.all())
    return FamilyOverview(
        family_id=family.id,
        name=family.name,
        members=[
            MemberOverview(
                patient=PatientRead.model_validate(member),
                latest_report_at=last_report.get(member.id),
                tracked_metric_count=tracked[member.id],
                out_of_range=sorted(flagged[member.id], key=_by_category_and_name),
            )
            for member in members
        ],
    )
