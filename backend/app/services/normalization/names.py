"""Map printed test names to the metric dictionary by exact, normalized name.

Never substring or fuzzy matching: short aliases such as "K", "Na" or "PCT" would otherwise
hit unrelated tests. An unmatched name stays unmapped and is surfaced in review.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalMetric


def name_key(name: str) -> str:
    key = name.casefold().replace("&", " and ")
    key = re.sub(r"[\u2010-\u2015\u2212]", "-", key)  # Unicode hyphens/dashes/minus → "-"
    key = re.sub(r"\s*([/,-])\s*", r"\1", key)  # "UA / C" == "UA/C", "A - B" == "A-B"
    return " ".join(key.split()).strip(" .:;")


@dataclass(frozen=True)
class DictionaryEntry:
    id: uuid.UUID
    canonical_name: str
    canonical_unit: str


def _candidates(raw_name: str, sample_type: str | None) -> list[str]:
    names = [raw_name]
    without_suffix = re.sub(r"\s*\([^()]*\)\s*$", "", raw_name)  # "… RATIO (UA/C)"
    if without_suffix != raw_name:
        names.append(without_suffix)
    if suffix := re.search(r"\(([^()]*)\)\s*$", raw_name):
        names.append(suffix[1])
    # On a urine sample, "CREATININE" means urine creatinine, not the serum test.
    if sample_type and sample_type.strip().upper() == "URINE" and "urin" not in raw_name.lower():
        names = [f"Urine {name}" for name in names] + names
    return names


class MetricIndex:
    def __init__(self, entries: Iterable[tuple[DictionaryEntry, Iterable[str]]]) -> None:
        self._by_key: dict[str, DictionaryEntry] = {}
        for entry, aliases in entries:
            for name in (entry.canonical_name, *aliases):
                self._by_key[name_key(name)] = entry

    @classmethod
    def from_rows(cls, rows: Iterable[CanonicalMetric]) -> "MetricIndex":
        return cls(
            (DictionaryEntry(row.id, row.canonical_name, row.canonical_unit), row.aliases)
            for row in rows
        )

    def match(self, raw_name: str, sample_type: str | None = None) -> DictionaryEntry | None:
        for candidate in _candidates(raw_name, sample_type):
            if entry := self._by_key.get(name_key(candidate)):
                return entry
        return None


def load_metric_index(session: Session) -> MetricIndex:
    return MetricIndex.from_rows(session.scalars(select(CanonicalMetric)))
