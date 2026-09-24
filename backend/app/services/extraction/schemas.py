"""Results of extracting a lab-report PDF, and the errors that stop extraction."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Sex


class ExtractionError(Exception):
    """The PDF cannot be turned into report text. The message is safe to show the user and to
    store as a report's `failure_reason`; it never contains identity data."""


class UnreadablePdfError(ExtractionError):
    pass


class NoTextLayerError(ExtractionError):
    pass


class UnsupportedLayoutError(ExtractionError):
    pass


class PiiLeakError(ExtractionError):
    """Identity data survived scrubbing. Extraction fails closed rather than risk sending it."""


class PrintedIdentity(BaseModel):
    """Identity as printed on the report. Used only on our backend: to scrub the text and to
    warn if it does not match the selected family member. Never persisted, never sent to an LLM."""

    model_config = ConfigDict(frozen=True)

    names: tuple[str, ...] = ()
    referred_by: tuple[str, ...] = ()
    barcodes: tuple[str, ...] = ()


class ResultsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_number: int = Field(description="1-based page number in the original PDF")
    sample_type: str | None
    collected_at: datetime | None
    received_at: datetime | None
    released_at: datetime | None
    text: str = Field(description="Scrubbed results region: safe to send to an LLM")


class ExtractedReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    lab_name: str | None
    collected_at: datetime | None = Field(description="Earliest sample collection time")
    printed_age_years: int | None
    printed_sex: Sex | None
    pages: tuple[ResultsPage, ...]
    dropped_pages: tuple[int, ...] = Field(description="Cover, summary and boilerplate pages")
    warnings: tuple[str, ...] = ()
    # Excluded from model_dump()/JSON and from repr, so it cannot leak into storage or logs.
    identity: PrintedIdentity = Field(exclude=True, repr=False)

    def llm_text(self) -> str:
        """The scrubbed results of every page, each labelled with its sample type."""
        return "\n\n".join(
            f"Sample type: {page.sample_type or 'unknown'}\n{page.text}" for page in self.pages
        )
