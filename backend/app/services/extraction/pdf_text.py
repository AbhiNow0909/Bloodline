"""Read the text layer of a PDF, page by page (pdfplumber). No OCR."""

import io
from dataclasses import dataclass

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from app.services.extraction.schemas import NoTextLayerError, UnreadablePdfError

MAX_PAGES = 50  # lab reports are a handful of pages; anything larger is not a report


@dataclass(frozen=True)
class PdfWord:
    text: str
    x0: float  # left edge, in points from the left of the page
    x1: float  # right edge
    top: float  # distance of the top edge from the top of the page


@dataclass(frozen=True)
class PdfPage:
    text: str  # "" for a page without a text layer, such as a picture
    words: tuple[PdfWord, ...]  # where each word is printed: tables are read by position


def read_pages(pdf_bytes: bytes) -> list[PdfPage]:
    """Each page's text and words. Fails if the file is not a readable PDF, or if no page has
    text at all (a scanned report). Whether a page without text may be skipped is decided by
    the caller (`extract_report`)."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise UnreadablePdfError(f"PDF has more than {MAX_PAGES} pages")
            pages = [
                PdfPage(
                    text=page.extract_text() or "",
                    # A small tolerance keeps words apart even where a PDF has no space glyphs.
                    words=tuple(
                        PdfWord(w["text"], w["x0"], w["x1"], w["top"])
                        for w in page.extract_words(x_tolerance=1.5)
                    ),
                )
                for page in pdf.pages
            ]
    except PdfminerException as exc:
        raise UnreadablePdfError("File is not a readable PDF") from exc

    if not pages:
        raise UnreadablePdfError("PDF has no pages")
    if all(not page.text.strip() for page in pages):
        raise NoTextLayerError("scanned/image PDF not supported yet")
    return pages


def read_page_texts(pdf_bytes: bytes) -> list[str]:
    """Each page's text ("" for a page without a text layer); see `read_pages`."""
    return [page.text for page in read_pages(pdf_bytes)]
