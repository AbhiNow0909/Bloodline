"""Seed reference data.

Usage (from backend/, or inside the api container):

    python -m app.cli.seed
"""

import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import CanonicalMetric

METRIC_DICTIONARY_FILE = Path(__file__).with_name("metric_dictionary.toml")

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MetricSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_name: NonEmptyStr
    category: NonEmptyStr
    canonical_unit: NonEmptyStr
    aliases: list[NonEmptyStr] = Field(default_factory=list)
    description: NonEmptyStr
    loinc_code: NonEmptyStr | None = None


def name_key(name: str) -> str:
    """Case- and whitespace-insensitive form used to detect clashing names."""
    return " ".join(name.casefold().split())


class MetricSeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: list[MetricSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def names_are_unique(self) -> Self:
        # Every canonical name and alias must identify exactly one metric.
        owners: dict[str, str] = {}
        for seed in self.metric:
            for name in (seed.canonical_name, *seed.aliases):
                key = name_key(name)
                if key in owners:
                    raise ValueError(
                        f"name {name!r} of {seed.canonical_name!r} "
                        f"is already used by {owners[key]!r}"
                    )
                owners[key] = seed.canonical_name
        return self


def load_metric_seeds(path: Path = METRIC_DICTIONARY_FILE) -> list[MetricSeed]:
    with path.open("rb") as file:
        return MetricSeedFile.model_validate(tomllib.load(file)).metric


def seed_metric_dictionary(session: Session, seeds: Sequence[MetricSeed]) -> int:
    """Insert new metrics and update existing ones (matched by canonical_name).

    The seed file is the source of truth for every column except `id`, which stays stable
    so existing `metrics` rows keep pointing at the same entry.
    """
    if not seeds:
        return 0
    statement = insert(CanonicalMetric)
    statement = statement.on_conflict_do_update(
        index_elements=[CanonicalMetric.canonical_name],
        set_={
            "category": statement.excluded.category,
            "canonical_unit": statement.excluded.canonical_unit,
            "aliases": statement.excluded.aliases,
            "description": statement.excluded.description,
            "loinc_code": statement.excluded.loinc_code,
        },
    )
    session.execute(statement, [seed.model_dump() for seed in seeds])
    return len(seeds)


def main() -> None:
    seeds = load_metric_seeds()
    with Session(get_engine()) as session, session.begin():
        count = seed_metric_dictionary(session, seeds)
    print(f"metric_dictionary: upserted {count} metrics")


if __name__ == "__main__":
    main()
