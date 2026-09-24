import pytest

from app.services.extraction import NoTextLayerError, UnreadablePdfError
from app.services.extraction.layout import PageKind, classify_page, split_results_page
from app.services.extraction.pdf_text import MAX_PAGES, read_page_texts
from tests.synthetic_pdf import FIXTURE_PATH, build_pdf, lines, synthetic_report


def test_committed_fixture_matches_its_generator() -> None:
    assert FIXTURE_PATH.read_bytes() == synthetic_report(), (
        "fixture is stale: run `uv run python -m tests.synthetic_pdf`"
    )


def test_reads_the_text_of_every_page() -> None:
    texts = read_page_texts(FIXTURE_PATH.read_bytes())

    assert len(texts) == 6
    assert texts[0].startswith("Name : ASHA FICTIONAL(58Y/F)")
    assert "URINARY MICROALBUMIN PHOTOMETRY 12.6 µg/mL" in texts[3]


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"GIF89a not a pdf", id="other-file"),
        pytest.param(synthetic_report()[:200], id="truncated"),
    ],
)
def test_rejects_files_that_are_not_readable_pdfs(data: bytes) -> None:
    with pytest.raises(UnreadablePdfError, match="not a readable PDF"):
        read_page_texts(data)


def test_a_page_without_text_fails_the_whole_report() -> None:
    pdf = build_pdf([lines("TEST NAME TECHNOLOGY VALUE UNITS"), []])

    with pytest.raises(NoTextLayerError, match="scanned/image PDF not supported yet"):
        read_page_texts(pdf)


def test_rejects_implausibly_long_pdfs() -> None:
    pdf = build_pdf([lines("page")] * (MAX_PAGES + 1))

    with pytest.raises(UnreadablePdfError, match=f"more than {MAX_PAGES} pages"):
        read_page_texts(pdf)


def test_classifies_cover_summary_results_and_conditions_pages() -> None:
    kinds = [classify_page(text) for text in read_page_texts(FIXTURE_PATH.read_bytes())]

    assert kinds == [
        PageKind.OTHER,  # cover
        PageKind.OTHER,  # status summary
        PageKind.RESULTS,
        PageKind.RESULTS,
        PageKind.RESULTS,
        PageKind.CONDITIONS,
    ]


def test_split_keeps_only_the_results_region() -> None:
    page = read_page_texts(FIXTURE_PATH.read_bytes())[2]

    parts = split_results_page(page)

    assert parts.header.startswith("Processed At :")
    assert "Patient Name : ASHA FICTIONAL(58Y/F)" in parts.header
    assert parts.results.startswith("TEST NAME TECHNOLOGY VALUE UNITS")
    assert parts.results.endswith("Tests Done : URINARY MICROALBUMIN")
    for footer in ("Report Remarks", "Dr Ravi Placeholder", "Scan QR", "Page 1 of 3"):
        assert footer not in parts.results


def test_results_region_runs_to_the_end_when_there_is_no_footer() -> None:
    parts = split_results_page(
        "Patient Name : X\nTEST NAME TECHNOLOGY VALUE UNITS\nFERRITIN C.M.I.A 48.3 ng/mL"
    )

    assert parts.header == "Patient Name : X"
    assert parts.results == "TEST NAME TECHNOLOGY VALUE UNITS\nFERRITIN C.M.I.A 48.3 ng/mL"
