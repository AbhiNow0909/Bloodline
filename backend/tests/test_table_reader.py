"""Reading results from table lines, without the AI. The lines mirror shapes seen on real
Thyrocare and MediBuddy reports (synthetic values)."""

from app.services.extraction.schemas import Column, ResultsPage, TableCell, TableLine
from app.services.structuring.schemas import LlmRange
from app.services.structuring.table_reader import TableReading, read_table

N, T, M, V, U, R = (
    Column.NAME,
    Column.TECHNOLOGY,
    Column.METHOD,
    Column.VALUE,
    Column.UNIT,
    Column.RANGE,
)


def line(*cells: tuple[Column | None, str]) -> TableLine:
    return TableLine(cells=tuple(TableCell(column=c, text=t) for c, t in cells))


def text(words: str) -> TableLine:
    """A line printed in the name column only (a heading, a note, a method line)."""
    return line((N, words))


def prose(words: str) -> TableLine:
    """Text running across columns."""
    return line((None, words))


def read(*lines: TableLine, sample_type: str | None = "SERUM") -> TableReading:
    page = ResultsPage(
        page_number=1,
        sample_type=sample_type,
        collected_at=None,
        received_at=None,
        released_at=None,
        text="",
        table=lines,
    )
    return read_table(page)


def ranges(*pairs: tuple[str | None, str]) -> list[LlmRange]:
    return [LlmRange(label=label, text=text) for label, text in pairs]


# --- MediBuddy: the range in its own column, "(Method: …)" lines ---------------------------


def test_rows_with_their_method_and_panel() -> None:
    reading = read(
        text("Liver Function Profile"),
        line((N, "Protein Total"), (V, "7.2"), (U, "g/dL"), (R, "6.4 - 8.3")),
        text("(Method: Biuret)"),
        line((N, "Bilirubin Direct"), (V, "0.21"), (U, "mg/dL"), (R, "Upto 0.25")),
    )

    first, second = reading.tests
    assert (first.raw_name, first.value, first.unit, first.method) == (
        "Protein Total",
        "7.2",
        "g/dL",
        "Biuret",
    )
    assert first.reference_ranges == ranges((None, "6.4 - 8.3"))
    assert (first.panel, first.sample_type) == ("Liver Function Profile", "SERUM")
    assert (second.raw_name, second.method) == ("Bilirubin Direct", None)
    assert reading.unread == ()


def test_a_range_of_several_lines_continues_beside_the_method_and_below() -> None:
    reading = read(
        line((N, "Cholesterol - Total"), (V, "182"), (U, "mg/dL"), (R, "<200"), (R, ": Desirable")),
        line(
            (N, "(Method: Cholesterol Oxidase, Esterase, peroxidase)"), (R, "200-239 : Borderline")
        ),
        line((R, ">240"), (R, ": High risk")),
        line((N, "Cholesterol VLDL"), (V, "24.0"), (U, "mg/dL"), (R, "5 - 40")),
    )

    total, vldl = reading.tests
    assert total.method == "Cholesterol Oxidase, Esterase, peroxidase"
    assert total.reference_ranges == ranges(
        ("<200", "Desirable"), ("200-239", "Borderline"), (">240", "High risk")
    )
    assert vldl.reference_ranges == ranges((None, "5 - 40"))


def test_text_results_and_the_labs_comments() -> None:
    reading = read(
        text("RBC Morphology"),
        line((N, "Remarks"), (V, "Microcytic Hypochromic")),  # the lab's comment, not a test
        line((N, "Colour"), (V, "Pale Yellow"), (R, "Pale Yellow")),
        line((N, "Leucocyte Esterase"), (V, "Negative")),
        line((N, "PUS(WBC) Cells"), (V, "3-4"), (U, "HPF"), (R, "0 - 5")),
        line((N, "Others"), (V, "Nil"), (R, "--")),
        line((N, "Impression"), (V, "S/O Microcytic Hypochromic Anaemia")),
        line((N, "Advise"), (V, "Kindly correlate clinically")),
    )

    assert [(t.raw_name, t.value) for t in reading.tests] == [
        ("Colour", "Pale Yellow"),
        ("Leucocyte Esterase", "Negative"),
        ("PUS(WBC) Cells", "3-4"),
        ("Others", "Nil"),
    ]
    assert reading.tests[0].reference_ranges == ranges((None, "Pale Yellow"))
    assert reading.tests[3].reference_ranges == []  # "--": nothing printed
    assert reading.unread == ()


def test_a_heading_ends_the_range_of_the_test_above() -> None:
    reading = read(
        line((N, "HbA1c"), (V, "6.1"), (U, "%"), (R, "Non-Diabetic: <= 5.6")),
        line((N, "(Method: HPLC)"), (R, "Pre Diabetic:5.7 - 6.4")),
        text("Microscopic Examination"),
        text("(Method: Microscopy)"),  # belongs to no test here
        line((R, "stray range")),
    )

    (hba1c,) = reading.tests
    assert hba1c.method == "HPLC"
    assert hba1c.reference_ranges == ranges(
        ("Non-Diabetic", "<= 5.6"), ("Pre Diabetic", "5.7 - 6.4")
    )


def test_text_results_may_have_brackets_and_commas() -> None:
    (protein,) = read(line((N, "URINARY PROTEIN"), (V, "Absent (Negative)"), (R, "Absent"))).tests

    assert protein.value == "Absent (Negative)"


def test_a_value_printed_with_its_unit_in_one_cell_is_split() -> None:
    (test,) = read(
        line((N, "Total Leucocyte Count (WBC)"), (V, "6500 cells/Cumm"), (R, "4000 - 10000"))
    ).tests

    assert (test.value, test.unit) == ("6500", "cells/Cumm")


# --- Thyrocare: ranges under "Bio. Ref. Interval." ------------------------------------------


def test_a_reference_block_and_its_method() -> None:
    reading = read(
        line((N, "CREATININE - URINE"), (T, "PHOTOMETRY"), (V, "84.20"), (U, "mg/dL")),
        text("Bio. Ref. Interval. :"),
        line((N, "Male"), (N, ":"), (N, "39 - 259 mg/dl")),
        text("Female: 28 - 217 mg/dl"),
        text("Method : Creatinine Jaffe Method, Rate-Blanked and Compensated"),
        line((N, "FERRITIN"), (T, "C.M.I.A"), (V, "48.3"), (U, "ng/mL")),
        text("Bio. Ref. Interval. :-"),
        text("Adults : 4.63 - 204.00 ng/ml"),
        text("Clinical Significance:"),
        text("Ferritin levels below 10 suggest low iron stores"),  # explanation, not a range
        text("Method:- CLIA"),
        text("Please correlate with clinical conditions."),
    )

    creatinine, ferritin = reading.tests
    assert creatinine.technology == "PHOTOMETRY"
    assert creatinine.reference_ranges == ranges(
        ("Male", "39 - 259 mg/dl"), ("Female", "28 - 217 mg/dl")
    )
    assert creatinine.method == "Creatinine Jaffe Method, Rate-Blanked and Compensated"
    assert ferritin.reference_ranges == ranges(("Adults", "4.63 - 204.00 ng/ml"))
    assert ferritin.method == "CLIA"


def test_two_range_tables_side_by_side_stay_apart() -> None:
    # HbA1c: ADA guidelines on the left, targets for known diabetics on the right.
    (hba1c,) = read(
        line((N, "HbA1c"), (T, "H.P.L.C"), (V, "5.4"), (U, "%")),
        text("Bio. Ref. Interval. :"),
        line((N, "As per ADA Guidelines"), (V, "Guidance For Known Diabetics")),
        line((N, "Below 5.7%"), (N, ": Normal"), (T, "Below 6.5% : Good Control")),
        line((N, "5.7% - 6.4% : Prediabetic"), (T, "6.5% - 7%"), (V, ": Fair Control")),
    ).tests

    assert hba1c.reference_ranges == ranges(
        (None, "As per ADA Guidelines"),
        (None, "Guidance For Known Diabetics"),
        ("Below 5.7%", "Normal"),
        ("Below 6.5%", "Good Control"),
        ("5.7% - 6.4%", "Prediabetic"),
        ("6.5% - 7%", "Fair Control"),
    )


def test_both_sexes_on_one_line_are_two_ranges_but_an_age_band_stays_whole() -> None:
    iron, esr = read(
        line(
            (N, "TOTAL IRON BINDING CAPACITY (TIBC)"), (T, "PHOTOMETRY"), (V, "310"), (U, "µg/dL")
        ),
        text("Bio. Ref. Interval. :"),
        line((N, "Male: 250 - 425 µg/dl"), (N, "Female: 250 - 450 µg/dl")),
        text("Method : Spectrophotometric Assay"),
        line((N, "ESR"), (T, "MODIFIED WESTERGREN"), (V, "12"), (U, "mm / hr")),
        text("Bio. Ref. Interval. :-"),
        line((N, "<50 yr : Male: 0-15 mm/hr"), (N, "Female: 0-20 mm/hr")),
    ).tests

    assert iron.reference_ranges == ranges(
        ("Male", "250 - 425 µg/dl"), ("Female", "250 - 450 µg/dl")
    )
    assert esr.reference_ranges == ranges(("<50 yr", "Male: 0-15 mm/hr Female: 0-20 mm/hr"))


def test_ranges_separated_by_double_bars_and_ratios_with_colons() -> None:
    vitamin_d, ratio = read(
        line((N, "25-OH VITAMIN D (TOTAL)"), (T, "E.C.L.I.A"), (V, "32.1"), (U, "ng/mL")),
        text("Bio. Ref. Interval. :-"),
        text("Deficiency : <=20 ng/ml || Insufficiency : 21-29 ng/ml"),
        text("Method:- ECLIA"),
        line(
            (N, "BUN / Sr.CREATININE RATIO"),
            (T, "CALCULATED"),
            (V, "12.5"),
            (U, "Ratio"),
            (R, "9:1-20:1"),
        ),
    ).tests

    assert vitamin_d.reference_ranges == ranges(
        ("Deficiency", "<=20 ng/ml"), ("Insufficiency", "21-29 ng/ml")
    )
    assert ratio.reference_ranges == ranges((None, "9:1-20:1"))  # not split at the colons


# --- Thyrocare tables: the range on the row --------------------------------------------------


def test_a_table_with_a_methodology_column() -> None:
    reading = read(
        line((N, "Total RBC"), (M, "HF & EI"), (V, "4.82"), (U, "X 10^6/µL"), (R, "4.5-5.5")),
        text("DIFFERENTIAL LEUCOCYTE COUNT"),
        line(
            (N, "Neutrophils Percentage"),
            (M, "Flow Cytometry"),
            (V, "61.2"),
            (U, "%"),
            (R, "40-80"),
        ),
        line(
            (N, "MENTZER INDEX"), (M, "Calculated"), (V, "17.4"), (U, "-"), (R, "*Refer Note below")
        ),
        line(
            (N, "COLOUR"),
            (M, "Visual Determination"),
            (V, "PALE YELLOW"),
            (U, "-"),
            (R, "Pale Yellow"),
        ),
    )

    rbc, neutrophils, mentzer, colour = reading.tests
    assert (rbc.method, rbc.technology, rbc.unit) == ("HF & EI", None, "X 10^6/µL")
    assert neutrophils.panel == "DIFFERENTIAL LEUCOCYTE COUNT"
    assert (mentzer.unit, mentzer.reference_ranges) == (None, ranges((None, "*Refer Note below")))
    assert (colour.value, colour.unit) == ("PALE YELLOW", None)


def test_nothing_after_the_closing_note_is_read() -> None:
    reading = read(
        line((N, "TOTAL CHOLESTEROL"), (T, "PHOTOMETRY"), (V, "182"), (U, "mg/dL"), (R, "< 200")),
        text("Please correlate with clinical conditions."),
        text("Method :"),
        text("CHOL - Cholesterol Oxidase, Esterase, Peroxidase"),
        line((N, "DESIRABLE <200"), (T, "LOW <40"), (V, "OPTIMAL <100"), (R, "NORMAL <150")),
        line((N, "BORDERLINE 200-239"), (V, "160"), (U, "mg/dl")),  # a guideline table
    )

    assert [t.raw_name for t in reading.tests] == ["TOTAL CHOLESTEROL"]
    assert reading.unread == ()


def test_method_abbreviations_are_not_results() -> None:
    reading = read(
        line((N, "SGOT / SGPT RATIO"), (T, "CALCULATED"), (V, "1.21"), (U, "Ratio"), (R, "< 2")),
        text("Method :"),  # a bare "Method :" heads a list of abbreviations
        text("SGOT - IFCC* Without Pyridoxal Phosphate Activation"),
        line((N, "PROT"), (V, "Biuret Method")),
    )

    assert [t.raw_name for t in reading.tests] == ["SGOT / SGPT RATIO"]
    assert reading.tests[0].method is None


# --- what the reader cannot read -------------------------------------------------------------


def test_a_result_that_cannot_be_read_is_reported() -> None:
    reading = read(
        line((N, "IRON"), (T, "PHOTOMETRY"), (V, "98"), (U, "µg/dL")),
        line((N, "MYSTERY TEST"), (T, "PHOTOMETRY"), (V, "4.5 6.7"), (U, "mg/dL")),
    )

    assert [t.raw_name for t in reading.tests] == ["IRON"]
    assert reading.unread == ("MYSTERY TEST",)


def test_a_text_result_that_cannot_be_read_is_reported_too() -> None:
    reading = read(line((N, "BACTERIA"), (V, "Seen. Moderate numbers of rods and cocci; repeat.")))

    assert (reading.tests, reading.unread) == ((), ("BACTERIA",))


def test_only_a_method_line_names_a_method() -> None:
    (sgot,) = read(
        line((N, "SGOT"), (T, "PHOTOMETRY"), (V, "31"), (U, "U/L")),
        text("Bio. Ref. Interval. :-"),
        text("Adults : < 35 U/L"),
        text("Clinical Significance:"),
        text("Methods of this laboratory are accredited"),  # not "Method :"
        text("Method:- IFCC without pyridoxal phosphate"),
    ).tests

    assert sgot.method == "IFCC without pyridoxal phosphate"


def test_explanations_are_not_read_as_results() -> None:
    reading = read(
        line((N, "AMYLASE"), (T, "PHOTOMETRY"), (V, "71.0"), (U, "U/L")),
        text("Bio. Ref. Interval. :-"),
        text("Adults : 28-100 U/L"),
        text("Interpretation:"),
        line((N, "About 85% of patients with"), (V, "Acute Pancreatitis")),
        line((N, "Lipemic sera may contain"), (V, "10 times")),
        prose("Moderate increases may be reported in normal pregnancy."),
    )

    assert [t.raw_name for t in reading.tests] == ["AMYLASE"]
    assert reading.tests[0].reference_ranges == ranges(("Adults", "28-100 U/L"))
    assert reading.unread == ()


def test_text_across_columns_ends_the_rows_but_a_full_row_starts_them_again() -> None:
    reading = read(
        line((N, "PCT"), (V, "0.21"), (U, "%"), (R, "0.1 - 0.4")),
        prose("Tests done on Automated Five Part Cell Counter. All abnormal haemograms reviewed."),
        line((N, "counts are"), (V, "Normal")),  # a sentence's words falling into columns
        line((N, "Platelet large cell ratio (P-LCR)"), (V, "28.1"), (U, "%"), (R, "13 - 43")),
    )

    assert [t.raw_name for t in reading.tests] == ["PCT", "Platelet large cell ratio (P-LCR)"]


def test_a_page_without_table_lines_reads_nothing() -> None:
    assert read() == TableReading(tests=(), unread=())
