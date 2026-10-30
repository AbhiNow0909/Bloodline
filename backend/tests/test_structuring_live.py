"""Optional end-to-end check against the real Groq API, using the SYNTHETIC reports only.

Reports are normally read from their tables; these tests use versions that only the AI can
read, so the AI path is what they check. Skipped unless GROQ_API_KEY is set (it is not in
CI). Deselect locally with `-m "not live"`.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.config import get_settings
from app.services.extraction import ExtractedReport, extract_report
from app.services.llm import get_structuring_client
from app.services.structuring import structure_report
from app.services.structuring.service import VALUE_NOT_IN_SOURCE
from tests import synthetic_medibuddy as medibuddy
from tests import synthetic_pdf as thyrocare
from tests.structuring_data import seed_metric_index

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(get_settings().groq_api_key is None, reason="GROQ_API_KEY is not set"),
]


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, **kwargs: Any) -> str:
        self.calls += 1
        return get_structuring_client().complete_json(**kwargs)


def without_tables(report: ExtractedReport) -> ExtractedReport:
    pages = tuple(page.model_copy(update={"table": ()}) for page in report.pages)
    return report.model_copy(update={"pages": pages})


def test_synthetic_report_structures_end_to_end() -> None:
    client = CountingClient()
    result = structure_report(
        extract_report(thyrocare.synthetic_report(columns=False)),
        patient_sex="female",
        metric_index=seed_metric_index(),
        client=client,
        model=get_settings().structuring_model,
    )

    assert client.calls >= 3  # a page at a time

    by_name = {m.canonical_name: m for m in result.metrics}
    assert set(by_name) == {
        "Urine Creatinine",
        "Urine Microalbumin",
        "Urine Albumin/Creatinine Ratio",
        "Ferritin",
    }
    expected = {
        "Urine Creatinine": (Decimal("84.20"), "Female", "normal"),
        "Urine Microalbumin": (Decimal("12.6"), "Adults", "normal"),
        "Urine Albumin/Creatinine Ratio": (Decimal("15.0"), "Adults", "normal"),
        "Ferritin": (Decimal("48.3"), "Women", "normal"),
    }
    for name, (value, label, flag) in expected.items():
        row = by_name[name]
        assert (row.value_numeric, row.reference_label, row.flag) == (value, label, flag), name
        assert VALUE_NOT_IN_SOURCE not in row.warnings


def test_synthetic_medibuddy_report_structures_end_to_end() -> None:
    client = CountingClient()
    result = structure_report(
        without_tables(extract_report(medibuddy.FIXTURE_PATH.read_bytes())),
        patient_sex="male",
        metric_index=seed_metric_index(),
        client=client,
        model=get_settings().structuring_model,
    )

    assert client.calls >= 2

    by_name = {m.canonical_name: m for m in result.metrics if m.canonical_name}
    expected = {
        "Total Protein": (Decimal("7.2"), "normal"),
        "Direct Bilirubin": (Decimal("0.21"), "normal"),
        "AST": (Decimal("46"), "high"),
        "Vitamin B12": (Decimal("345"), "normal"),
        "Haemoglobin": (Decimal("13.9"), "normal"),
        "RBC Count": (Decimal("4.82"), "normal"),
        "Total Leucocyte Count": (Decimal("6500"), "normal"),
        "Absolute Neutrophil Count": (Decimal("3.90"), "normal"),
    }
    assert set(by_name) == set(expected)
    for name, (value, flag) in expected.items():
        row = by_name[name]
        assert (row.value_numeric, row.flag) == (value, flag), name
        assert row.unit_canonical is not None, name  # every unit converted
        assert row.warnings == (), name
    assert "999" not in {m.value_text for m in result.metrics}  # interpretation never sent
