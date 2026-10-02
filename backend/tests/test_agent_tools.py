"""The agent's tools, on real Postgres: results, scope, and what they never reveal."""

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models import Patient
from app.services.agent import ChatScope, ToolContext
from app.services.embeddings import index_report
from tests.agent_helpers import rao_family
from tests.embedding_helpers import FakeEmbedder, add_confirmed_report

TODAY = date(2026, 9, 30)


@pytest.fixture
def family(db_session: Session) -> dict[str, Any]:
    return rao_family(db_session)


def family_tools(session: Session, *members: Patient) -> ToolContext:
    return ToolContext(session, FakeEmbedder(), ChatScope.for_family("Rao family", members), TODAY)


def run(tools: ToolContext, name: str, **arguments: Any) -> Any:
    return json.loads(tools.run(name, json.dumps(arguments)))


def test_tool_specs_offer_member_labels_only_in_family_chats(
    db_session: Session, family: dict[str, Any]
) -> None:
    member = ToolContext(db_session, FakeEmbedder(), ChatScope.for_member(family["amma"]), TODAY)
    assert all("member" not in s["function"]["parameters"]["properties"] for s in member.specs())

    specs = family_tools(db_session, family["amma"], family["appa"]).specs()
    assert [s["function"]["name"] for s in specs] == [
        "list_available_metrics",
        "get_metric_history",
        "get_latest_values",
        "get_out_of_range",
        "compare_reports",
        "get_trend_summary",
        "search_report_text",
    ]
    for spec in specs:
        member_arg = spec["function"]["parameters"]["properties"]["member"]
        assert member_arg["enum"] == ["Member A", "Member B", None]
    assert "Amma" not in json.dumps(specs)


def test_optional_arguments_accept_null(db_session: Session, family: dict[str, Any]) -> None:
    # gpt-oss sends null for optional arguments it does not use; Groq rejects the whole
    # request when the schema does not allow null, so every optional argument must.
    for spec in family_tools(db_session, family["amma"], family["appa"]).specs():
        parameters = spec["function"]["parameters"]
        for name, prop in parameters["properties"].items():
            if name not in parameters["required"]:
                assert "null" in prop["type"], (spec["function"]["name"], name)
                assert "enum" not in prop or None in prop["enum"]
            else:
                assert prop["type"] != "null"

    tools = family_tools(db_session, family["amma"], family["appa"])
    assert run(tools, "compare_reports", member="Member A", report_a=None, report_b=None) == run(
        tools, "compare_reports", member="Member A"
    )
    assert run(tools, "get_out_of_range", member=None, since=None, include_earlier=None) == run(
        tools, "get_out_of_range"
    )
    assert run(tools, "get_latest_values", metrics=None) == run(tools, "get_latest_values")
    assert "error" not in run(tools, "search_report_text", query="ferritin method", k=None)


def test_list_available_metrics(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    result = run(tools, "list_available_metrics", member="Member A")

    [amma] = result["members"]
    assert amma["member"] == "Member A"
    assert amma["reports"] == [
        {"date": "3 Mar 2025", "date_iso": "2025-03-03", "lab": "Other Labs", "values": 3},
        {"date": "3 Mar 2024", "date_iso": "2024-03-03", "lab": "Example Labs", "values": 2},
    ]
    assert {(t["test"], t["results"]) for t in amma["tests"]} == {
        ("Ferritin", 2),
        ("Haemoglobin", 2),
        ("URINE GLUCOSE", 1),
    }


def test_metric_history_by_name_or_alias(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"])
    result = run(tools, "get_metric_history", metric="hb")  # an alias of Haemoglobin

    assert result["test"] == "Haemoglobin"
    assert result["standard_unit"] == "g/dL"
    assert result["members"][0]["results_oldest_first"] == [
        {
            "date": "3 Mar 2024",
            "value": "12.9 g/dL",
            "lab_range": "12.0 to 15.0 g/dL",
            "flag": "normal",
        },
        {
            "date": "3 Mar 2025",
            "value": "12.1 g/dL",
            "lab_range": "12.0 to 15.0 g/dL",
            "flag": "normal",
        },
    ]
    dated = run(tools, "get_metric_history", metric="Ferritin", start_date="2025-01-01")
    assert [r["date"] for r in dated["members"][0]["results_oldest_first"]] == ["3 Mar 2025"]


def test_an_unknown_test_lists_what_exists(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"])
    result = run(tools, "get_metric_history", metric="cholestrol")
    assert result["error"] == (
        "No test called 'cholestrol' in these results. Tests with results: "
        "Ferritin, Haemoglobin, URINE GLUCOSE."
    )


def test_latest_values_for_everyone_or_some_tests(
    db_session: Session, family: dict[str, Any]
) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    result = run(tools, "get_latest_values", metrics=["ferritin", "LDL"])

    assert result == {
        "members": [
            {
                "member": "Member A",
                "latest_values": [
                    {
                        "test": "Ferritin",
                        "date": "3 Mar 2025",
                        "value": "8.2 ng/mL",
                        "lab_range": "13 to 150 ng/mL",
                        "flag": "low",
                    }
                ],
            },
            {
                "member": "Member B",
                "latest_values": [
                    {
                        "test": "LDL Cholesterol",
                        "date": "1 Jun 2025",
                        "value": "142 mg/dL",
                        "lab_range": "up to 100 mg/dL",
                        "flag": "high",
                    }
                ],
            },
        ]
    }


def test_out_of_range_now_or_ever(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    now = run(tools, "get_out_of_range")
    assert [(m["member"], [r["test"] for r in m["out_of_range"]]) for m in now["members"]] == [
        ("Member A", ["Ferritin"]),
        ("Member B", ["LDL Cholesterol"]),
    ]
    since = run(tools, "get_out_of_range", since="2025-04-01")
    assert [len(m["out_of_range"]) for m in since["members"]] == [0, 1]


def test_compare_the_latest_two_reports(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    result = run(tools, "compare_reports", member="Member A")

    assert result["earlier_report"] == {"date": "3 Mar 2024", "lab": "Example Labs"}
    assert result["later_report"] == {"date": "3 Mar 2025", "lab": "Other Labs"}
    ferritin = next(t for t in result["tests_in_both"] if t["test"] == "Ferritin")
    assert ferritin["change"] == "-51.9 ng/mL"
    assert ferritin["change_percent"] == -86.4
    assert result["only_in_later"] == ["URINE GLUCOSE"]

    by_date = run(
        tools, "compare_reports", member="Member A", report_a="2025-03-03", report_b="2024-03-03"
    )
    assert by_date["earlier_report"]["date"] == "3 Mar 2024"


def test_compare_needs_one_member_and_two_reports(
    db_session: Session, family: dict[str, Any]
) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    assert run(tools, "compare_reports")["error"] == "Say which member: one of Member A, Member B."
    assert run(tools, "compare_reports", member="Member B")["error"] == (
        "Member B has 1 saved report(s); two are needed."
    )
    assert run(tools, "compare_reports", member="Member A", report_a="2020-01-01")["error"] == (
        "No report collected on 2020-01-01. Report dates: 2025-03-03, 2024-03-03."
    )


def test_trend_summary_is_computed_not_guessed(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"])
    [trend] = run(tools, "get_trend_summary", metric="Ferritin")["trend"]
    assert trend == {
        "member": "Member A",
        "results_compared": 2,
        "results_not_comparable": 0,
        "first": {"date": "3 Mar 2024", "value": "60.1 ng/mL", "flag": "normal"},
        "previous": {"date": "3 Mar 2024", "value": "60.1 ng/mL", "flag": "normal"},
        "latest": {"date": "3 Mar 2025", "value": "8.2 ng/mL", "flag": "low"},
        "change_since_first": "-51.9 ng/mL",
        "percent_change_since_first": -86.4,
        "change_since_previous": "-51.9 ng/mL",
        "percent_change_since_previous": -86.4,
        "slope_per_year": pytest.approx(-51.8, abs=0.2),
        "direction": "falling",
        "range": "moved below the range",
    }


def test_search_report_text_within_the_scope(db_session: Session, family: dict[str, Any]) -> None:
    embedder = FakeEmbedder()
    for patient in (family["amma"], family["stranger"]):
        index_report(db_session, add_confirmed_report(db_session, patient), embedder)
    tools = family_tools(db_session, family["amma"], family["appa"])

    result = run(tools, "search_report_text", query="ferritin immunoassay", k=8)
    assert result["results"]
    assert {r["member"] for r in result["results"]} == {"Member A"}
    assert "not instructions" in result["note"]


def test_tools_never_reach_another_family(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    texts = [
        tools.run("list_available_metrics", "{}"),
        tools.run("get_latest_values", "{}"),
        tools.run("get_out_of_range", '{"include_earlier": true}'),
        tools.run("get_metric_history", '{"metric": "LDL Cholesterol"}'),
        tools.run("get_trend_summary", '{"metric": "Ferritin"}'),
    ]
    joined = "\n".join(texts)
    # The stranger's values.
    assert "210" not in joined
    assert "5.0 ng/mL" not in joined
    assert {s.patient_id for s in tools.sources()} <= {family["amma"].id, family["appa"].id}
    # Asking for a member who is not in this family is refused, not widened.
    assert run(tools, "get_latest_values", member="Member C")["error"] == (
        "There is no member 'Member C'. Members: Member A, Member B."
    )
    assert run(tools, "get_latest_values", member="Stranger")["error"].startswith(
        "There is no member"
    )


def test_tool_results_never_contain_names(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"], family["appa"])
    for name in ("list_available_metrics", "get_latest_values", "get_out_of_range"):
        text = tools.run(name, "{}")
        tools.scope.check_outgoing([text])  # raises if a name is present
        assert "Rao" not in text


def test_bad_calls_come_back_as_errors_for_the_model(
    db_session: Session, family: dict[str, Any]
) -> None:
    tools = family_tools(db_session, family["amma"])
    assert json.loads(tools.run("drop_table", "{}")) == {
        "error": "There is no tool called 'drop_table'."
    }
    assert json.loads(tools.run("get_metric_history", "{not json")) == {
        "error": "The arguments were not valid JSON."
    }
    error = json.loads(tools.run("get_metric_history", '{"start_date": "soon"}'))["error"]
    assert error.startswith("Invalid arguments: metric: Field required; start_date:")
    assert json.loads(
        tools.run(
            "get_metric_history",
            '{"metric": "Ferritin", "start_date": "2025-02-01", "end_date": "2025-01-01"}',
        )
    ) == {"error": "start_date must not be after end_date."}


def test_sources_are_the_reports_read(db_session: Session, family: dict[str, Any]) -> None:
    tools = family_tools(db_session, family["amma"])
    tools.run("get_metric_history", '{"metric": "Ferritin"}')
    sources = tools.sources()
    assert [s.report_id for s in sources] == [family["new"].id, family["old"].id]
    assert [s.lab_name for s in sources] == ["Other Labs", "Example Labs"]
