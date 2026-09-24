"""Parse a results page's header block with regexes (no LLM).

pdfplumber joins the two header columns into one line, e.g.
    "Patient Name : ASHA FICTIONAL(58Y/F) Sample Collected on (SCT): 03 Mar 2025 08:15"
so each pattern stops at the next known right-column label rather than at the line end.

The bracketed codes (SCT, SRT, RRT: sample collection / received / report release time) name
the field, not a time zone. Times are printed in Indian local time.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.models import Sex

# India Standard Time has no daylight saving, so a fixed offset is exact (and needs no tzdata).
IST = timezone(timedelta(hours=5, minutes=30), "IST")

# Where a left-column value ends: an opening bracket (age/sex), a full right-column label, or
# the end of the line. Labels are matched as whole phrases, so a surname such as "Test" or
# "Sample" is not mistaken for one (a truncated name would escape scrubbing).
_RIGHT_COLUMN = (
    r"(?=\s*\(|\s+Sample (?:Collected|Received) on\b|\s+Tests (?:Asked|Done)\b"
    r"|\s+Report Released on\b|\s*$)"
)
_PATIENT = re.compile(
    r"Patient Name\s*:\s*(?P<name>.*?)\s*"
    r"(?:\(\s*(?P<age>\d{1,3})\s*Y\s*/\s*(?P<sex>[MF])\s*\)|" + _RIGHT_COLUMN + ")",
    re.IGNORECASE | re.MULTILINE,
)
_REFERRED_BY = re.compile(
    r"Referred By\s*:\s*(?P<value>.*?)" + _RIGHT_COLUMN, re.IGNORECASE | re.MULTILINE
)
_TIMESTAMP = (
    r"\s*(?:\(\s*[A-Za-z]{2,5}\s*\))?\s*:\s*(?P<at>\d{1,2} [A-Za-z]{3} \d{4} \d{1,2}:\d{2})"
)
_COLLECTED = re.compile(r"Sample Collected on" + _TIMESTAMP, re.IGNORECASE)
_RECEIVED = re.compile(r"Sample Received on" + _TIMESTAMP, re.IGNORECASE)
_RELEASED = re.compile(r"Report Released on" + _TIMESTAMP, re.IGNORECASE)
_SAMPLE_AND_BARCODE = re.compile(
    r"Sample Type\s*\|\s*Barcode\s*:\s*"
    r"(?P<sample>[A-Za-z][A-Za-z /-]*?)\s*\|\s*(?P<barcode>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SEXES: dict[str, Sex] = {"M": "male", "F": "female"}


@dataclass(frozen=True)
class ParsedHeader:
    name: str | None = None
    age_years: int | None = None
    sex: Sex | None = None
    referred_by: str | None = None
    sample_type: str | None = None
    barcode: str | None = None
    collected_at: datetime | None = None
    received_at: datetime | None = None
    released_at: datetime | None = None
    warnings: tuple[str, ...] = field(default=())


def _timestamp(pattern: re.Pattern[str], text: str, warnings: list[str]) -> datetime | None:
    match = pattern.search(text)
    if match is None:
        return None
    try:
        return datetime.strptime(match["at"], "%d %b %Y %H:%M").replace(tzinfo=IST)
    except ValueError:
        warnings.append("Unreadable date in report header")
        return None


def parse_header(text: str) -> ParsedHeader:
    warnings: list[str] = []
    patient = _PATIENT.search(text)
    referred = _REFERRED_BY.search(text)
    sample = _SAMPLE_AND_BARCODE.search(text)
    return ParsedHeader(
        name=(patient["name"].strip() or None) if patient else None,
        age_years=int(patient["age"]) if patient and patient["age"] else None,
        sex=_SEXES[patient["sex"].upper()] if patient and patient["sex"] else None,
        referred_by=(referred["value"].strip() or None) if referred else None,
        sample_type=sample["sample"].strip().upper() if sample else None,
        barcode=sample["barcode"] if sample else None,
        collected_at=_timestamp(_COLLECTED, text, warnings),
        received_at=_timestamp(_RECEIVED, text, warnings),
        released_at=_timestamp(_RELEASED, text, warnings),
        warnings=tuple(warnings),
    )
