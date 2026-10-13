"""Which pages hold results, and where a results page's header, results and footer are.

Two report layouts are known. Each results page starts with an identity header (patient,
referring doctor, dates, sample type and id), then a results table, then a footer:

- Thyrocare: a table headed "TEST NAME TECHNOLOGY VALUE UNITS", footer from "Report Remarks"
  (signing doctors, QR text).
- MediBuddy (reports issued through MediBuddy by partner labs such as HealthMap Diagnostics):
  a table headed "TEST DESCRIPTION RESULT UNITS BIOLOGICAL REFERENCE INTERVAL", each test
  followed by a "(Method: …)" line; footer from "Interpretation:" (general text about the
  tests), "NOTE :" (which lab processed the sample) or "Page N of M".
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class Layout(StrEnum):
    THYROCARE = "thyrocare"
    MEDIBUDDY = "medibuddy"


_RESULTS_TABLE = {
    Layout.THYROCARE: re.compile(r"^TEST NAME\b.*\bVALUE\b.*\bUNITS\b"),
    Layout.MEDIBUDDY: re.compile(r"^TEST DESCRIPTION\b.*\bRESULT\b.*\bUNITS\b"),
}
_FOOTER = {
    Layout.THYROCARE: re.compile(r"^(Report Remarks\b|Page \d+ of \d+\b)"),
    Layout.MEDIBUDDY: re.compile(r"^(Interpretation\b|NOTE\s*:|Page \d+ of \d+\b)"),
}
_CONDITIONS = re.compile(r"\bCONDITIONS OF REPORTING\b", re.IGNORECASE)


class PageKind(StrEnum):
    RESULTS = "results"
    CONDITIONS = "conditions"  # "Conditions of Reporting" boilerplate
    OTHER = "other"  # cover, status summary, vitals, marketing


def page_layout(text: str) -> Layout | None:
    """The layout of a results page, or None for any other page."""
    for line in text.splitlines():
        for layout, table in _RESULTS_TABLE.items():
            if table.match(line):
                return layout
    return None


def classify_page(text: str) -> PageKind:
    if page_layout(text) is not None:
        return PageKind.RESULTS
    if _CONDITIONS.search(text):
        return PageKind.CONDITIONS
    return PageKind.OTHER


@dataclass(frozen=True)
class ResultsPageParts:
    layout: Layout
    header: str  # identity and sample header; parsed locally, never sent anywhere
    results: str  # from the table heading up to the footer


def split_results_page(text: str) -> ResultsPageParts:
    """Split a results page. The footer (remarks, interpretation, signing doctors, QR text)
    is dropped."""
    layout = page_layout(text)
    if layout is None:
        raise ValueError("not a results page")
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if _RESULTS_TABLE[layout].match(line))
    end = next(
        (i for i in range(start + 1, len(lines)) if _FOOTER[layout].match(lines[i])),
        len(lines),
    )
    return ResultsPageParts(
        layout=layout, header="\n".join(lines[:start]), results="\n".join(lines[start:end])
    )
