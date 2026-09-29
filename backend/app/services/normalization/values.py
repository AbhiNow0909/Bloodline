"""Printed result values → exact decimals. Numbers never come from the LLM, only its text."""

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
_MAX_DIGITS = 18  # no lab value needs more; longer "numbers" are kept as text only


def parse_number(text: str) -> Decimal | None:
    """A plain printed number ("84.20", "1,234.5") as an exact Decimal; anything else is None.

    Qualified or descriptive results ("<0.5", ">1000", "Negative", "Trace") stay text-only:
    they cannot be compared against a range without guessing.
    """
    candidate = text.strip().replace(",", "")
    if not _NUMBER.fullmatch(candidate) or sum(c.isdigit() for c in candidate) > _MAX_DIGITS:
        return None
    try:
        return Decimal(candidate)
    except InvalidOperation:  # pragma: no cover - the regex already guarantees a valid number
        return None
