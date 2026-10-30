"""Reading a page's results from its table lines, without the AI.

The supported labs print one test per row: the name, then the technology or method, the
value, the unit and, when the table has that column, the reference interval (see
`extraction/table.py` for how lines become cells). Around the rows:

- Thyrocare prints a test's range on lines after "Bio. Ref. Interval. :", then "Method : …";
  explanations, notes and a list of method abbreviations may follow.
- MediBuddy prints "(Method: …)" under a row; a range of several lines continues in the
  range column, beside the method line and below it.
- A heading above a group of rows ("Lipid Profile", "DIFFERENTIAL LEUCOCYTE COUNT") is the
  panel of the rows below it.

The rows become the same `LlmTest` entries the AI would return, so values, ranges, units,
dictionary matches and flags are derived from them exactly as before. A line that looks like
a result but cannot be read this way is reported in `unread`, so the page can be given to
the AI instead.
"""

import re
from dataclasses import dataclass, field

from app.services.extraction.schemas import Column, ResultsPage, TableLine
from app.services.structuring.schemas import LlmRange, LlmTest

# Thyrocare: nothing after this on a page is a result (method keys, guideline tables).
# "Tests Done : …" lists the tests ordered; MediBuddy's "Tests done on …" is a note.
_STOP = re.compile(r"^(Please correlate\b|Tests Done\s*:|~~)", re.IGNORECASE)
_RANGE_HEADING = re.compile(r"^Bio\.?\s*Ref\.?\s*Interval", re.IGNORECASE)
_METHOD_UNDER_ROW = re.compile(r"^\(Method\s*:\s*(?P<method>.*?)\)?$", re.IGNORECASE)
_METHOD_LINE = re.compile(r"^Method\s*:\s*-?\s*(?P<method>.*)$", re.IGNORECASE)  # "Method:- …"
# The start of explanations, notes and references: not results, not ranges, not headings.
_PROSE = re.compile(
    r"^(Clinical|Notes?\b|Interpretation|Disclaimer|References?\b|Specifications|Kit\b|"
    r"Comments?\b|Remarks?\b|Alert\b|Associated|Factors|[*•\-\u2013]|\d+\.\s)",
    re.IGNORECASE,
)
# Rows with these names are the lab's comments, not tests ("Impression S/O …").
_NOT_TESTS = {
    "remark",
    "remarks",
    "impression",
    "advise",
    "advice",
    "comment",
    "comments",
    "note",
    "notes",
    "interpretation",
    "conclusion",
    "opinion",
}
_NAME = re.compile(r"^[A-Za-z0-9%(]")
_NUMBER = r"\d+(?:[.,]\d+)?"
_NUMERIC_VALUE = re.compile(rf"^(?:[<>≤≥]=?\s*)?{_NUMBER}(?:\s*[-\u2013]\s*{_NUMBER})?$")
# "Not-Detected", "Within Normal Limits", "Absent (Negative)": a few words, not a sentence.
_TEXT_VALUE = re.compile(r"^[A-Za-z(][A-Za-z()/,+-]*(?: [A-Za-z()][A-Za-z()/,+-]*){0,5}$")
_PLUS_VALUE = re.compile(r"^\+{1,4}$")  # "++"
_NOTHING = {"", "-", "--", "\u2014", "\u2013"}  # printed in a column that has nothing for this test
_SEX_LABEL = re.compile(r"^(?:male|female|men|women)\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class TableReading:
    tests: tuple[LlmTest, ...]
    unread: tuple[str, ...]  # names of lines that look like results but were not read


@dataclass
class _Row:
    name: str
    value: str
    unit: str | None
    technology: str | None
    method: str | None
    panel: str | None
    ranges: list[LlmRange] = field(default_factory=list)
    range_column: bool = False  # its range is printed in the range column (and may continue)


def _clean(text: str | None) -> str | None:
    text = " ".join((text or "").split())
    return None if text in _NOTHING else text


def _is_test_name(name: str) -> bool:
    return (
        bool(_NAME.match(name))
        and not _PROSE.match(name)
        and name.rstrip(" :").casefold() not in _NOT_TESTS
    )


def _range(piece: str) -> LlmRange | None:
    """One printed range: the label is the text before the first colon, unless that colon is
    part of a ratio ("10:1-20:1"). The same split the AI was asked to make."""
    piece = " ".join(piece.split())
    if piece in _NOTHING:
        return None
    for i, char in enumerate(piece):
        if char == ":" and not (0 < i < len(piece) - 1 and piece[i - 1 : i + 2 : 2].isdigit()):
            return LlmRange(label=piece[:i].strip() or None, text=piece[i + 1 :].strip())
    return LlmRange(label=None, text=piece)


def _ranges(text: str | None) -> list[LlmRange]:
    """Ranges printed in one place; "||" separates ranges printed on the same line."""
    pieces = (piece for piece in (text or "").split("||"))
    return [r for r in map(_range, pieces) if r is not None]


def _block_ranges(line: TableLine) -> list[LlmRange]:
    """A line of a "Bio. Ref. Interval." block. Labs sometimes print two range tables side by
    side (HbA1c: general guidelines, and targets for known diabetics); the second starts
    right of the name column. A line listing both sexes is two ranges, but only when it starts
    with a sex: "<50 yr : Male: … Female: …" is one age band, left for review."""
    left: list[list[str]] = [[]]
    right: list[str] = []
    for cell in line.cells:
        if cell.column not in {Column.NAME, None}:
            right.append(cell.text)
        elif left[-1] and _SEX_LABEL.match(cell.text) and _SEX_LABEL.match(left[0][0]):
            left.append([cell.text])
        else:
            left[-1].append(cell.text)
    return [r for group in [*left, right] if group for r in _ranges(" ".join(group))]


def _row(line: TableLine, *, needs: tuple[Column, ...] = ()) -> _Row | None:
    """The line as a test row, or None. `needs`: columns of which the row must have one, where
    text that is not a table could otherwise pass for a row."""
    name, value = _clean(line.get(Column.NAME)), _clean(line.get(Column.VALUE))
    if name is None or value is None or not _is_test_name(name):
        return None
    if needs and not any(line.get(column) for column in needs):
        return None
    unit = _clean(line.get(Column.UNIT))
    if not (_NUMERIC_VALUE.match(value) or _TEXT_VALUE.match(value) or _PLUS_VALUE.match(value)):
        # The value and its unit in one cell ("6500 cells/Cumm"), with nothing under UNITS.
        first, _, rest = value.partition(" ")
        if unit is not None or not rest or not _NUMERIC_VALUE.match(first):
            return None
        value, unit = first, rest
    range_text = line.get(Column.RANGE)
    return _Row(
        name=name,
        value=value,
        unit=unit,
        technology=_clean(line.get(Column.TECHNOLOGY)),
        method=_clean(line.get(Column.METHOD)),
        panel=None,
        ranges=_ranges(range_text),
        range_column=range_text is not None,
    )


def _looks_like_result(line: TableLine) -> bool:
    """A test name with something in the value column: a result, unless something else read
    it. Rows named "Remarks", "Impression" and the like are the lab's comments."""
    name = _clean(line.get(Column.NAME))
    return name is not None and _is_test_name(name) and _clean(line.get(Column.VALUE)) is not None


def _method(line: TableLine) -> str | None:
    """The method named on a method line ("" for a bare "Method :"), or None."""
    if match := _METHOD_UNDER_ROW.match(line.get(Column.NAME) or ""):
        return match["method"].strip()
    if match := _METHOD_LINE.match(line.text):
        return match["method"].strip()
    return None


def _is_heading(line: TableLine) -> bool:
    text = line.text
    return (
        len(line.cells) == 1
        and line.cells[0].column is Column.NAME
        and any(char.isalpha() for char in text)
        and len(text.split()) <= 8
        and not text.endswith(".")
        and not _PROSE.match(text)
    )


# Where text that is not a table could pass for a row, a row must have one of these columns:
# in a range block, a Thyrocare row's technology or method; in explanations, also a unit or a
# range, which a table row has and a sentence does not.
_ROW_NEEDS = {
    "rows": (),
    "ranges": (Column.TECHNOLOGY, Column.METHOD),
    "prose": (Column.TECHNOLOGY, Column.METHOD, Column.UNIT, Column.RANGE),
}


def read_table(page: ResultsPage) -> TableReading:
    rows: list[_Row] = []
    unread: list[str] = []
    panel: str | None = None
    current: _Row | None = None
    # rows: reading rows; ranges: in a "Bio. Ref. Interval." block; prose: in explanations
    mode = "rows"
    for line in page.table:
        text = line.text.strip()
        if _STOP.match(text):
            break
        row = _row(line, needs=_ROW_NEEDS[mode])
        if row is not None:
            row.panel = panel
            rows.append(row)
            current, mode = row, "rows"
            continue
        if _RANGE_HEADING.match(text):
            mode = "ranges" if current is not None else "prose"
            continue
        method = _method(line)
        if method is not None:
            if current is not None and current.method is None and method:
                current.method = method
            if current is not None and current.range_column:
                current.ranges += _ranges(line.get(Column.RANGE))
            # A bare "Method :" heads a list of method abbreviations, not results.
            mode = "rows" if method else "prose"
            continue
        if mode == "ranges":
            if _PROSE.match(text):
                mode = "prose"
            elif current is not None:
                current.ranges += _block_ranges(line)
            continue
        if mode == "prose":
            continue
        if all(cell.column is Column.RANGE for cell in line.cells):
            if current is not None and current.range_column:  # a range continuing below
                current.ranges += _ranges(line.get(Column.RANGE))
            continue
        if _looks_like_result(line):
            unread.append(_clean(line.get(Column.NAME)) or text)
            continue
        if line.get(Column.NAME) and line.get(Column.VALUE):
            continue  # the lab's comment in the table ("Remarks …", "Impression …")
        if _PROSE.match(text) or any(cell.column is None for cell in line.cells):
            mode = "prose"
        elif _is_heading(line):
            panel, current = text, None
    tests = tuple(
        LlmTest(
            raw_name=row.name,
            panel=row.panel,
            technology=row.technology,
            value=row.value,
            unit=row.unit,
            reference_ranges=row.ranges,
            method=row.method,
            sample_type=page.sample_type,
        )
        for row in rows
    )
    return TableReading(tests=tests, unread=tuple(unread))
