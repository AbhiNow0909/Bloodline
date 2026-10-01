"""Deterministic trend statistics (computed in Python, never by the model)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import MetricFlag
from app.schemas.history import HistoryPoint
from app.services.agent.trends import summarize


def point(
    day: str, value: str | None, flag: MetricFlag = "normal", unit: str = "ng/mL"
) -> HistoryPoint:
    return HistoryPoint(
        patient_id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        collected_at=datetime.fromisoformat(f"{day}T03:00:00").replace(tzinfo=UTC),
        canonical_metric_id=uuid.uuid4(),
        raw_name="FERRITIN",
        value_text=value or "Negative",
        value_numeric=Decimal(value) if value else None,
        unit=unit,
        value_canonical=Decimal(value) if value else None,
        unit_canonical=unit if value else None,
        reference_low=Decimal("13"),
        reference_high=Decimal("150"),
        reference_text=None,
        flag=flag,
        reference_low_canonical=Decimal("13"),
        reference_high_canonical=Decimal("150"),
    )


def test_a_falling_value_that_left_the_range() -> None:
    trend = summarize(
        [
            point("2023-03-03", "92.5"),
            point("2024-03-03", "48.0"),
            point("2025-03-03", "8.2", "low"),
        ]
    )
    assert trend.count == 3
    assert trend.unit == "ng/mL"
    assert trend.first is not None
    assert trend.first.value == Decimal("92.5")
    assert trend.latest is not None
    assert trend.latest.value == Decimal("8.2")
    assert trend.change_since_first == Decimal("-84.3")
    assert trend.percent_since_first == -91.1
    assert trend.change_since_previous == Decimal("-39.8")
    assert trend.percent_since_previous == -82.9
    assert trend.direction == "falling"
    assert trend.crossing == "moved below the range"
    # Least squares over ~2 years: about -42 ng/mL per year.
    assert trend.slope_per_year == pytest.approx(-42.2, abs=0.2)


@pytest.mark.parametrize(
    ("values", "direction"),
    [
        (["100", "104.9"], "stable"),  # under 5 %
        (["100", "95.1"], "stable"),
        (["100", "105"], "rising"),
        (["100", "94"], "falling"),
        (["0", "0"], "stable"),
        (["0", "3"], "rising"),  # no percent from zero, but the direction is clear
    ],
)
def test_direction_uses_a_five_percent_band(values: list[str], direction: str) -> None:
    trend = summarize([point("2024-01-01", values[0]), point("2025-01-01", values[1])])
    assert trend.direction == direction


@pytest.mark.parametrize(
    ("before", "after", "crossing"),
    [
        ("normal", "high", "moved above the range"),
        ("normal", "low", "moved below the range"),
        ("high", "normal", "moved back into the range"),
        ("normal", "normal", "stayed in the range"),
        ("low", "low", "stayed outside the range"),
        ("normal", "unknown", "not compared"),
    ],
)
def test_range_crossings(before: MetricFlag, after: MetricFlag, crossing: str) -> None:
    trend = summarize([point("2024-01-01", "50", before), point("2025-01-01", "60", after)])
    assert trend.crossing == crossing


def test_one_result_is_not_a_trend_and_text_results_are_skipped() -> None:
    trend = summarize([point("2024-01-01", None), point("2025-01-01", "60")])
    assert trend.count == 1
    assert trend.skipped == 1
    assert trend.direction == "not enough results"
    assert trend.change_since_first is None
    assert trend.slope_per_year is None
    assert trend.crossing == "not compared"


def test_results_on_one_day_have_no_slope() -> None:
    trend = summarize([point("2025-01-01", "50"), point("2025-01-01", "70")])
    assert trend.slope_per_year is None
    assert trend.direction == "rising"


def test_no_results() -> None:
    trend = summarize([])
    assert (trend.count, trend.first, trend.latest, trend.unit) == (0, None, None, None)
