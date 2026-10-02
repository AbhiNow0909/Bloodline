"""Range flags and trend alerts for one test's results (`series_insight`), computed in code."""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.models import CanonicalMetric, Metric
from app.schemas.history import Insight
from app.services.extraction.header import IST
from app.services.insights import series_insight

FERRITIN = CanonicalMetric(
    id=uuid.uuid4(),
    canonical_name="Ferritin",
    category="Iron Studies",
    canonical_unit="ng/mL",
    aliases=[],
    description="Reflects the body's iron stores.",
)
HAEMOGLOBIN = CanonicalMetric(
    id=uuid.uuid4(),
    canonical_name="Haemoglobin",
    category="Complete Blood Count",
    canonical_unit="g/dL",
    aliases=[],
    description=None,
)
PATIENT = uuid.uuid4()


def result(
    day: str,
    value: str,
    flag: str,
    *,
    metric: CanonicalMetric = FERRITIN,
    unit: str = "ng/mL",
    canonical: str | None = None,
    low: str | None = "13",
    high: str | None = "150",
) -> Metric:
    """One saved result on `day` (YYYY-MM-DD). `canonical` is the value in the standard unit
    (by default the printed value, when the printed unit is the standard one)."""
    numeric = Decimal(value) if value.replace(".", "", 1).isdigit() else None
    if canonical is None and unit == metric.canonical_unit:
        canonical = value if numeric is not None else None
    return Metric(
        id=uuid.uuid4(),
        patient_id=PATIENT,
        report_id=uuid.uuid4(),
        canonical_metric_id=metric.id,
        raw_name=metric.canonical_name.upper(),
        value_text=value,
        value_numeric=numeric,
        unit=unit,
        value_canonical=Decimal(canonical) if canonical else None,
        unit_canonical=metric.canonical_unit if canonical else None,
        reference_low=Decimal(low) if low else None,
        reference_high=Decimal(high) if high else None,
        reference_text=None,
        flag=flag,
        collected_at=datetime.fromisoformat(f"{day}T08:15:00").replace(tzinfo=IST),
    )


def insight(*results: Metric, percent: float = 25.0, last: int = 3) -> Insight | None:
    metric = (
        HAEMOGLOBIN if results and results[0].canonical_metric_id == HAEMOGLOBIN.id else FERRITIN
    )
    return series_insight(metric, results, alert_percent=percent, alert_results=last)


def test_nothing_to_say_without_results_or_with_one_result_in_range() -> None:
    assert insight() is None
    assert insight(result("2025-03-03", "48.3", "normal")) is None


def test_a_first_result_outside_the_range() -> None:
    found = insight(result("2025-03-03", "8.2", "low"))

    assert found is not None
    assert found.kind == "outside_range"
    assert found.compared_with is None
    assert (found.results_compared, found.outside_in_a_row) == (1, 1)
    assert found.change is None
    assert (found.reference_low, found.reference_high) == (Decimal("13"), Decimal("150"))
    assert found.metric.canonical_name == "Ferritin"
    assert found.patient_id == PATIENT


def test_newly_outside_the_range_compares_with_the_previous_result() -> None:
    previous = result("2025-03-03", "48.3", "normal")
    latest = result("2025-09-05", "3.10", "low")

    found = insight(result("2024-03-03", "60.1", "normal"), previous, latest)

    assert found is not None
    assert found.kind == "outside_range"
    assert found.compared_with is not None
    assert found.compared_with.report_id == previous.report_id
    assert found.compared_with.flag == "normal"
    assert found.latest.report_id == latest.report_id
    assert found.change == Decimal("-45.20")
    assert found.percent_change == -93.6
    assert (found.results_compared, found.outside_in_a_row) == (2, 1)


def test_counts_how_many_results_in_a_row_are_outside_on_the_same_side() -> None:
    found = insight(
        result("2023-01-01", "9.0", "low"),
        result("2023-06-01", "60.0", "normal"),
        result("2024-01-01", "10.0", "low"),
        result("2024-06-01", "8.0", "low"),
        result("2025-01-01", "7.0", "low"),
    )
    assert found is not None
    assert found.outside_in_a_row == 3

    swung = insight(result("2024-01-01", "170", "high"), result("2025-01-01", "9.0", "low"))
    assert swung is not None
    assert swung.outside_in_a_row == 1
    assert swung.compared_with is not None
    assert swung.compared_with.flag == "high"


def test_back_within_the_range() -> None:
    found = insight(result("2024-03-03", "8.2", "low"), result("2025-03-03", "20.5", "normal"))

    assert found is not None
    assert found.kind == "back_in_range"
    assert found.change == Decimal("12.3")
    assert found.percent_change == 150.0
    assert found.results_compared == 2


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["40.0", "49.9"], None),  # +24.75 %, rounds to 24.8: below the threshold
        (["40.0", "50.0"], 25.0),  # exactly the threshold counts
        (["40.0", "30.0"], -25.0),  # falling counts the same
        (["20.0", "40.0", "45.0", "50.0"], 25.0),  # only the last 3 results: 40 -> 50
        (["40.0", "60.0", "44.0"], None),  # first of the window to the latest: +10 %
    ],
)
def test_a_big_change_while_still_in_the_range(values: list[str], expected: float | None) -> None:
    results = [result(f"20{20 + i}-01-01", value, "normal") for i, value in enumerate(values)]

    found = insight(*results)

    if expected is None:
        assert found is None
    else:
        assert found is not None
        assert found.kind == "big_change"
        assert found.percent_change == expected
        window = min(len(values), 3)
        assert found.results_compared == window
        assert found.compared_with is not None
        assert found.compared_with.report_id == results[-window].report_id


def test_the_alert_settings_are_used() -> None:
    results = (result("2024-01-01", "40.0", "normal"), result("2025-01-01", "45.0", "normal"))
    assert insight(*results) is None
    found = insight(*results, percent=10.0)
    assert found is not None
    assert found.percent_change == 12.5

    longer = [result(f"20{20 + i}-01-01", v, "normal") for i, v in enumerate(["20", "40", "50"])]
    assert insight(*longer, last=2, percent=30.0) is None  # 40 -> 50: +25 %
    three = insight(*longer, last=3, percent=30.0)  # 20 -> 50: +150 %
    assert three is not None
    assert three.percent_change == 150.0


def test_results_in_other_units_are_compared_in_the_standard_unit() -> None:
    earlier = result(
        "2024-01-01",
        "120",
        "normal",
        metric=HAEMOGLOBIN,
        unit="g/L",
        canonical="12.0",
        low="115",
        high="160",
    )
    latest = result(
        "2025-01-01",
        "165",
        "high",
        metric=HAEMOGLOBIN,
        unit="g/L",
        canonical="16.5",
        low="120",
        high="150",
    )

    found = insight(earlier, latest)

    assert found is not None
    assert found.kind == "outside_range"
    assert found.change == Decimal("4.5")
    assert found.percent_change == 37.5
    # The range is given in the standard unit too.
    assert (found.reference_low, found.reference_high) == (Decimal("12.0"), Decimal("15.0"))
    assert (found.latest.value_text, found.latest.unit) == ("165", "g/L")  # as printed


def test_no_alert_without_a_range_or_a_comparable_value() -> None:
    # No range printed: nothing is known about it being in or out of range.
    assert (
        insight(result("2024-01-01", "40", "unknown"), result("2025-01-01", "90", "unknown"))
        is None
    )
    # The latest value could not be put in the standard unit: no change can be computed.
    assert (
        insight(
            result("2024-01-01", "40.0", "normal"),
            result("2025-01-01", "90.0", "normal", unit="ug/L", canonical=None),
        )
        is None
    )
    # A change from zero has no percentage.
    assert insight(result("2024-01-01", "0", "normal"), result("2025-01-01", "5", "normal")) is None


def test_outside_the_range_without_a_comparable_value_still_shows() -> None:
    found = insight(
        result("2024-01-01", "40.0", "normal"),
        result("2025-01-01", "9.0", "low", unit="ug/L", canonical=None),
    )
    assert found is not None
    assert found.kind == "outside_range"
    assert found.change is None
    assert found.percent_change is None
