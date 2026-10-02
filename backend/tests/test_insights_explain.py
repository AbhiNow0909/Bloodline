"""Members' findings from saved results, and their explanations with a scripted model."""

import json
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.schemas.history import Insight
from app.services.agent import ChatScope, PrivacyGuardError
from app.services.agent.prompt import NO_DIAGNOSIS_RULE, NO_TREATMENT_RULE
from app.services.insights import (
    MAX_EXPLAINED,
    SYSTEM_PROMPT,
    ExplanationError,
    explain_insights,
    member_insights,
)
from app.services.insights.explain import (
    EXPLANATION_SCHEMA,
    NO_NUMBERS_RULE,
    _LlmExplanation,
    _LlmReply,
    facts_message,
    numbers_in,
)
from tests.agent_helpers import rao_family, reading, report_on
from tests.structuring_data import FakeChatClient


@pytest.fixture
def family(db_session: Session) -> dict[str, Any]:
    return rao_family(db_session)


def explain(
    insights: list[Insight], reply: Any, scope: ChatScope
) -> tuple[list[Any], FakeChatClient]:
    client = FakeChatClient(reply)
    return explain_insights(client, "test-model", scope, insights), client


def reply(*items: tuple[str, str]) -> dict[str, Any]:
    return {"explanations": [{"id": fact_id, "text": text} for fact_id, text in items]}


# --- findings from the database ---------------------------------------------------------------


def test_member_insights_read_only_the_members_asked_for(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma, appa, stranger = family["amma"], family["appa"], family["stranger"]

    found = member_insights(db_session, [amma.id, appa.id])

    assert set(found) == {amma.id, appa.id}
    # Amma: ferritin fell below the range; haemoglobin changed 6 % (no alert); urine glucose is
    # not in the dictionary (left out).
    (ferritin,) = found[amma.id]
    assert (ferritin.kind, ferritin.metric.canonical_name) == ("outside_range", "Ferritin")
    assert ferritin.change == Decimal("-51.9")
    (ldl,) = found[appa.id]
    assert (ldl.kind, ldl.metric.canonical_name, ldl.compared_with) == (
        "outside_range",
        "LDL Cholesterol",
        None,
    )
    assert all(i.patient_id != stranger.id for items in found.values() for i in items)
    assert member_insights(db_session, []) == {}
    assert member_insights(db_session, [stranger.id])[stranger.id][0].patient_id == stranger.id


def test_findings_are_ordered_by_importance(db_session: Session, family: dict[str, Any]) -> None:
    amma = family["amma"]
    newest = report_on(db_session, amma, "2025-09-05")
    reading(db_session, newest, "Ferritin", "7.0", "ng/mL", "13", "150", "low")  # still low
    reading(db_session, newest, "Haemoglobin", "16.1", "g/dL", "12.0", "15.0", "high")  # newly
    older = report_on(db_session, amma, "2023-01-01")
    reading(db_session, older, "LDL Cholesterol", "160", "mg/dL", None, "100", "high")
    reading(db_session, newest, "LDL Cholesterol", "90", "mg/dL", None, "100", "normal")  # back
    reading(db_session, older, "HbA1c", "4.0", "%", None, "5.7", "normal")
    reading(db_session, newest, "HbA1c", "5.5", "%", None, "5.7", "normal")  # +37.5 %

    found = member_insights(db_session, [amma.id])[amma.id]

    assert [(i.metric.canonical_name, i.kind) for i in found] == [
        ("Haemoglobin", "outside_range"),
        ("Ferritin", "outside_range"),
        ("HbA1c", "big_change"),
        ("LDL Cholesterol", "back_in_range"),
    ]
    assert found[1].outside_in_a_row == 2


# --- what the model is given ------------------------------------------------------------------


def test_the_model_gets_facts_only(db_session: Session, family: dict[str, Any]) -> None:
    found = member_insights(db_session, [family["amma"].id])[family["amma"].id]

    message, by_id = facts_message(found)

    assert by_id == {"1": found[0]}
    (fact,) = json.loads(message)["findings"]
    assert fact == {
        "id": "1",
        "test": "Ferritin",
        "category": found[0].metric.category,
        "what_the_test_measures": found[0].metric.description,
        "finding": "now below the lab's range; the previous result was within it",
        "latest_result": "8.2 ng/mL",
        "lab_range": "13 to 150 ng/mL",
        "earlier_result": "60.1 ng/mL",
        "change": "-51.9 ng/mL (-86.4%)",
    }
    assert "Amma" not in message
    # No report dates either.
    assert "2025" not in message
    assert "2024" not in message


# Results added to the stranger's (one ferritin result, low): (day, test, value, low, high, flag)
SETUPS: dict[str, list[tuple[str, str, str, str | None, str, str]]] = {
    "first": [],
    "still": [("2025-06-01", "Ferritin", "6.0", "13", "150", "low")],
    "back": [("2025-06-01", "Ferritin", "20.0", "13", "150", "normal")],
    "change": [
        ("2025-03-01", "HbA1c", "4.0", None, "6.0", "normal"),
        ("2025-06-01", "HbA1c", "6.0", None, "6.0", "normal"),
    ],
}
UNITS = {"Ferritin": "ng/mL", "HbA1c": "%"}


@pytest.mark.parametrize(
    ("setup", "finding"),
    [
        ("first", "below the lab's range (the only result so far)"),
        ("still", "below the lab's range in each of the last 2 results"),
        ("back", "back within the lab's range; the previous result was below it"),
        ("change", "rose by 50.0% across the last 2 results, and is still within the lab's range"),
    ],
)
def test_each_kind_of_finding_is_worded_for_the_model(
    db_session: Session, family: dict[str, Any], setup: str, finding: str
) -> None:
    stranger = family["stranger"]
    for day, test, value, low, high, flag in SETUPS[setup]:
        report = report_on(db_session, stranger, day)
        reading(db_session, report, test, value, UNITS[test], low, high, flag)
    test_name = "HbA1c" if setup == "change" else "Ferritin"
    found = member_insights(db_session, [stranger.id])[stranger.id]
    insight = next(i for i in found if i.metric.canonical_name == test_name)

    message, _ = facts_message([insight])

    assert json.loads(message)["findings"][0]["finding"] == finding


def test_ranges_are_worded_for_open_ends(db_session: Session, family: dict[str, Any]) -> None:
    (ldl,) = member_insights(db_session, [family["appa"].id])[family["appa"].id]
    message, _ = facts_message([ldl])
    assert json.loads(message)["findings"][0]["lab_range"] == "up to 100 mg/dL"


# --- explaining -------------------------------------------------------------------------------


def test_explanations_come_back_for_each_finding(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    found = member_insights(db_session, [amma.id])[amma.id]
    text = "Ferritin  reflects iron stores.\nThis result is lower than the lab's usual range."

    explanations, client = explain(found, reply(("1", text)), ChatScope.for_member(amma))

    assert [(e.metric_id, e.kind, e.text) for e in explanations] == [
        (
            found[0].metric.id,
            "outside_range",
            "Ferritin reflects iron stores. This result is lower than the lab's usual range.",
        )
    ]
    (call,) = client.calls
    assert call["model"] == "test-model"
    assert call["system"] == SYSTEM_PROMPT
    assert call["schema_name"] == "insight_explanations"
    assert call["schema"] == EXPLANATION_SCHEMA
    for rule in (NO_DIAGNOSIS_RULE, NO_TREATMENT_RULE, NO_NUMBERS_RULE):
        assert rule in call["system"]
    assert "Amma" not in json.dumps(call)


def test_an_explanation_with_a_number_not_given_is_dropped(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    newest = report_on(db_session, amma, "2025-09-05")
    reading(db_session, newest, "Vitamin B12", "150", "pg/mL", "197", "771", "low")
    found = member_insights(db_session, [amma.id])[amma.id]
    ids = {i.metric.canonical_name: str(n) for n, i in enumerate(found, start=1)}

    explanations, _ = explain(
        found,
        reply(
            (ids["Ferritin"], "Ferritin fell by 86.4% to 8.2, below the range of 13 to 150."),
            (ids["Vitamin B12"], "Vitamin B12 below 200 can matter."),  # 200: not a given number
        ),
        ChatScope.for_member(amma),
    )

    # Numbers given in the facts (and the 12 in "B12", part of the name) are allowed.
    assert [e.text for e in explanations] == [
        "Ferritin fell by 86.4% to 8.2, below the range of 13 to 150."
    ]


def test_unknown_duplicate_empty_and_overlong_explanations_are_ignored(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    found = member_insights(db_session, [amma.id])[amma.id]

    explanations, _ = explain(
        found,
        reply(("7", "Not a finding."), ("1", "  "), ("1", "First."), ("1", "Second.")),
        ChatScope.for_member(amma),
    )
    assert [e.text for e in explanations] == ["First."]

    explanations, _ = explain(found, reply(("1", "word " * 200)), ChatScope.for_member(amma))
    assert explanations == []


def test_a_reply_in_the_wrong_shape_is_an_error(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    found = member_insights(db_session, [amma.id])[amma.id]
    bad_replies: list[Any] = ["not json", {"explanations": [{"id": "1"}]}, {"items": []}]
    for bad in bad_replies:
        with pytest.raises(ExplanationError, match="unexpected shape"):
            explain(found, bad, ChatScope.for_member(amma))


def test_nothing_is_sent_without_findings(family: dict[str, Any]) -> None:
    explanations, client = explain([], reply(), ChatScope.for_member(family["amma"]))
    assert explanations == []
    assert client.calls == []


def test_at_most_max_explained_findings_are_sent(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    (ferritin,) = member_insights(db_session, [amma.id])[amma.id]
    many = [ferritin.model_copy() for _ in range(MAX_EXPLAINED + 5)]

    _, client = explain(many, reply(), ChatScope.for_member(amma))

    assert len(json.loads(client.calls[0]["user"])["findings"]) == MAX_EXPLAINED


def test_a_member_name_in_the_facts_stops_the_request(
    db_session: Session, family: dict[str, Any]
) -> None:
    amma = family["amma"]
    amma.display_name = "Ferritin"  # a name that is also a test's name
    found = member_insights(db_session, [amma.id])[amma.id]

    with pytest.raises(PrivacyGuardError):
        explain(found, reply(), ChatScope.for_member(amma))


def test_numbers_in_text() -> None:
    assert numbers_in("Ferritin 8.20, B12 and HbA1c; 1,200 or 93.6% (25)") == {
        Decimal("8.2"),
        Decimal("1200"),
        Decimal("93.6"),
        Decimal("25"),
    }


def test_the_reply_schema_is_strict_and_matches_the_models() -> None:
    item = EXPLANATION_SCHEMA["properties"]["explanations"]["items"]
    for schema, model in ((EXPLANATION_SCHEMA, _LlmReply), (item, _LlmExplanation)):
        assert set(schema["properties"]) == set(model.model_fields)
        assert schema["required"] == list(schema["properties"])
        assert schema["additionalProperties"] is False
