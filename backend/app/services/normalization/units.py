"""Unit normalization and analyte-independent conversion.

Units are compared through `unit_key` ("µg/mL" and "ug/ml" are the same unit). Conversion
only uses SI-prefix arithmetic within one kind of quantity: mass, moles, (international)
units or cell counts per volume, and mass per mass ("µg/mg of Creatinine" → "mg/g"). A
conversion that depends on the analyte (e.g. mg/dL → mmol/L) is never guessed; it returns None
and the row is surfaced for review.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

_MICRO = str.maketrans({"µ": "u", "μ": "u"})  # MICRO SIGN and GREEK SMALL LETTER MU
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_COUNT_WORDS = {"thou": 3, "thousand": 3, "lakh": 5, "lakhs": 5, "mill": 6, "million": 6}

_PREFIX = {
    "": Decimal(1),
    "k": Decimal(1000),
    "d": Decimal("0.1"),
    "c": Decimal("0.01"),
    "m": Decimal("0.001"),
    "u": Decimal("1e-6"),
    "n": Decimal("1e-9"),
    "p": Decimal("1e-12"),
    "f": Decimal("1e-15"),
}
_COUNT = re.compile(r"^10\^(?P<exp>\d+)/(?P<den>[kdcmunpf]?)l$")
_RATE = re.compile(
    r"^(?P<num>[kdcmunpf]?)(?P<base>mol|iu|eq|g|u)/(?P<den>[kdcmunpf]?)(?P<per>l|g)$"
)


def unit_key(unit: str) -> str:
    """A normalized spelling for comparing units: lower case, ASCII 'u' for micro, no spaces."""
    key = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "10^" + m[1].translate(_SUPERSCRIPT_DIGITS), unit)
    key = key.translate(_MICRO).lower()
    key = re.sub(r"\bof\s+creat(?:inine)?\b", "", key)  # "µg/mg of Creatinine" → "µg/mg"
    key = re.sub(r"\s+", "", key)
    key = key.replace("mcg", "ug").replace("cumm", "ul").replace("mm3", "ul")
    key = re.sub(r"^x(?=10\^)", "", key)  # "x 10^3/µL"
    word = re.fullmatch(r"([a-z]+)/(ul|l)", key)
    if word and word[1] in _COUNT_WORDS:
        key = f"10^{_COUNT_WORDS[word[1]]}/{word[2]}"
    return key


@dataclass(frozen=True)
class _Quantity:
    kind: tuple[str, str]  # (what is counted, per what), e.g. ("g", "l")
    scale: Decimal  # size relative to the base unit of that kind


def _quantity(key: str) -> _Quantity | None:
    if match := _COUNT.fullmatch(key):
        scale = Decimal(10) ** int(match["exp"]) / _PREFIX[match["den"]]
        return _Quantity(("count", "l"), scale)
    if match := _RATE.fullmatch(key):
        base = "u" if match["base"] == "iu" else match["base"]  # IU and U are used alike
        return _Quantity((base, match["per"]), _PREFIX[match["num"]] / _PREFIX[match["den"]])
    return None


def convert(value: Decimal, from_unit: str | None, to_unit: str) -> Decimal | None:
    """`value` in `from_unit` expressed in `to_unit`, or None if no safe conversion exists."""
    if from_unit is None or not from_unit.strip():
        return value if unit_key(to_unit) == "ratio" else None
    source, target = unit_key(from_unit), unit_key(to_unit)
    if source == target:
        return value
    a, b = _quantity(source), _quantity(target)
    if a is None or b is None or a.kind != b.kind:
        return None
    converted = value * (a.scale / b.scale).normalize()
    # Scaling up can leave an exponent (2.5E+2); show it as a plain number (250).
    exponent = converted.as_tuple().exponent
    return (
        converted.quantize(Decimal(1)) if isinstance(exponent, int) and exponent > 0 else converted
    )
