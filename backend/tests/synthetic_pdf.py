"""Deterministic synthetic lab-report PDFs for tests. Every name, id and value is made up.

`synthetic_report()` mimics the layout of a Thyrocare report (issued via Healthcare OnTime):
a cover page, a status summary, results pages whose header prints two columns side by side,
sex-specific and "Less than" reference ranges, µg units, and a Conditions of Reporting page.

Regenerate the committed fixture after changing this file:

    uv run python -m tests.synthetic_pdf
"""

from collections.abc import Sequence
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_thyrocare_report.pdf"

# (x, y, text, font size); y is measured from the bottom of an A4 page, as in PDF.
TextRun = tuple[float, float, str, float]

PAGE_WIDTH, PAGE_HEIGHT = 595, 842
LEFT, RIGHT = 36.0, 320.0
TOP, LINE = 800.0, 14.0

# The synthetic patient. Tests assert that none of these survive scrubbing.
NAME = "ASHA FICTIONAL"
AGE_SEX = "(58Y/F)"
REFERRED_BY = "DR SUNIL NOTREAL"
URINE_BARCODE = "ZZ123456"
SERUM_BARCODE = "ZZ654321"
PHONE = "9876543210"
EMAIL = "asha.fictional@example.test"
ADDRESS_LINE_1 = "Flat 12 Imaginary Lane, , , 400000,Fakenagar Testpur,4"
ADDRESS_LINE_2 = "Block,XYZ Colony,FAKESTATE - 01, , Testpur, Testpur, INDIA,"
SIGNING_DOCTORS = ("Dr Ravi Placeholder", "Dr Neha Madeup")
LAB_ADDRESS = ("12th Floor, 404 SYN Tower Testpur-4", "(HO), No 1234, Fakenagar")


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")  # WinAnsiEncoding: covers µ (0xB5) and • (0x95)
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(pages: Sequence[Sequence[TextRun]]) -> bytes:
    """A minimal text-only PDF (Helvetica). No timestamps, so the output is reproducible."""
    count = len(pages)
    page_ids = [4 + 2 * i for i in range(count)]
    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, count),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, runs in zip(page_ids, pages, strict=True):
        stream = b"".join(
            b"BT /F1 %.1f Tf %.2f %.2f Td (%s) Tj ET\n" % (size, x, y, _escape(text))
            for x, y, text, size in runs
        )
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, page_id + 1)
        )
        objects[page_id + 1] = b"<< /Length %d >>\nstream\n%sendstream" % (len(stream), stream)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (number, objects[number])
    xref_at = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    out += b"".join(b"%010d 00000 n \n" % offsets[number] for number in range(1, size))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    return bytes(out)


def lines(*rows: str | tuple[str, str], size: float = 9) -> list[TextRun]:
    """Lay rows out top-down. A tuple row prints a left and a right column on the same line."""
    runs: list[TextRun] = []
    for i, row in enumerate(rows):
        y = TOP - i * LINE
        left, right = row if isinstance(row, tuple) else (row, "")
        if left:
            runs.append((LEFT, y, left, size))
        if right:
            runs.append((RIGHT, y, right, size))
    return runs


def results_header(sample_type: str, barcode: str, name: str = NAME) -> list[str | tuple[str, str]]:
    return [
        "Processed At :",
        LAB_ADDRESS[0],
        LAB_ADDRESS[1],
        (f"Patient Name : {name}{AGE_SEX}", "Sample Collected on (SCT): 03 Mar 2025 08:15"),
        (f"Referred By : {REFERRED_BY}", "Sample Received on (SRT) : 03 Mar 2025 13:40"),
        (f"Address : {ADDRESS_LINE_1}", "Report Released on (RRT) : 04 Mar 2025 10:05"),
        (ADDRESS_LINE_2, f"Sample Type | Barcode : {sample_type} | {barcode}"),
        "400000",
        "TEST NAME TECHNOLOGY VALUE UNITS",
    ]


def results_footer(page: int, total: int) -> list[str]:
    return [
        "Report Remarks : Sample Tested by: Thyrocare Technologies Ltd-Synthetic Lab",
        f"accreditation, NABL accreditation no: MC-0000 {SIGNING_DOCTORS[0]} "
        f"{SIGNING_DOCTORS[1]} Scan QR to verify(valid for",
        "30 days from release time)",
        "MD(Path) MD(Path)",
        f"Page {page} of {total}",
    ]


def cover_page() -> list[TextRun]:
    return lines(
        f"Name : {NAME}{AGE_SEX}",
        "Date : 3 Mar, 2025",
        "Test Asked : Kidney Check, Iron Check",
        "Report Availability : Complete Report",
        size=12,
    )


def summary_page() -> list[TextRun]:
    return lines(
        "Processed At :",
        LAB_ADDRESS[0],
        LAB_ADDRESS[1],
        (f"Patient Name : {NAME}{AGE_SEX}", "Tests Asked : KIDNEY,IRON"),
        f"Referred By :{REFERRED_BY}",
        f"Address : {ADDRESS_LINE_1}",
        ADDRESS_LINE_2 + " 400000",
        "Report Availability Summary",
        "Note: Please refer to the detailed report for results of each test.",
        "1 Sample 2 Tests Collected 3 Processing 4 Completed at Lab",
        "TEST PROFILE REPORT STATUS",
        "URINARY MICROALBUMIN Ready",
        "FERRITIN Ready",
        "Page: 1 of 1",
    )


def creatinine_page() -> list[TextRun]:
    return lines(
        *results_header("URINE", URINE_BARCODE),
        "CREATININE - URINE PHOTOMETRY 84.20 mg/dL",
        "Bio. Ref. Interval. :",
        "Male: 39 - 259 mg/dl",
        "Female: 28 - 217 mg/dl",
        "Method : Creatinine Jaffe Method, Rate-Blanked and Compensated",
        "Please correlate with clinical conditions.",
        "Tests Done : URINARY MICROALBUMIN",
        *results_footer(1, 3),
    )


def microalbumin_page() -> list[TextRun]:
    return lines(
        *results_header("URINE", URINE_BARCODE),
        "DIABETES SCREEN (URINE)",
        "URINARY MICROALBUMIN PHOTOMETRY 12.6 µg/mL",
        "Bio. Ref. Interval. :",
        "Adults: Less than 30 µg/ml",
        "Method : Fully Automated Immuno Turbidometry",
        "URI. ALBUMIN/CREATININE RATIO (UA/C) CALCULATED 15.0 µg/mg of Creatinine",
        "Bio. Ref. Interval. :",
        "Adults : Less than 30 µg/mg of Creatinine",
        "Method : Derived from Albumin and Creatinine values",
        f"Sample of {NAME.title()} received in good condition.",
        f"For queries call {PHONE} or write to {EMAIL}",
        "Please correlate with clinical conditions.",
        "Tests Done : URINARY MICROALBUMIN",
        *results_footer(2, 3),
    )


def ferritin_page() -> list[TextRun]:
    return lines(
        *results_header("SERUM", SERUM_BARCODE),
        "FERRITIN C.M.I.A 48.3 ng/mL",
        "Bio. Ref. Interval. :",
        "Men: 21.81 - 274.66 ng/ml",
        "Women: 4.63 - 204.00 ng/ml",
        "Method : Fully Automated Chemi Luminescent Microparticle Immunoassay",
        "Please correlate with clinical conditions.",
        "Tests Done : FERRITIN",
        *results_footer(3, 3),
    )


def conditions_page() -> list[TextRun]:
    return lines(
        "CONDITIONS OF REPORTING",
        "• The reported results are for information and interpretation of the referring doctor.",
        "• It is presumed that the tests performed are on the specimen belonging to the patient.",
        "• For queries write to care@example.test",
        size=8,
    )


def synthetic_report() -> bytes:
    return build_pdf(
        [
            cover_page(),
            summary_page(),
            creatinine_page(),
            microalbumin_page(),
            ferritin_page(),
            conditions_page(),
        ]
    )


if __name__ == "__main__":
    FIXTURE_PATH.write_bytes(synthetic_report())
    print(f"wrote {FIXTURE_PATH} ({FIXTURE_PATH.stat().st_size} bytes)")
