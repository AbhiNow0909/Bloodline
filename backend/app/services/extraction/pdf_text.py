"""Read the text layer of a PDF, page by page (pdfplumber). No OCR."""

import io

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from app.services.extraction.schemas import NoTextLayerError, UnreadablePdfError

MAX_PAGES = 50  # lab reports are a handful of pages; anything larger is not a report


def read_page_texts(pdf_bytes: bytes) -> list[str]:
    """Return each page's text. Fails if the file is not a readable PDF, or if any page has no
    text layer: a scanned page could hide results, so it is never silently skipped."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise UnreadablePdfError(f"PDF has more than {MAX_PAGES} pages")
            texts = [page.extract_text() or "" for page in pdf.pages]
    except PdfminerException as exc:
        raise UnreadablePdfError("File is not a readable PDF") from exc

    if not texts:
        raise UnreadablePdfError("PDF has no pages")
    if any(not text.strip() for text in texts):
        raise NoTextLayerError("scanned/image PDF not supported yet")
    return texts
