"""Test helpers for embeddings: a deterministic fake model and confirmed reports with text."""

import hashlib
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Patient, Report
from app.models.report_chunk import EMBEDDING_DIMENSIONS
from app.services.extraction import ExtractedReport, ResultsPage, extract_report
from app.services.ingestion import StoredProcessing
from app.services.structuring import StructuredReport
from tests.factories import add, build_report

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "synthetic_thyrocare_report.pdf"


def _vector(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIMENSIONS] += 1.0
    if not any(vector):
        vector[0] = 1.0  # pgvector's cosine distance is undefined for a zero vector
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


class FakeEmbedder:
    """A normalized bag of words hashed into 384 dimensions: texts that share words are close.
    Different words can share a dimension ("ferritin" and "mg" do), so tests that depend on
    ranking use texts checked to be unambiguous. Records what it was asked to embed."""

    def __init__(self) -> None:
        self.passages: list[str] = []
        self.queries: list[str] = []

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        self.passages.extend(texts)
        return [_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return _vector(text)


class BrokenEmbedder:
    """An embedding model that fails, as when its files are missing."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("model files missing")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("model files missing")


@cache
def synthetic_extraction() -> ExtractedReport:
    return extract_report(FIXTURE_PDF.read_bytes())


def extraction_with_pages(*texts: str, sample_type: str = "SERUM") -> ExtractedReport:
    """An extraction whose results pages hold exactly these (already scrubbed) texts."""
    return ExtractedReport(
        lab_name="Example Labs",
        collected_at=None,
        printed_age_years=None,
        printed_sex=None,
        pages=tuple(
            ResultsPage(
                page_number=number,
                sample_type=sample_type,
                collected_at=None,
                received_at=None,
                released_at=None,
                text=text,
            )
            for number, text in enumerate(texts, start=1)
        ),
        dropped_pages=(),
    )


def add_confirmed_report(
    session: Session,
    patient: Patient,
    extraction: ExtractedReport | None = None,
    **overrides: Any,
) -> Report:
    """A confirmed report whose stored processing holds this extraction's scrubbed text."""
    stored = StoredProcessing(
        extraction=extraction or synthetic_extraction(),
        structured=StructuredReport(model="test", metrics=()),
        warnings=[],
    )
    fields: dict[str, Any] = {
        "status": "confirmed",
        "lab_name": "Example Labs",
        "collected_at": datetime(2025, 3, 3, 2, 45, tzinfo=UTC),
        "raw_extraction": stored.model_dump(mode="json"),
    }
    return add(session, build_report(patient, **(fields | overrides)))
