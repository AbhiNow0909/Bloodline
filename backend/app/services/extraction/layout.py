"""Which pages hold results, and where a results page's header, results and footer are.

Modelled on Thyrocare reports: a results page starts with an identity header (lab address,
patient, referring doctor, address, dates, sample type and barcode), then a table headed
"TEST NAME TECHNOLOGY VALUE UNITS", then a footer ("Report Remarks", signing doctors, QR).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

_RESULTS_TABLE = re.compile(r"^TEST NAME\b.*\bVALUE\b.*\bUNITS\b")
_CONDITIONS = re.compile(r"\bCONDITIONS OF REPORTING\b", re.IGNORECASE)
_FOOTER = re.compile(r"^(Report Remarks\b|Page \d+ of \d+\b)")


class PageKind(StrEnum):
    RESULTS = "results"
    CONDITIONS = "conditions"  # "Conditions of Reporting" boilerplate
    OTHER = "other"  # cover, status summary, marketing


def classify_page(text: str) -> PageKind:
    if any(_RESULTS_TABLE.match(line) for line in text.splitlines()):
        return PageKind.RESULTS
    if _CONDITIONS.search(text):
        return PageKind.CONDITIONS
    return PageKind.OTHER


@dataclass(frozen=True)
class ResultsPageParts:
    header: str  # identity and sample header; parsed locally, never sent anywhere
    results: str  # from the table heading up to the footer


def split_results_page(text: str) -> ResultsPageParts:
    """Split a results page. The footer (remarks, signing doctors, QR text) is dropped."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if _RESULTS_TABLE.match(line))
    end = next(
        (i for i in range(start + 1, len(lines)) if _FOOTER.match(lines[i])),
        len(lines),
    )
    return ResultsPageParts(header="\n".join(lines[:start]), results="\n".join(lines[start:end]))
