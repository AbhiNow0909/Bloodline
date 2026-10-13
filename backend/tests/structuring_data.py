"""Shared data for structuring tests. Everything here describes the SYNTHETIC fixture report."""

import json
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


# A real gpt-oss-20b reply for the synthetic MediBuddy-style report
# (`tests/synthetic_medibuddy.py`), kept verbatim: the model carries a panel heading over to the
# next section's tests and keeps the accreditation mark ("*") in names.
SYNTHETIC_MEDIBUDDY_LLM_REPLY: dict[str, Any] = {
    "tests": [
        {
            "raw_name": "Protein Total",
            "panel": "Liver Function Profile",
            "technology": None,
            "value": "7.2",
            "unit": "g/dL",
            "reference_ranges": [{"label": None, "text": "6.4 - 8.3"}],
            "method": "Biuret",
            "sample_type": "SERUM",
        },
        {
            "raw_name": "Bilirubin Direct",
            "panel": "Liver Function Profile",
            "technology": None,
            "value": "0.21",
            "unit": "mg/dL",
            "reference_ranges": [{"label": None, "text": "Upto 0.25"}],
            "method": "Diazo method",
            "sample_type": "SERUM",
        },
        {
            "raw_name": "Aspartate Aminotransferase(AST/SGOT)",
            "panel": "Liver Function Profile",
            "technology": None,
            "value": "46",
            "unit": "U/L",
            "reference_ranges": [{"label": None, "text": "Upto 40"}],
            "method": "IFCC without P5P",
            "sample_type": "SERUM",
        },
        {
            "raw_name": "Vitamin - B12*",
            "panel": "Liver Function Profile",
            "technology": None,
            "value": "345",
            "unit": "pg/mL",
            "reference_ranges": [{"label": None, "text": "211 - 911"}],
            "method": "CLIA",
            "sample_type": "SERUM",
        },
        {
            "raw_name": "Hemoglobin (Hb)*",
            "panel": "Complete Blood Count (CBC)",
            "technology": None,
            "value": "13.9",
            "unit": "g/dL",
            "reference_ranges": [{"label": None, "text": "13.0 - 17.0"}],
            "method": "Photometry",
            "sample_type": "WB EDTA",
        },
        {
            "raw_name": "RBC Count",
            "panel": "Complete Blood Count (CBC)",
            "technology": None,
            "value": "4.82",
            "unit": "mil/µL",
            "reference_ranges": [{"label": None, "text": "4.5 - 5.5"}],
            "method": "Electrical impedance",
            "sample_type": "WB EDTA",
        },
        {
            "raw_name": "Total Leucocyte Count (WBC)",
            "panel": "Complete Blood Count (CBC)",
            "technology": None,
            "value": "6500",
            "unit": "cells/Cumm",
            "reference_ranges": [{"label": None, "text": "4000 - 10000"}],
            "method": None,
            "sample_type": "WB EDTA",
        },
        {
            "raw_name": "Absolute Neutrophil Count",
            "panel": "Complete Blood Count (CBC)",
            "technology": None,
            "value": "3.90",
            "unit": "* 10^9/L",
            "reference_ranges": [{"label": None, "text": "2.0 - 7.0"}],
            "method": "Calculated",
            "sample_type": "WB EDTA",
        },
        {
            "raw_name": "RBC Morphology",
            "panel": "Complete Blood Count (CBC)",
            "technology": None,
            "value": "Normocytic Normochromic",
            "unit": None,
            "reference_ranges": [],
            "method": None,
            "sample_type": "WB EDTA",
        },
    ]
}


def seed_metric_index() -> MetricIndex:
    """The real metric dictionary (from the seed file) without a database."""
    return MetricIndex(
        (DictionaryEntry(uuid.uuid4(), seed.canonical_name, seed.canonical_unit), seed.aliases)
        for seed in load_metric_seeds()
    )


class FakeChatClient:
    """Stands in for the Groq client at the `ChatClient` boundary: replies with `reply`
    (or raises it, if it is an exception) and records every call."""

    def __init__(self, reply: dict[str, Any] | str | Exception = SYNTHETIC_LLM_REPLY) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
