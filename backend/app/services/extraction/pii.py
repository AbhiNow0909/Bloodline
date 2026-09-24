"""Scrub identity data from report text before it can reach an LLM.

The header block and footer are already dropped by `layout.split_results_page`; this is the
second line of defence for anything that appears inside the results region. It prefers
over-scrubbing: a scrubbed test name is caught in human review, a leaked name is not.
"""

import re
from collections.abc import Iterable

from app.services.extraction.schemas import PrintedIdentity

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Indian mobile numbers: optional +91 / 91 prefix, and "98765 43210" / "98765-43210" grouping.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
# "Dr" / "DR." followed by up to three capitalised words (a second "Dr" starts a new match).
_DOCTOR = re.compile(r"\b[Dd][Rr]\.?\s+(?:(?!Dr\b|DR\b)[A-Z][A-Za-z.'-]*\s*){1,3}")
_MIN_NAME_PART = 3  # shorter parts (initials) would also hit units and symbols like "K"
_NOT_A_NAME = {"self", "dr", "dr."}


def _words(values: Iterable[str]) -> set[str]:
    parts = {part for value in values for part in re.split(r"[\s,.()]+", value)}
    return {p for p in parts if len(p) >= _MIN_NAME_PART and p.lower() not in _NOT_A_NAME}


def _replace_words(text: str, words: set[str], label: str) -> str:
    # Longest first, so "FICTIONALS" is not left half-replaced by "FICTIONAL".
    for word in sorted(words, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", label, text, flags=re.IGNORECASE)
    return text


def _replace_phrases(text: str, phrases: Iterable[str], label: str) -> str:
    """Whole printed names first, so parts too short to scrub alone (e.g. "LI") still go."""
    for phrase in phrases:
        parts = [re.escape(part) for part in phrase.split()]
        if parts and phrase.strip().lower() not in _NOT_A_NAME:
            pattern = r"[\s,]+".join(parts)
            text = re.sub(rf"(?<!\w){pattern}(?!\w)", label, text, flags=re.IGNORECASE)
    return text


def scrub_text(text: str, identity: PrintedIdentity) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    for barcode in identity.barcodes:
        text = re.sub(rf"(?<!\w){re.escape(barcode)}(?!\w)", "[BARCODE]", text, flags=re.I)
    text = _replace_phrases(text, identity.names, "[NAME]")
    text = _replace_words(text, _words(identity.names), "[NAME]")
    text = _replace_phrases(text, identity.referred_by, "[DOCTOR]")
    text = _replace_words(text, _words(identity.referred_by), "[DOCTOR]")
    return _DOCTOR.sub("[DOCTOR] ", text)


def find_leaks(text: str, identity: PrintedIdentity) -> list[str]:
    """Kinds of identity data still present in `text` (kinds only, never the values)."""
    leaks = []
    if _EMAIL.search(text):
        leaks.append("email")
    if _PHONE.search(text):
        leaks.append("phone")
    if any(re.search(rf"(?<!\w){re.escape(b)}(?!\w)", text, re.I) for b in identity.barcodes):
        leaks.append("barcode")
    for kind, values in (("name", identity.names), ("referring doctor", identity.referred_by)):
        words = _words(values)
        if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I) for w in words):
            leaks.append(kind)
    return leaks
