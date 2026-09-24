"""PDF bytes → scrubbed, LLM-safe report text plus locally parsed header fields."""

from app.models import Sex
from app.services.extraction.header import ParsedHeader, parse_header
from app.services.extraction.layout import PageKind, classify_page, split_results_page
from app.services.extraction.pdf_text import read_page_texts
from app.services.extraction.pii import find_leaks, scrub_text
from app.services.extraction.schemas import (
    ExtractedReport,
    PiiLeakError,
    PrintedIdentity,
    ResultsPage,
    UnsupportedLayoutError,
)


def _unique(values: list[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _single[T](values: list[T | None], what: str, warnings: list[str]) -> T | None:
    """The one value all pages agree on; a warning (and None) if pages disagree."""
    distinct = list(dict.fromkeys(v for v in values if v is not None))
    if len(distinct) > 1:
        warnings.append(f"Results pages show different {what}")
        return None
    return distinct[0] if distinct else None


def extract_report(pdf_bytes: bytes) -> ExtractedReport:
    """Raises `ExtractionError` subclasses with user-safe messages."""
    texts = read_page_texts(pdf_bytes)
    kinds = [classify_page(text) for text in texts]
    results = [i for i, kind in enumerate(kinds) if kind is PageKind.RESULTS]
    if not results:
        raise UnsupportedLayoutError(
            "No results pages found. Only Thyrocare-style reports are supported so far."
        )

    parts = {i: split_results_page(texts[i]) for i in results}
    headers: dict[int, ParsedHeader] = {i: parse_header(parts[i].header) for i in results}
    identity = PrintedIdentity(
        names=_unique([h.name for h in headers.values()]),
        referred_by=_unique([h.referred_by for h in headers.values()]),
        barcodes=_unique([h.barcode for h in headers.values()]),
    )

    warnings = [w for h in headers.values() for w in h.warnings]
    if len(identity.names) > 1:
        warnings.append("Results pages show different patient names")
    age = _single([h.age_years for h in headers.values()], "patient ages", warnings)
    sex: Sex | None = _single([h.sex for h in headers.values()], "patient sexes", warnings)

    pages = []
    for i in results:
        text = scrub_text(parts[i].results, identity)
        if leaks := find_leaks(text, identity):
            raise PiiLeakError(f"Identity data remained after scrubbing ({', '.join(leaks)})")
        header = headers[i]
        pages.append(
            ResultsPage(
                page_number=i + 1,
                sample_type=header.sample_type,
                collected_at=header.collected_at,
                received_at=header.received_at,
                released_at=header.released_at,
                text=text,
            )
        )

    collection_times = [p.collected_at for p in pages if p.collected_at is not None]
    return ExtractedReport(
        lab_name="Thyrocare" if any("thyrocare" in t.lower() for t in texts) else None,
        collected_at=min(collection_times, default=None),
        printed_age_years=age,
        printed_sex=sex,
        pages=tuple(pages),
        dropped_pages=tuple(i + 1 for i, kind in enumerate(kinds) if kind is not PageKind.RESULTS),
        warnings=tuple(dict.fromkeys(warnings)),
        identity=identity,
    )
