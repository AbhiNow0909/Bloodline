"""Deterministic trend statistics for one test (CLAUDE.md Section 4.4).

Computed in Python from the values in the test's canonical unit, so results from labs that
print different units are comparable. The model only phrases these numbers; it never
computes them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.schemas.history import HistoryPoint

# A change smaller than this (in either direction, first to latest) counts as stable.
STABLE_PERCENT = 5.0
DAYS_PER_YEAR = 365.25

Direction = Literal["rising", "falling", "stable", "not enough results"]
Crossing = Literal[
    "moved above the range",
    "moved below the range",
    "moved back into the range",
    "stayed in the range",
    "stayed outside the range",
    "not compared",
]


@dataclass(frozen=True)
class TrendPoint:
    collected_at: datetime
    value: Decimal
    flag: str


@dataclass(frozen=True)
class TrendSummary:
    unit: str | None
    count: int  # results with a value in the test's unit
    skipped: int  # results without one (e.g. "Negative", or a unit that could not be converted)
    first: TrendPoint | None
    previous: TrendPoint | None
    latest: TrendPoint | None
    change_since_first: Decimal | None
    percent_since_first: float | None
    change_since_previous: Decimal | None
    percent_since_previous: float | None
    slope_per_year: float | None
    direction: Direction
    crossing: Crossing


def _percent(old: Decimal, new: Decimal) -> float | None:
    return None if old == 0 else round(float((new - old) / abs(old)) * 100, 1)


def _slope_per_year(points: Sequence[TrendPoint]) -> float | None:
    """Least-squares slope of value over time, in units per year."""
    if len(points) < 2:
        return None
    start = points[0].collected_at
    xs = [(p.collected_at - start).total_seconds() / 86_400 / DAYS_PER_YEAR for p in points]
    ys = [float(p.value) for p in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:  # all on the same day
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread


def _crossing(previous: TrendPoint | None, latest: TrendPoint | None) -> Crossing:
    known = {"low", "normal", "high"}
    if previous is None or latest is None or not {previous.flag, latest.flag} <= known:
        return "not compared"
    if previous.flag == latest.flag:
        return "stayed in the range" if latest.flag == "normal" else "stayed outside the range"
    if latest.flag == "high":
        return "moved above the range"
    if latest.flag == "low":
        return "moved below the range"
    return "moved back into the range"


def summarize(points: Sequence[HistoryPoint]) -> TrendSummary:
    """Trend of one test for one member. `points` are in time order (oldest first)."""
    numeric = [
        TrendPoint(p.collected_at, p.value_canonical, p.flag)
        for p in points
        if p.value_canonical is not None
    ]
    unit = next((p.unit_canonical for p in points if p.value_canonical is not None), None)
    first = numeric[0] if numeric else None
    latest = numeric[-1] if numeric else None
    previous = numeric[-2] if len(numeric) >= 2 else None

    change_first = percent_first = change_previous = percent_previous = None
    direction: Direction = "not enough results"
    if first is not None and latest is not None and previous is not None:
        change_first = latest.value - first.value
        percent_first = _percent(first.value, latest.value)
        change_previous = latest.value - previous.value
        percent_previous = _percent(previous.value, latest.value)
        if percent_first is None:
            direction = (
                "stable" if change_first == 0 else ("rising" if change_first > 0 else "falling")
            )
        elif abs(percent_first) < STABLE_PERCENT:
            direction = "stable"
        else:
            direction = "rising" if percent_first > 0 else "falling"

    return TrendSummary(
        unit=unit,
        count=len(numeric),
        skipped=len(points) - len(numeric),
        first=first,
        previous=previous,
        latest=latest,
        change_since_first=change_first,
        percent_since_first=percent_first,
        change_since_previous=change_previous,
        percent_since_previous=percent_previous,
        slope_per_year=_slope_per_year(numeric),
        direction=direction,
        crossing=_crossing(previous, latest),
    )
