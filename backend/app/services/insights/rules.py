"""Range flags and trend alerts for members' saved results (CLAUDE.md Section 4.4).

Each test's results are compared in its standard unit, so results from labs that print
different units compare. Thresholds come from settings. The model only words these findings
(see `explain`); it never finds or computes them.
"""

import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CanonicalMetric, Family, Metric
from app.schemas.history import FamilyOverview, Insight, InsightKind, InsightResult, MetricInfo
from app.services import history
from app.services.agent.trends import percent_change
from app.services.normalization import convert

FLAGGED = ("low", "high")


@dataclass(frozen=True)
class _Point:
    reading: Metric
    value: Decimal | None  # in the standard unit
    low: Decimal | None  # the reading's range, in the standard unit
    high: Decimal | None


def _point(reading: Metric, unit: str) -> _Point:
    def bound(value: Decimal | None) -> Decimal | None:
        return None if value is None else convert(value, reading.unit, unit)

    return _Point(
        reading,
        reading.value_canonical,
        bound(reading.reference_low),
        bound(reading.reference_high),
    )


def _result(point: _Point) -> InsightResult:
    return InsightResult.model_validate(point.reading)


def _insight(
    kind: InsightKind,
    metric: CanonicalMetric,
    latest: _Point,
    compared: _Point | None,
    *,
    results_compared: int,
    outside_in_a_row: int = 0,
) -> Insight:
    change = percent = None
    if compared is not None and compared.value is not None and latest.value is not None:
        change = latest.value - compared.value
        percent = percent_change(compared.value, latest.value)
    return Insight(
        patient_id=latest.reading.patient_id,
        kind=kind,
        metric=MetricInfo.model_validate(metric),
        latest=_result(latest),
        compared_with=_result(compared) if compared is not None else None,
        results_compared=results_compared,
        change=change,
        percent_change=percent,
        outside_in_a_row=outside_in_a_row,
        reference_low=latest.low,
        reference_high=latest.high,
    )


def series_insight(
    metric: CanonicalMetric,
    readings: Sequence[Metric],
    *,
    alert_percent: float,
    alert_results: int,
) -> Insight | None:
    """The most important finding for one test of one member (`readings` oldest first)."""
    if not readings:
        return None
    points = [_point(reading, metric.canonical_unit) for reading in readings]
    latest = points[-1]
    previous = points[-2] if len(points) > 1 else None
    flag = latest.reading.flag

    if flag in FLAGGED:
        in_a_row = 0
        for point in reversed(points):
            if point.reading.flag != flag:
                break
            in_a_row += 1
        return _insight(
            "outside_range",
            metric,
            latest,
            previous,
            results_compared=2 if previous else 1,
            outside_in_a_row=in_a_row,
        )

    if flag != "normal" or previous is None:
        return None  # no range to compare with, or nothing to compare
    if previous.reading.flag in FLAGGED:
        return _insight("back_in_range", metric, latest, previous, results_compared=2)

    # Still within the range: did it move a lot across the last few results?
    window = [(point, point.value) for point in points if point.value is not None]
    window = window[-alert_results:]
    if len(window) < 2 or window[-1][0] is not latest:
        return None
    (first, first_value), (_, latest_value) = window[0], window[-1]
    percent = percent_change(first_value, latest_value)
    if percent is None or abs(percent) < alert_percent:
        return None
    return _insight("big_change", metric, latest, first, results_compared=len(window))


def _importance(insight: Insight) -> tuple[int, str, str]:
    if insight.kind == "outside_range":
        # Newly outside (the previous result was not on this side) before still outside.
        newly = (
            insight.compared_with is not None and insight.compared_with.flag != insight.latest.flag
        )
        rank = 0 if newly else 1
    else:
        rank = 2 if insight.kind == "big_change" else 3
    return (rank, insight.metric.category, insight.metric.canonical_name.casefold())


def member_insights(
    session: Session, patient_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[Insight]]:
    """Each member's findings, most important first. Like `history`, this reads only the
    exact patient ids given (resolved by the caller through ownership checks). Tests not
    matched to the metric dictionary have no comparable series and are left out."""
    if not patient_ids:
        return {}
    settings = get_settings()
    readings = session.scalars(
        select(Metric)
        .where(Metric.patient_id.in_(patient_ids), Metric.canonical_metric_id.is_not(None))
        .order_by(
            Metric.patient_id, Metric.canonical_metric_id, Metric.collected_at, Metric.created_at
        )
    )
    series: dict[tuple[uuid.UUID, uuid.UUID], list[Metric]] = defaultdict(list)
    for reading in readings:
        if reading.canonical_metric_id is not None:  # always, given the query
            series[(reading.patient_id, reading.canonical_metric_id)].append(reading)
    metric_ids = {metric_id for _, metric_id in series}
    definitions = {
        definition.id: definition
        for definition in session.scalars(
            select(CanonicalMetric).where(CanonicalMetric.id.in_(metric_ids))
        )
    }

    found: dict[uuid.UUID, list[Insight]] = {patient_id: [] for patient_id in patient_ids}
    for (patient_id, metric_id), rows in series.items():
        insight = series_insight(
            definitions[metric_id],
            rows,
            alert_percent=settings.trend_alert_percent,
            alert_results=settings.trend_alert_results,
        )
        if insight is not None:
            found[patient_id].append(insight)
    return {patient_id: sorted(items, key=_importance) for patient_id, items in found.items()}


def family_overview(session: Session, family: Family) -> FamilyOverview:
    """`history.family_overview` with each member's findings."""
    overview = history.family_overview(session, family)
    found = member_insights(session, [member.patient.id for member in overview.members])
    for member in overview.members:
        member.insights = found[member.patient.id]
    return overview
