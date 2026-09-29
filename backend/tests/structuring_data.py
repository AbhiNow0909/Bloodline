"""Shared data for structuring tests. Everything here describes the SYNTHETIC fixture report."""

import uuid
from typing import Any

from app.cli.seed import load_metric_seeds
from app.services.normalization import DictionaryEntry, MetricIndex

# A real gpt-oss-20b reply for the synthetic report (recorded in Phase 6), kept verbatim,
# including its quirk of appending the technology to one test name ("… (UA/C) CALCULATED").
SYNTHETIC_LLM_REPLY: dict[str, Any] = {
    "tests": [
        {
            "raw_name": "CREATININE - URINE",
            "panel": None,
            "technology": "PHOTOMETRY",
            "value": "84.20",
            "unit": "mg/dL",
            "reference_ranges": [
                {"label": "Male", "text": "39 - 259 mg/dl"},
                {"label": "Female", "text": "28 - 217 mg/dl"},
            ],
            "method": "Creatinine Jaffe Method, Rate-Blanked and Compensated",
            "sample_type": "URINE",
        },
        {
            "raw_name": "URINARY MICROALBUMIN",
            "panel": "DIABETES SCREEN (URINE)",
            "technology": "PHOTOMETRY",
            "value": "12.6",
            "unit": "µg/mL",
            "reference_ranges": [{"label": "Adults", "text": "Less than 30 µg/ml"}],
            "method": "Fully Automated Immuno Turbidometry",
            "sample_type": "URINE",
        },
        {
            "raw_name": "URI. ALBUMIN/CREATININE RATIO (UA/C) CALCULATED",
            "panel": "DIABETES SCREEN (URINE)",
            "technology": "CALCULATED",
            "value": "15.0",
            "unit": "µg/mg of Creatinine",
            "reference_ranges": [
                {"label": "Adults", "text": "Less than 30 µg/mg of Creatinine"},
            ],
            "method": "Derived from Albumin and Creatinine values",
            "sample_type": "URINE",
        },
        {
            "raw_name": "FERRITIN",
            "panel": None,
            "technology": "C.M.I.A",
            "value": "48.3",
            "unit": "ng/mL",
            "reference_ranges": [
                {"label": "Men", "text": "21.81 - 274.66 ng/ml"},
                {"label": "Women", "text": "4.63 - 204.00 ng/ml"},
            ],
            "method": "Fully Automated Chemi Luminescent Microparticle Immunoassay",
            "sample_type": "SERUM",
        },
    ]
}


def seed_metric_index() -> MetricIndex:
    """The real metric dictionary (from the seed file) without a database."""
    return MetricIndex(
        (DictionaryEntry(uuid.uuid4(), seed.canonical_name, seed.canonical_unit), seed.aliases)
        for seed in load_metric_seeds()
    )
