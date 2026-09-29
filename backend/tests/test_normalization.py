"""Deterministic normalization: every number the app stores is decided here, not by the LLM."""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.models import CanonicalMetric, Sex
from app.services.normalization import (
    Bounds,
    RangeLine,
    compute_flag,
    convert,
    load_metric_index,
    name_key,
    parse_bounds,
    parse_number,
    select_range,
    unit_key,
)
from tests.structuring_data import seed_metric_index


def D(text: str) -> Decimal:  # noqa: N802 - reads like a literal
    return Decimal(text)


# --- values --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("84.20", D("84.20")),
        (" 12.6 ", D("12.6")),
        ("1,234.5", D("1234.5")),
        ("-2", D("-2")),
        ("0", D("0")),
    ],
)
def test_numbers_parse_exactly(text: str, expected: Decimal) -> None:
    parsed = parse_number(text)

    assert parsed == expected
    assert str(parsed) == str(expected)  # printed precision kept ("84.20", not 84.2)


@pytest.mark.parametrize(
    "text", ["<0.5", ">1000", "Negative", "Trace", "", "12.6 H", "1.2.3", "9" * 19]
)
def test_qualified_or_descriptive_values_are_not_numbers(text: str) -> None:
    assert parse_number(text) is None


# --- reference ranges --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("39 - 259 mg/dl", "39", "259"),
        ("4.63 - 204.00 ng/ml", "4.63", "204.00"),
        ("28 to 217", "28", "217"),
        ("39 \u2013 259", "39", "259"),  # en dash
        ("Less than 30 µg/ml", None, "30"),
        ("< 5.7 %", None, "5.7"),
        ("<= 200", None, "200"),
        ("Upto 40 U/L", None, "40"),
        ("Below 150", None, "150"),
        ("More than 60", "60", None),
        ("> 1.0", "1.0", None),
        ("Above 30 ng/mL", "30", None),
    ],
)
def test_range_text_parses_to_bounds(text: str, low: str | None, high: str | None) -> None:
    expected = Bounds(D(low) if low else None, D(high) if high else None)

    assert parse_bounds(text) == expected


@pytest.mark.parametrize("text", ["Negative", "See note", "", "259 - 39"])
def test_unparseable_ranges_have_no_bounds(text: str) -> None:
    assert parse_bounds(text) is None


MALE_FEMALE = [RangeLine("Male", "39 - 259 mg/dl"), RangeLine("Female", "28 - 217 mg/dl")]
MEN_WOMEN = [RangeLine("Men", "21.81 - 274.66"), RangeLine("Women", "4.63 - 204.00")]
ADULT_SEXES = [RangeLine("Adult Male", "13 - 17"), RangeLine("Adult Female", "12 - 15")]


@pytest.mark.parametrize(
    ("lines", "sex", "label", "low", "high"),
    [
        pytest.param(MALE_FEMALE, "female", "Female", "28", "217", id="female"),
        pytest.param(MALE_FEMALE, "male", "Male", "39", "259", id="male"),
        pytest.param(MEN_WOMEN, "female", "Women", "4.63", "204.00", id="women"),
        pytest.param(MEN_WOMEN, "male", "Men", "21.81", "274.66", id="men"),
        pytest.param(ADULT_SEXES, "female", "Adult Female", "12", "15", id="adult-female"),
        pytest.param(
            [RangeLine("Adults", "Less than 30 µg/ml")], "male", "Adults", None, "30", id="adults"
        ),
        pytest.param([RangeLine(None, "70 - 100")], "female", None, "70", "100", id="unlabelled"),
        pytest.param(
            [RangeLine("Adults", "10 - 20"), RangeLine("Female", "12 - 18")],
            "female",
            "Female",
            "12",
            "18",
            id="sex-beats-general",
        ),
        pytest.param(
            [RangeLine("Adults", "10 - 20"), RangeLine("Female", "12 - 18")],
            "male",
            "Adults",
            "10",
            "20",
            id="general-when-no-sex-line",
        ),
    ],
)
def test_the_range_for_the_patients_sex_is_chosen(
    lines: list[RangeLine], sex: Sex, label: str | None, low: str | None, high: str | None
) -> None:
    chosen = select_range(lines, sex)

    assert chosen is not None
    assert chosen.label == label
    assert chosen.bounds == Bounds(D(low) if low else None, D(high) if high else None)


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param([], id="none-printed"),
        pytest.param([RangeLine("Children", "0.5 - 1.2")], id="subgroup-only"),
        pytest.param(
            [RangeLine("Female 18-40 yrs", "10 - 20"), RangeLine("Female >40 yrs", "12 - 30")],
            id="ambiguous-age-bands",
        ),
        pytest.param([RangeLine("Adults", "See note")], id="unparseable"),
    ],
)
def test_no_range_is_chosen_when_none_fits_unambiguously(lines: list[RangeLine]) -> None:
    assert select_range(lines, "female") is None


# --- flags ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "bounds", "flag"),
    [
        (D("84.20"), Bounds(D("28"), D("217")), "normal"),
        (D("20"), Bounds(D("28"), D("217")), "low"),
        (D("300"), Bounds(D("28"), D("217")), "high"),
        (D("217"), Bounds(D("28"), D("217")), "normal"),  # bounds are inclusive
        (D("12.6"), Bounds(None, D("30")), "normal"),
        (D("31"), Bounds(None, D("30")), "high"),
        (D("5"), Bounds(D("10"), None), "low"),
        (None, Bounds(D("1"), D("2")), "unknown"),
        (D("5"), None, "unknown"),
        (D("5"), Bounds(None, None), "unknown"),
    ],
)
def test_flags(value: Decimal | None, bounds: Bounds | None, flag: str) -> None:
    assert compute_flag(value, bounds) == flag


# --- units ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "key"),
    [
        ("µg/mL", "ug/ml"),  # MICRO SIGN
        ("μg/ml", "ug/ml"),  # GREEK SMALL LETTER MU
        ("µg/mg of Creatinine", "ug/mg"),
        ("X 10³ / µL", "10^3/ul"),
        ("Lakhs/cumm", "10^5/ul"),
        ("mcg/dL", "ug/dl"),
        ("mg/dl", "mg/dl"),
    ],
)
def test_unit_keys(unit: str, key: str) -> None:
    assert unit_key(unit) == key


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        ("84.20", "mg/dl", "mg/dL", "84.20"),
        ("12.6", "µg/mL", "mg/L", "12.6"),
        ("15.0", "µg/mg of Creatinine", "mg/g", "15.0"),
        ("4.5", "g/L", "g/dL", "0.45"),
        ("2.5", "µIU/mL", "mIU/L", "2.5"),
        ("2.5", "Lakhs/cumm", "10^3/uL", "250"),
        ("7.2", "X 10³ / µL", "10^9/L", "7.2"),
        ("140", "mEq/L", "mmol/L", None),  # equivalents vs moles depend on the ion
        ("90", "mg/dL", "mmol/L", None),  # depends on the analyte: never guessed
        ("12", "fL", "pg", None),
        ("1.5", None, "ratio", "1.5"),
        ("1.5", None, "mg/dL", None),
    ],
)
def test_unit_conversion(value: str, source: str | None, target: str, expected: str | None) -> None:
    converted = convert(D(value), source, target)

    assert (str(converted) if converted is not None else None) == expected


# --- names ---------------------------------------------------------------------------------

INDEX = seed_metric_index()


@pytest.mark.parametrize(
    ("raw_name", "sample_type", "canonical"),
    [
        ("CREATININE - URINE", "URINE", "Urine Creatinine"),
        ("CREATININE", "URINE", "Urine Creatinine"),
        ("CREATININE", "SERUM", "Creatinine"),
        ("URINARY MICROALBUMIN", "URINE", "Urine Microalbumin"),
        ("URI. ALBUMIN/CREATININE RATIO (UA/C)", "URINE", "Urine Albumin/Creatinine Ratio"),
        ("FERRITIN", "SERUM", "Ferritin"),
        ("HEMOGLOBIN", None, "Haemoglobin"),
        ("hb", None, "Haemoglobin"),
        ("SGPT", None, "ALT"),
        ("ALT (SGPT)", None, "ALT"),
        ("K", None, "Potassium"),
        ("TSH \u2013 ULTRASENSITIVE", None, "TSH"),
    ],
)
def test_printed_names_map_to_the_dictionary(
    raw_name: str, sample_type: str | None, canonical: str
) -> None:
    entry = INDEX.match(raw_name, sample_type)

    assert entry is not None
    assert entry.canonical_name == canonical


@pytest.mark.parametrize(
    "raw_name", ["IRON BINDING PROTEIN", "HB ELECTROPHORESIS", "VITAMIN K2", "POTASSIUM RATIO"]
)
def test_names_never_match_by_substring(raw_name: str) -> None:
    assert INDEX.match(raw_name) is None


def test_name_keys_ignore_case_spacing_and_dash_style() -> None:
    assert (
        name_key(" Creatinine \u2013 Urine ") == name_key("CREATININE-URINE") == "creatinine-urine"
    )


def test_index_loads_from_the_database(db_session: Session) -> None:
    seed_metric_dictionary(db_session, load_metric_seeds())

    index = load_metric_index(db_session)

    entry = index.match("FERRITIN")
    assert entry is not None
    assert db_session.get_one(CanonicalMetric, entry.id).canonical_name == "Ferritin"
