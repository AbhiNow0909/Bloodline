import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.seed import (
    MetricSeed,
    MetricSeedFile,
    load_metric_seeds,
    name_key,
    seed_metric_dictionary,
)
from app.models import CanonicalMetric

REQUIRED_CATEGORIES = {
    "Complete Blood Count",
    "Lipid Profile",
    "Liver Function",
    "Kidney Function",
    "Thyroid",
    "Diabetes",
    "Iron Studies",
    "Vitamins",
    "Urine",
}


def _seed(name: str, *aliases: str) -> dict[str, Any]:
    return {
        "canonical_name": name,
        "category": "Test Panel",
        "canonical_unit": "mg/dL",
        "aliases": list(aliases),
        "description": "Synthetic marker used only in tests.",
    }


def test_seed_file_is_valid_and_covers_the_required_panels() -> None:
    seeds = load_metric_seeds()

    assert {seed.category for seed in seeds} >= REQUIRED_CATEGORIES
    names = {name_key(seed.canonical_name) for seed in seeds}
    for expected in ("haemoglobin", "hba1c", "ferritin", "tsh", "urine albumin/creatinine ratio"):
        assert expected in names


@pytest.mark.parametrize(
    "metrics",
    [
        pytest.param([_seed("Marker A", "MA"), _seed("Marker B", "ma")], id="alias-clash"),
        pytest.param([_seed("Marker A"), _seed("Marker B", " marker  a ")], id="alias-is-name"),
        pytest.param([_seed("Marker A"), _seed("MARKER A")], id="duplicate-name"),
        pytest.param([_seed("Marker A", "Marker A")], id="alias-repeats-own-name"),
    ],
)
def test_seed_file_rejects_names_used_twice(metrics: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError, match="already used by"):
        MetricSeedFile.model_validate({"metric": metrics})


@pytest.mark.parametrize(
    "metric",
    [
        pytest.param(_seed("Marker A") | {"unit": "mg/dL"}, id="unknown-key"),
        pytest.param(_seed("Marker A") | {"description": "   "}, id="blank-description"),
        pytest.param(_seed("Marker A", ""), id="blank-alias"),
    ],
)
def test_seed_file_rejects_malformed_entries(metric: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MetricSeedFile.model_validate({"metric": [metric]})


def _ids_by_name(session: Session) -> dict[str, uuid.UUID]:
    query = select(CanonicalMetric.canonical_name, CanonicalMetric.id)
    return dict(session.execute(query).tuples().all())


def test_seeding_twice_creates_no_duplicates_and_keeps_ids(db_session: Session) -> None:
    seeds = load_metric_seeds()

    seed_metric_dictionary(db_session, seeds)
    first = _ids_by_name(db_session)
    seed_metric_dictionary(db_session, seeds)
    second = _ids_by_name(db_session)

    assert len(first) == len(seeds)
    assert second == first


def test_seeding_updates_an_existing_definition(db_session: Session) -> None:
    original = MetricSeed.model_validate(_seed("Test Marker", "TM"))
    seed_metric_dictionary(db_session, [original])
    original_id = _ids_by_name(db_session)["Test Marker"]

    changed = original.model_copy(update={"aliases": ["TM", "T-Marker"], "canonical_unit": "g/L"})
    seed_metric_dictionary(db_session, [changed])
    db_session.expire_all()

    stored = db_session.scalars(
        select(CanonicalMetric).where(CanonicalMetric.canonical_name == "Test Marker")
    ).one()
    assert stored.id == original_id
    assert stored.aliases == ["TM", "T-Marker"]
    assert stored.canonical_unit == "g/L"
