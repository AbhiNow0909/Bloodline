"""Printed reference ranges → numeric bounds, and choosing the one for the patient's sex.

Reports print lines such as "Male: 39 - 259 mg/dl", "Women: 4.63 - 204.00 ng/ml" or
"Adults: Less than 30 µg/ml". The LLM only splits them into (label, text); the numbers are
parsed here. Bounds are treated as inclusive.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.models import Sex

_NUM = r"(\d+(?:\.\d+)?)"
_BETWEEN = re.compile(rf"^{_NUM}\s*(?:-|\u2013|\u2014|to)\s*{_NUM}")  # -, en/em dash, "to"
_UPPER = re.compile(rf"^(?:<=?|≤|less than(?: or equal to)?|below|up\s*to|upto|under)\s*{_NUM}")
_LOWER = re.compile(rf"^(?:>=?|≥|more than|greater than(?: or equal to)?|above|over)\s*{_NUM}")

_MALE = {"male", "males", "man", "men", "m"}
_FEMALE = {"female", "females", "woman", "women", "f"}
# Labels that describe the general reference interval rather than a subgroup.
_GENERAL = {
    "adult",
    "adults",
    "all",
    "general",
    "normal",
    "normal range",
    "reference",
    "reference range",
    "reference interval",
    "desirable",
    "optimal",
}


@dataclass(frozen=True)
class Bounds:
    low: Decimal | None
    high: Decimal | None


@dataclass(frozen=True)
class RangeLine:
    label: str | None  # as printed before the colon, e.g. "Male", "Adults"; None if unlabelled
    text: str  # as printed after the colon, e.g. "39 - 259 mg/dl"


@dataclass(frozen=True)
class SelectedRange:
    bounds: Bounds
    label: str | None


def parse_bounds(text: str) -> Bounds | None:
    """ "39 - 259 mg/dl" → (39, 259); "Less than 30 µg/ml" → (None, 30); "> 5" → (5, None)."""
    normalized = " ".join(text.strip().lower().split())
    if match := _BETWEEN.match(normalized):
        low, high = Decimal(match[1]), Decimal(match[2])
        return Bounds(low, high) if low <= high else None
    if match := _UPPER.match(normalized):
        return Bounds(None, Decimal(match[1]))
    if match := _LOWER.match(normalized):
        return Bounds(Decimal(match[1]), None)
    return None


def _audience(label: str | None) -> Sex | str | None:
    """'male', 'female', 'general', or None for a subgroup we cannot place (e.g. children)."""
    if label is None or not label.strip():
        return "general"
    words = set(re.findall(r"[a-z]+", label.lower()))
    is_male, is_female = bool(words & _MALE), bool(words & _FEMALE)
    if is_male != is_female:
        return "male" if is_male else "female"
    if " ".join(label.lower().split()) in _GENERAL or words <= {"adult", "adults", "all"}:
        return "general"
    return None


def select_range(lines: list[RangeLine], sex: Sex) -> SelectedRange | None:
    """The range for this patient: a line for their sex, else the single general line.

    Returns None when nothing fits unambiguously (several candidates, only subgroup ranges
    such as children or age bands, or nothing parseable); the row is then flagged 'unknown'
    and the printed text is shown for review.
    """
    parsed = [(line, _audience(line.label), parse_bounds(line.text)) for line in lines]
    for wanted in (sex, "general"):
        matches = [(line, bounds) for line, who, bounds in parsed if who == wanted and bounds]
        if len(matches) == 1:
            line, bounds = matches[0]
            return SelectedRange(bounds=bounds, label=line.label)
        if len(matches) > 1:
            return None
    return None
