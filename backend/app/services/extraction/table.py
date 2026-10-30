"""A results table as printed cells, from word positions.

Labs print results in fixed columns (TEST NAME | TECHNOLOGY | VALUE | UNITS | Bio. Ref.
Interval.), but the text layer alone cannot say where a multi-word method ends and the value
begins ("Total RBC HF & EI 4.82 X 10^6/µL"). The words' positions can: inside a cell words
are a normal space apart (about 3 points), between cells there is a column gap. Each cell is
then placed in the column whose heading it lines up with best; text running across several
columns (notes, explanations) belongs to none.
"""

from collections.abc import Callable, Sequence
from itertools import pairwise

from app.services.extraction.layout import Layout, is_footer, is_table_heading
from app.services.extraction.pdf_text import PdfWord
from app.services.extraction.schemas import Column, TableCell, TableLine

LINE_TOLERANCE = 3.0  # words whose tops differ by at most this much are on the same line
CELL_GAP = 4.0  # a wider gap between two words separates cells; a space is about 3 points

# The words that start each column heading, as printed by the supported labs.
_HEADING_WORDS = {
    "TEST": Column.NAME,
    "TECHNOLOGY": Column.TECHNOLOGY,
    "METHODOLOGY": Column.METHOD,
    "VALUE": Column.VALUE,
    "RESULT": Column.VALUE,
    "UNITS": Column.UNIT,
    "Bio.": Column.RANGE,
    "BIOLOGICAL": Column.RANGE,
}


def _lines(words: Sequence[PdfWord]) -> list[list[PdfWord]]:
    lines: list[list[PdfWord]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(lines[-1][0].top - word.top) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _text(words: Sequence[PdfWord]) -> str:
    return " ".join(word.text for word in words)


def _cells(line: Sequence[PdfWord]) -> list[list[PdfWord]]:
    cells: list[list[PdfWord]] = []
    for word in line:
        if cells and word.x0 - cells[-1][-1].x1 <= CELL_GAP:
            cells[-1].append(word)
        else:
            cells.append([word])
    return cells


class _Columns:
    """Where each column lies, from the table heading. A column reaches halfway to its
    neighbours' headings: values and units are often centred, not aligned with the heading."""

    def __init__(self, heading: Sequence[PdfWord]) -> None:
        spans: list[tuple[Column, float, float]] = []
        for word in heading:
            column = _HEADING_WORDS.get(word.text)
            if column is not None and column not in {c for c, _, _ in spans}:
                spans.append((column, word.x0, word.x1))
            elif spans:  # a later word of the same heading ("NAME", "Ref.", "INTERVAL")
                column, x0, _ = spans[-1]
                spans[-1] = (column, x0, word.x1)
        spans.sort(key=lambda span: span[1])
        self.columns = [column for column, _, _ in spans]
        # Boundaries between neighbouring columns: halfway between their headings.
        self.bounds = [(left[2] + right[1]) / 2 for left, right in pairwise(spans)]

    def column_of(self, x0: float, x1: float) -> Column | None:
        # Text starting in the first column and running past the second is not a cell.
        if len(self.bounds) >= 2 and x0 < self.bounds[0] and x1 > self.bounds[1]:
            return None
        edges = [float("-inf"), *self.bounds, float("inf")]
        overlaps = [min(x1, right) - max(x0, left) for left, right in pairwise(edges)]
        return self.columns[overlaps.index(max(overlaps))]


def table_lines(
    words: Sequence[PdfWord], layout: Layout, scrub: Callable[[str], str]
) -> tuple[TableLine, ...]:
    """The lines of the page's results table, below its heading and above the footer (the
    same region as the page's results text), with each cell's text scrubbed."""
    lines = _lines(words)
    start = next((i for i, line in enumerate(lines) if is_table_heading(_text(line), layout)), None)
    if start is None:
        return ()
    columns = _Columns(lines[start])
    table: list[TableLine] = []
    for line in lines[start + 1 :]:
        if is_footer(_text(line), layout):
            break
        cells = tuple(
            TableCell(column=columns.column_of(cell[0].x0, cell[-1].x1), text=scrub(_text(cell)))
            for cell in _cells(line)
        )
        table.append(TableLine(cells=cells))
    return tuple(table)
