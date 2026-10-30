"""Results tables as cells, from word positions. PDFs are built here with the column positions
of real Thyrocare and MediBuddy reports (synthetic text)."""

from app.services.extraction.layout import Layout
from app.services.extraction.pdf_text import read_pages
from app.services.extraction.schemas import Column, TableLine
from app.services.extraction.table import table_lines
from tests.synthetic_pdf import Cells, build_pdf, cells, lines

N, T, M, V, U, R = (
    Column.NAME,
    Column.TECHNOLOGY,
    Column.METHOD,
    Column.VALUE,
    Column.UNIT,
    Column.RANGE,
)


def table(*rows: str | Cells, layout: Layout) -> tuple[TableLine, ...]:
    (page,) = read_pages(build_pdf([lines(*rows)]))
    return table_lines(page.words, layout, lambda text: text)


def columns(line: TableLine) -> list[tuple[Column | None, str]]:
    return [(cell.column, cell.text) for cell in line.cells]


THYROCARE_TABLE = cells(
    (45, "TEST NAME"), (241, "METHODOLOGY"), (362, "VALUE"), (426, "UNITS"),
    (483, "Bio. Ref. Interval."),
)  # fmt: skip
MEDIBUDDY_TABLE = cells(
    (24, "TEST DESCRIPTION"), (269, "RESULT"), (351, "UNITS"),
    (404, "BIOLOGICAL REFERENCE INTERVAL"),
)  # fmt: skip


def test_a_row_is_split_into_its_columns_however_many_words_a_cell_has() -> None:
    (rbc, colour) = table(
        THYROCARE_TABLE,
        cells((45, "Total RBC"), (241, "HF & EI"), (370, "4.82"), (426, "X 10^6/µL"),
              (483, "4.5-5.5")),
        cells((45, "COLOUR"), (241, "Visual Determination"), (362, "PALE YELLOW"), (430, "-"),
              (483, "Pale Yellow")),
        layout=Layout.THYROCARE,
    )  # fmt: skip

    assert columns(rbc) == [
        (N, "Total RBC"), (M, "HF & EI"), (V, "4.82"), (U, "X 10^6/µL"), (R, "4.5-5.5"),
    ]  # fmt: skip
    assert columns(colour) == [
        (N, "COLOUR"), (M, "Visual Determination"), (V, "PALE YELLOW"), (U, "-"),
        (R, "Pale Yellow"),
    ]  # fmt: skip


def test_centred_values_and_units_land_in_their_columns() -> None:
    # MediBuddy centres values and units: text results start left of RESULT, long units left
    # of UNITS. Each cell belongs to the column it lines up with best.
    esterase, leucocytes = table(
        MEDIBUDDY_TABLE,
        cells((20, "Leucocyte Esterase"), (246, "Negative")),
        cells((20, "Total Leucocyte Count (WBC)"), (277, "6500"), (346, "cells/Cumm"),
              (416, "4000 - 10000")),
        layout=Layout.MEDIBUDDY,
    )  # fmt: skip

    assert columns(esterase) == [(N, "Leucocyte Esterase"), (V, "Negative")]
    assert columns(leucocytes) == [
        (N, "Total Leucocyte Count (WBC)"), (V, "6500"), (U, "cells/Cumm"), (R, "4000 - 10000"),
    ]  # fmt: skip


def test_a_range_continuing_below_a_row_stays_in_the_range_column() -> None:
    (_, method, last) = table(
        MEDIBUDDY_TABLE,
        cells((20, "Cholesterol - Total"), (277, "182"), (363, "mg/dL"), (416, "<200 : Desirable")),
        cells((20, "(Method: Cholesterol Oxidase)"), (416, "200-239 : Borderline risk")),
        cells((416, ">240 : High risk")),
        layout=Layout.MEDIBUDDY,
    )

    assert columns(method) == [
        (N, "(Method: Cholesterol Oxidase)"),
        (R, "200-239 : Borderline risk"),
    ]
    assert columns(last) == [(R, ">240 : High risk")]


def test_text_running_across_columns_is_in_none() -> None:
    (note,) = table(
        MEDIBUDDY_TABLE,
        "Tests done on Automated Five Part Cell Counter. All abnormal haemograms are reviewed and "
        "confirmed microscopically by a pathologist.",
        layout=Layout.MEDIBUDDY,
    )

    assert [cell.column for cell in note.cells] == [None]


def test_only_the_results_region_is_read_and_every_cell_is_scrubbed() -> None:
    pdf = build_pdf(
        [
            lines(
                "Name : MR. RAVI FICTIONAL K",
                MEDIBUDDY_TABLE,
                cells((20, "Remarks"), (246, "Seen by RAVI")),
                "NOTE : This sample is processed at Synthetic Diagnostics Lab.",
                cells((20, "After the footer"), (277, "1.0")),
            )
        ]
    )
    (page,) = read_pages(pdf)

    (remarks,) = table_lines(
        page.words, Layout.MEDIBUDDY, lambda text: text.replace("RAVI", "[NAME]")
    )

    assert columns(remarks) == [(N, "Remarks"), (V, "Seen by [NAME]")]


def test_a_page_without_the_table_heading_has_no_table() -> None:
    assert table("Vital Signs Summary", "Systolic BP (mm Hg) 120", layout=Layout.MEDIBUDDY) == ()
