"""The scrubber is the last line of defence before text reaches an LLM (Principle 2)."""

import pytest

from app.services.extraction import PrintedIdentity
from app.services.extraction.pii import find_leaks, scrub_text

IDENTITY = PrintedIdentity(
    names=("ASHA FICTIONAL",),
    referred_by=("DR SUNIL NOTREAL",),
    barcodes=("ZZ123456",),
)

SCRUBBED = [
    pytest.param("Call 9876543210 today", "Call [PHONE] today", id="phone"),
    pytest.param("Call +91 9876543210", "Call [PHONE]", id="phone-with-country-code"),
    pytest.param("Call 98765 43210", "Call [PHONE]", id="phone-grouped"),
    pytest.param("write to asha.f@example.test", "write to [EMAIL]", id="email"),
    pytest.param("Barcode ZZ123456 received", "Barcode [BARCODE] received", id="barcode"),
    pytest.param("Sample of ASHA FICTIONAL", "Sample of [NAME]", id="name"),
    pytest.param("Sample of Asha  Fictional", "Sample of [NAME]", id="name-other-case"),
    pytest.param("Patient: FICTIONAL, ASHA", "Patient: [NAME], [NAME]", id="name-reordered"),
    pytest.param("referred by DR SUNIL NOTREAL", "referred by [DOCTOR]", id="referrer"),
    pytest.param("referred by SUNIL", "referred by [DOCTOR]", id="referrer-part"),
    pytest.param(
        "Dr Ravi Placeholder Dr Neha Madeup Scan QR",
        "[DOCTOR] [DOCTOR] QR",
        id="signing-doctors",
    ),
    pytest.param("verified by DR. K. SHARMA", "verified by [DOCTOR] ", id="doctor-with-initial"),
]


@pytest.mark.parametrize(("text", "expected"), SCRUBBED)
def test_scrubs_identity(text: str, expected: str) -> None:
    scrubbed = scrub_text(text, IDENTITY)

    assert scrubbed == expected
    assert find_leaks(scrubbed, IDENTITY) == []


@pytest.mark.parametrize(
    "text",
    [
        "CREATININE - URINE PHOTOMETRY 84.20 mg/dL",
        "Male: 39 - 259 mg/dl",
        "Adults: Less than 30 µg/ml",
        "URI. ALBUMIN/CREATININE RATIO (UA/C) CALCULATED 15.0 µg/mg of Creatinine",
        "PLATELET COUNT IMPEDANCE 250000 /uL",
        "POTASSIUM K 4.5 mmol/L",
        "Drug levels may interfere with the assay",
        "Method : Fully Automated Chemi Luminescent Microparticle Immunoassay",
    ],
)
def test_leaves_results_untouched(text: str) -> None:
    assert scrub_text(text, IDENTITY) == text


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("call 9876543210", "phone"),
        ("mail a@example.test", "email"),
        ("ZZ123456", "barcode"),
        ("Asha", "name"),
        ("notreal", "referring doctor"),
    ],
)
def test_find_leaks_reports_kinds_not_values(text: str, kind: str) -> None:
    assert find_leaks(text, IDENTITY) == [kind]


def test_self_referral_and_initials_are_not_treated_as_names() -> None:
    identity = PrintedIdentity(names=("A K",), referred_by=("SELF",))

    assert scrub_text("SELF K 4.5 mmol/L", identity) == "SELF K 4.5 mmol/L"


def test_short_name_parts_are_scrubbed_as_part_of_the_full_name() -> None:
    identity = PrintedIdentity(names=("MEI LI",))

    assert scrub_text("Sample of Mei Li received", identity) == "Sample of [NAME] received"
    # Alone, a two-letter part is left: it could be a unit or a symbol.
    assert scrub_text("LI 1.2 mmol/L", identity) == "LI 1.2 mmol/L"
