"""Result-looking lines that no returned row accounts for (`possibly_missed`)."""

from decimal import Decimal

import pytest

from app.services.structuring.completeness import possibly_missed
from app.services.structuring.schemas import StructuredMetric


def row(name: str, value: str) -> StructuredMetric:
    return StructuredMetric(
        raw_name=name,
        panel=None,
        technology=None,
        method=None,
        sample_type=None,
        value_text=value,
        value_numeric=Decimal(value) if value[0].isdigit() else None,
        unit=None,
        canonical_metric_id=None,
        canonical_name=None,
        value_canonical=None,
        unit_canonical=None,
        reference_text=None,
        reference_low=None,
        reference_high=None,
        reference_label=None,
        flag="unknown",
        warnings=(),
    )


PAGE = """Sample type: SERUM
TEST DESCRIPTION RESULT UNITS BIOLOGICAL REFERENCE INTERVAL
PCT 0.25 % 0.1 - 0.5
Platelet large cell ratio (P-LCR) 33.5 % 13 - 43
CRP 4.5 mg/L < 5.0
(Method: Immunoturbidimetry)
Estimated Average Glucose (eAG) 117.0 mg/dL 90 - 120
Reaction (pH) 6.0 5.0 - 8.0"""


def test_lines_without_a_matching_row_are_named() -> None:
    rows = [row("PCT", "0.25"), row("C-Reactive Protein (CRP)", "4.5"), row("Reaction (pH)", "6.0")]

    assert possibly_missed(PAGE, rows) == [
        "Platelet large cell ratio (P-LCR)",
        "Estimated Average Glucose (eAG)",
    ]


def test_a_row_with_the_same_name_but_another_value_does_not_count() -> None:
    assert possibly_missed("PCT 0.25 % 0.1 - 0.5", [row("PCT", "0.52")]) == ["PCT"]


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("FERRITIN C.M.I.A 48.3 ng/mL", id="thyrocare-row-range-on-its-own-line"),
        pytest.param("Women: 4.63 - 204.00 ng/ml", id="range-line"),
        pytest.param(
            "Tietz NW,Clinical Guide to Laboratory Tests Saunders 2015 : 400-405", id="citation"
        ),
        pytest.param("reaches a peak after 24 hours and decreases after 8 to 14 days", id="prose"),
        pytest.param("Sample type: SERUM", id="header"),
    ],
)
def test_lines_that_are_not_result_rows_are_ignored(line: str) -> None:
    assert possibly_missed(line, []) == []
