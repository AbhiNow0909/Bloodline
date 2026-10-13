"""Parse a results page's header block with regexes (no LLM), one parser per layout.

pdfplumber joins the two header columns into one line, e.g.
    Thyrocare: "Patient Name : ASHA FICTIONAL(58Y/F) Sample Collected on (SCT): 03 Mar 2025 08:15"
    MediBuddy: "Sample Type : SERUM Collected : 13/07/26, 04:33 PM"
so each pattern stops at the next known right-column label rather than at the line end.

Thyrocare's bracketed codes (SCT, SRT, RRT: sample collection / received / report release
time) name the field, not a time zone. Both layouts print Indian local time.
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
    client_id: str | None = None  # MediBuddy's "Client Name" (an account code); scrubbed too
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


# --- MediBuddy -------------------------------------------------------------------------------
#
#   Name : MR. RAVI FICTIONAL K
#   Age/ Gender : 41 years / Male Ref. Doctor : SELF
#   Sample Type : SERUM Collected : 13/07/26, 04:33 PM
#   Sample ID : AB1234567 Received : 13/07/26, 06:27 PM
#   Client Name : 1AB2345 Reported : 13/07/26, 07:13 PM

_MB_RIGHT_COLUMN = r"(?=\s+(?:Ref\. Doctor|Collected|Received|Reported)\s*:|\s*$)"
_MB_NAME = re.compile(r"^Name\s*:\s*(?P<name>.*?)" + _MB_RIGHT_COLUMN, re.MULTILINE)
_HONORIFIC = re.compile(r"^(?:MR|MRS|MS|MISS|MASTER|BABY|DR)\.?\s+", re.IGNORECASE)
_MB_AGE_SEX = re.compile(
    r"Age\s*/\s*Gender\s*:\s*(?:(?P<age>\d{1,3})\s*(?:years?|yrs?|Y)\b)?[^/\n]*/\s*"
    r"(?P<sex>Male|Female)\b",
    re.IGNORECASE,
)
_MB_DOCTOR = re.compile(r"Ref\. Doctor\s*:\s*(?P<value>.*?)" + _MB_RIGHT_COLUMN, re.MULTILINE)
_MB_SAMPLE = re.compile(r"Sample Type\s*:\s*(?P<value>.*?)" + _MB_RIGHT_COLUMN, re.MULTILINE)
_MB_SAMPLE_ID = re.compile(r"Sample ID\s*:\s*(?P<value>[A-Za-z0-9-]+)")
_MB_CLIENT = re.compile(r"Client Name\s*:\s*(?P<value>.*?)" + _MB_RIGHT_COLUMN, re.MULTILINE)
_MB_STAMP = r"\s*:\s*(?P<at>\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*[AP]M)"
_MB_COLLECTED = re.compile(r"\bCollected" + _MB_STAMP, re.IGNORECASE)
_MB_RECEIVED = re.compile(r"\bReceived" + _MB_STAMP, re.IGNORECASE)
_MB_REPORTED = re.compile(r"\bReported" + _MB_STAMP, re.IGNORECASE)


def _mb_timestamp(pattern: re.Pattern[str], text: str, warnings: list[str]) -> datetime | None:
    """Day first ("13/07/26, 04:33 PM"), as printed in India."""
    match = pattern.search(text)
    if match is None:
        return None
    stamp = " ".join(match["at"].replace(",", " ").split()).upper()
    for fmt in ("%d/%m/%y %I:%M %p", "%d/%m/%Y %I:%M %p"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    warnings.append("Unreadable date in report header")
    return None


def _value(match: re.Match[str] | None) -> str | None:
    return (match["value"].strip() or None) if match else None


def parse_medibuddy_header(text: str) -> ParsedHeader:
    warnings: list[str] = []
    name = _MB_NAME.search(text)
    age_sex = _MB_AGE_SEX.search(text)
    sample = _value(_MB_SAMPLE.search(text))
    return ParsedHeader(
        name=(_HONORIFIC.sub("", name["name"].strip()) or None) if name else None,
        age_years=int(age_sex["age"]) if age_sex and age_sex["age"] else None,
        sex=_SEXES[age_sex["sex"][0].upper()] if age_sex else None,
        referred_by=_value(_MB_DOCTOR.search(text)),
        sample_type=sample.upper() if sample else None,
        barcode=_value(_MB_SAMPLE_ID.search(text)),
        client_id=_value(_MB_CLIENT.search(text)),
        collected_at=_mb_timestamp(_MB_COLLECTED, text, warnings),
        received_at=_mb_timestamp(_MB_RECEIVED, text, warnings),
        released_at=_mb_timestamp(_MB_REPORTED, text, warnings),
        warnings=tuple(warnings),
    )
