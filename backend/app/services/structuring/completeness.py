"""Lines that look like a result but match no row the model returned: a skipped test.

The model now and then leaves out a row (seen with real reports). A line counts as a result
when it reads "<name> <number> <unit> <interval>", the way labs that print the range on the
same row lay out a test (MediBuddy). Labs that print ranges on separate lines (Thyrocare) are
not checked this way. The check only warns; the person compares with the PDF in review.
"""

import re
from collections.abc import Sequence

from app.services.normalization import parse_bounds
from app.services.structuring.schemas import StructuredMetric

_ROW = re.compile(r"^(?P<name>[A-Za-z][^:,]*?)\s+(?P<value>\d[\d.,]*)\s+(?P<rest>\S.*)$")
_MAX_UNIT_WORDS = 3  # "%", "mil/µL", "* 10^9/L", "ml/min/1.73 m2"


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if len(word) >= 2}


def _ends_with_interval(rest: str) -> bool:
    """A short unit followed by an interval ("% 13 - 43"); prose ("hours and …") is not."""
    words = rest.split()
    return any(
        parse_bounds(" ".join(words[i:])) for i in range(1, min(len(words), _MAX_UNIT_WORDS + 1))
    )


def possibly_missed(page_text: str, metrics: Sequence[StructuredMetric]) -> list[str]:
    """Names of result-looking lines on the page that no returned row accounts for. A row
    accounts for a line when its value starts the line's value and a word of its name is on
    the line ("C-Reactive Protein (CRP)" accounts for "CRP 4.5 mg/L < 5.0")."""
    missed = []
    for line in page_text.splitlines():
        match = _ROW.match(line.strip())
        if not match or not _ends_with_interval(match["rest"]):
            continue
        value, words = match["value"].casefold(), _words(line)
        if not any(
            " ".join(metric.value_text.split()).casefold().startswith(value)
            and _words(metric.raw_name) & words
            for metric in metrics
        ):
            missed.append(match["name"].strip())
    return missed
