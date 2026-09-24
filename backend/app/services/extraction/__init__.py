"""Lab-report PDF → scrubbed text + locally parsed header (CLAUDE.md Section 4.1, steps 2-4)."""

from app.services.extraction.pipeline import extract_report
from app.services.extraction.schemas import (
    ExtractedReport,
    ExtractionError,
    NoTextLayerError,
    PiiLeakError,
    PrintedIdentity,
    ResultsPage,
    UnreadablePdfError,
    UnsupportedLayoutError,
)

__all__ = [
    "ExtractedReport",
    "ExtractionError",
    "NoTextLayerError",
    "PiiLeakError",
    "PrintedIdentity",
    "ResultsPage",
    "UnreadablePdfError",
    "UnsupportedLayoutError",
    "extract_report",
]
