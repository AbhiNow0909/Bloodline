"""Splitting scrubbed report text into chunks for embedding."""

from itertools import pairwise

from app.services.embeddings import chunk_report
from app.services.embeddings.chunking import chunk_page
from tests import synthetic_pdf
from tests.embedding_helpers import extraction_with_pages, synthetic_extraction

HEADER = "Sample type: SERUM"


def test_a_short_page_is_one_chunk_with_its_sample_type() -> None:
    assert chunk_page("FERRITIN C.M.I.A 48.3 ng/mL\nMethod : CMIA", HEADER) == [
        "Sample type: SERUM\nFERRITIN C.M.I.A 48.3 ng/mL\nMethod : CMIA"
    ]


def test_layout_spacing_and_blank_lines_are_dropped() -> None:
    assert chunk_page("  FERRITIN    48.3   ng/mL  \n\n   \nMethod :  CMIA ", HEADER) == [
        "Sample type: SERUM\nFERRITIN 48.3 ng/mL\nMethod : CMIA"
    ]
    assert chunk_page(" \n\n ", HEADER) == []


def test_long_pages_split_on_lines_with_one_line_of_overlap() -> None:
    lines = [f"TEST {n} RESULT {n}.0 mg/dL Method : photometry" for n in range(40)]
    chunks = chunk_page("\n".join(lines), HEADER, max_chars=300)

    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert all(chunk.startswith(HEADER + "\n") for chunk in chunks)
    bodies = [chunk.splitlines()[1:] for chunk in chunks]
    # Each chunk starts with the line the previous one ended with.
    for previous, current in pairwise(bodies):
        assert current[0] == previous[-1]
    # Every line is kept, in order.
    seen = [line for body in bodies for line in body]
    assert list(dict.fromkeys(seen)) == lines


def test_a_line_longer_than_a_chunk_is_cut_at_spaces_or_hard() -> None:
    words = " ".join(["interpretation"] * 40)
    chunks = chunk_page(words, HEADER, max_chars=120)
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert " ".join(c.removeprefix(HEADER + "\n") for c in chunks) == words

    unbroken = "x" * 250
    chunks = chunk_page(unbroken, HEADER, max_chars=120)
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert "".join(c.removeprefix(HEADER + "\n") for c in chunks) == unbroken


def test_pages_are_chunked_separately_in_order() -> None:
    extraction = extraction_with_pages("First page text", "Second page text", sample_type="URINE")
    assert chunk_report(extraction.pages) == [
        "Sample type: URINE\nFirst page text",
        "Sample type: URINE\nSecond page text",
    ]


def test_the_synthetic_report_gives_one_chunk_per_results_page_without_identity() -> None:
    chunks = chunk_report(synthetic_extraction().pages)

    assert [chunk.splitlines()[0] for chunk in chunks] == [
        "Sample type: URINE",
        "Sample type: URINE",
        "Sample type: SERUM",
    ]
    assert "FERRITIN C.M.I.A 48.3 ng/mL" in chunks[2]
    assert "Method : Fully Automated Chemi Luminescent Microparticle Immunoassay" in chunks[2]
    identity = [
        synthetic_pdf.NAME,
        *synthetic_pdf.NAME.split(),
        synthetic_pdf.REFERRED_BY,
        synthetic_pdf.URINE_BARCODE,
        synthetic_pdf.SERUM_BARCODE,
        synthetic_pdf.PHONE,
        synthetic_pdf.EMAIL,
        *synthetic_pdf.SIGNING_DOCTORS,
    ]
    for value in identity:
        assert all(value.casefold() not in chunk.casefold() for chunk in chunks), value
