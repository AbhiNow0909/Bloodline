"""What the structuring LLM returns (strings copied verbatim) and what we derive from it."""

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import MetricFlag


class StructuringError(Exception):
    """The report could not be structured. The message is safe to show the user."""


# --- LLM output: every string copied from the report; no numbers are interpreted here ------


# Optional fields default to None: the model sometimes leaves out a field it would set to
# null (seen with `panel` on parts of a report without headings). Groq then rejects the reply,
# and the client hands back that reply for these models to check instead (see
# `GroqChatClient.complete_json`). Anything else wrong with it still fails validation here.
class LlmRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    text: str


class LlmTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_name: str
    panel: str | None = None
    technology: str | None = None
    value: str
    unit: str | None = None
    reference_ranges: list[LlmRange]
    method: str | None = None
    sample_type: str | None = None


class LlmReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tests: list[LlmTest]


def _nullable_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


# Written out by hand for Groq strict mode: every property required, no extra properties,
# optional values as ["string", "null"]. tests/test_structuring.py keeps it in sync with
# the models above.
LLM_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_name": {"type": "string", "description": "Test name as printed"},
                    "panel": _nullable_string("Heading the test is printed under, if any"),
                    "technology": _nullable_string("Technology column, e.g. PHOTOMETRY"),
                    "value": {"type": "string", "description": "Result exactly as printed"},
                    "unit": _nullable_string("Unit exactly as printed"),
                    "reference_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": _nullable_string("Text before the colon, e.g. Male"),
                                "text": {
                                    "type": "string",
                                    "description": "Rest of the range line exactly as printed",
                                },
                            },
                            "required": ["label", "text"],
                            "additionalProperties": False,
                        },
                    },
                    "method": _nullable_string("Text after 'Method :' for this test"),
                    "sample_type": _nullable_string("From the preceding 'Sample type:' line"),
                },
                "required": [
                    "raw_name",
                    "panel",
                    "technology",
                    "value",
                    "unit",
                    "reference_ranges",
                    "method",
                    "sample_type",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tests"],
    "additionalProperties": False,
}


# --- Our result: one reviewable row per test, numbers derived deterministically ------------


class StructuredMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_name: str
    panel: str | None
    technology: str | None
    method: str | None
    sample_type: str | None
    value_text: str  # as printed
    value_numeric: Decimal | None  # parsed from value_text; None for "Negative", "<0.5", ...
    unit: str | None  # as printed
    canonical_metric_id: uuid.UUID | None
    canonical_name: str | None
    value_canonical: Decimal | None
    unit_canonical: str | None
    reference_text: str | None  # every printed range line, e.g. "Male: 39 - 259 mg/dl"
    reference_low: Decimal | None  # of the range chosen for the patient's sex
    reference_high: Decimal | None
    reference_label: str | None  # which printed line was chosen, e.g. "Female"
    flag: MetricFlag
    warnings: tuple[str, ...] = ()


class StructuredReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    metrics: tuple[StructuredMetric, ...]
    warnings: tuple[str, ...] = ()
