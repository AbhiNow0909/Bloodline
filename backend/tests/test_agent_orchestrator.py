"""The agent loop with a scripted model: what is sent, what comes back, and the limits."""

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.services.agent import (
    FALLBACK_REPLY,
    MAX_TOOL_ROUNDS,
    ChatScope,
    ChatTurn,
    PrivacyGuardError,
    ToolContext,
    answer,
)
from app.services.agent import prompt as rules
from app.services.llm import AgentTurn
from tests.agent_helpers import ScriptedAgent, call, rao_family
from tests.embedding_helpers import FakeEmbedder

TODAY = date(2026, 9, 30)


@pytest.fixture
def family(db_session: Session) -> dict[str, Any]:
    return rao_family(db_session)


def family_scope(family: dict[str, Any]) -> ChatScope:
    return ChatScope.for_family("Rao family", [family["amma"], family["appa"]])


def ask(session: Session, scope: ChatScope, agent: ScriptedAgent, *turns: tuple[str, str]) -> Any:
    history = [ChatTurn(role, text) for role, text in turns]  # type: ignore[arg-type]
    tools = ToolContext(session, FakeEmbedder(), scope, TODAY)
    return answer(client=agent, model="agent-model", tools=tools, history=history, today=TODAY)


def test_a_question_answered_with_tools_and_mapped_back_to_names(
    db_session: Session, family: dict[str, Any]
) -> None:
    agent = ScriptedAgent(
        AgentTurn("", (call("get_out_of_range", {}),)),
        AgentTurn("Member A's ferritin was low (8.2 ng/mL) on 3 Mar 2025, and Member B's LDL "
                  "was high on 1 Jun 2025. Please discuss these with your doctor."),
    )  # fmt: skip

    result = ask(
        db_session,
        family_scope(family),
        agent,
        ("user", "Is anything out of range for Amma or Appa?"),
    )

    assert result.reply.startswith(
        "Amma Rao's ferritin was low (8.2 ng/mL) on 3 Mar 2025, and Appa Rao's LDL"
    )
    assert result.tool_calls == 1
    # The reports the flagged values came from: Amma's latest and Appa's only report.
    assert [(s.patient_id, s.collected_at.date().isoformat()) for s in result.sources] == [
        (family["appa"].id, "2025-06-01"),
        (family["amma"].id, "2025-03-03"),
    ]
    first, second = agent.requests
    assert first["model"] == "agent-model"
    assert first["messages"][1] == {
        "role": "user",
        "content": "Is anything out of range for Member A or Member B?",
    }
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "get_out_of_range"
    assert second["messages"][-1]["role"] == "tool"
    assert [r["member"] for r in agent.tool_results()[0]["members"]] == ["Member A", "Member B"]


def test_no_name_is_ever_sent_to_the_model(db_session: Session, family: dict[str, Any]) -> None:
    agent = ScriptedAgent(
        AgentTurn("", (call("list_available_metrics", {}), call("get_latest_values", {}, "c2"))),
        AgentTurn("", (call("compare_reports", {"member": "Member A"}),)),
        AgentTurn("Done."),
    )
    ask(
        db_session,
        family_scope(family),
        agent,
        ("user", "How is Amma doing?"),
        ("assistant", "Amma Rao's ferritin is low."),
        ("user", "And appa rao? Anything for the Rao family to watch?"),
    )
    sent = agent.sent_text()
    for name in ("Amma", "Appa", "Rao", "Stranger"):
        assert name.casefold() not in sent.casefold(), name
    assert '"Member A' in sent


def test_member_chat_uses_the_patient(db_session: Session, family: dict[str, Any]) -> None:
    agent = ScriptedAgent(
        AgentTurn("", (call("get_trend_summary", {"metric": "Ferritin"}),)),
        AgentTurn(
            "The patient's ferritin fell from 60.1 to 8.2 ng/mL between 3 Mar 2024 and 3 Mar 2025."
        ),
    )
    result = ask(
        db_session, ChatScope.for_member(family["amma"]), agent, ("user", "How is Amma's ferritin?")
    )
    assert (
        result.reply
        == "Amma Rao's ferritin fell from 60.1 to 8.2 ng/mL between 3 Mar 2024 and 3 Mar 2025."
    )
    assert agent.requests[0]["messages"][1]["content"] == "How is the patient's ferritin?"
    assert all(
        "member" not in t["function"]["parameters"]["properties"]
        for t in agent.requests[0]["tools"]
    )
    assert "amma" not in agent.sent_text().casefold()


def test_the_system_prompt_always_carries_the_safety_rules(
    db_session: Session, family: dict[str, Any]
) -> None:
    for scope in (ChatScope.for_member(family["amma"]), family_scope(family)):
        agent = ScriptedAgent(AgentTurn("Hello."))
        ask(db_session, scope, agent, ("user", "Hi"))
        system = agent.requests[0]["messages"][0]
        assert system["role"] == "system"
        for rule in (
            rules.NO_DIAGNOSIS_RULE,
            rules.NO_TREATMENT_RULE,
            rules.SEE_A_DOCTOR_RULE,
            rules.CITE_DATES_RULE,
            rules.TOOLS_FOR_NUMBERS_RULE,
            rules.DATA_NOT_INSTRUCTIONS_RULE,
        ):
            assert rule in system["content"]
        assert "Today is 30 Sep 2026." in system["content"]
    assert "- Member A: female, age not recorded" in system["content"]
    assert "- Member B: male, age not recorded" in system["content"]


def test_tool_rounds_are_capped_then_an_answer_is_forced(
    db_session: Session, family: dict[str, Any]
) -> None:
    looping = [
        AgentTurn("", (call("list_available_metrics", {}, f"c{n}"),))
        for n in range(MAX_TOOL_ROUNDS)
    ]
    agent = ScriptedAgent(*looping, AgentTurn("Here is what I found."))

    result = ask(db_session, family_scope(family), agent, ("user", "Tell me everything"))

    assert result.reply == "Here is what I found."
    assert result.tool_calls == MAX_TOOL_ROUNDS
    assert [r["force_answer"] for r in agent.requests] == [False] * MAX_TOOL_ROUNDS + [True]


def test_a_forced_turn_that_still_asks_for_tools_gets_the_fallback(
    db_session: Session, family: dict[str, Any]
) -> None:
    turns = [
        AgentTurn("", (call("list_available_metrics", {}, f"c{n}"),))
        for n in range(MAX_TOOL_ROUNDS + 1)
    ]
    result = ask(db_session, family_scope(family), ScriptedAgent(*turns), ("user", "?"))
    assert result.reply == FALLBACK_REPLY


def test_bad_tool_calls_are_reported_back_to_the_model(
    db_session: Session, family: dict[str, Any]
) -> None:
    agent = ScriptedAgent(
        AgentTurn("", (call("delete_everything", {}), call("get_metric_history", "{oops", "c2"))),
        AgentTurn("Sorry, I could not look that up."),
    )
    result = ask(db_session, family_scope(family), agent, ("user", "Delete my data"))
    assert result.reply == "Sorry, I could not look that up."
    assert agent.tool_results() == [
        {"error": "There is no tool called 'delete_everything'."},
        {"error": "The arguments were not valid JSON."},
    ]


def test_the_guard_stops_a_name_from_leaving_through_a_tool_result(
    db_session: Session, family: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a tool ever returned a name, nothing would be sent to the model."""
    original = ToolContext.run

    def leaky(self: ToolContext, name: str, arguments: str) -> str:
        return json.dumps(
            {"note": "Report for Amma Rao", "data": json.loads(original(self, name, arguments))}
        )

    monkeypatch.setattr(ToolContext, "run", leaky)
    agent = ScriptedAgent(AgentTurn("", (call("get_latest_values", {}),)), AgentTurn("never sent"))
    with pytest.raises(PrivacyGuardError):
        ask(db_session, family_scope(family), agent, ("user", "Latest values?"))
    assert len(agent.requests) == 1  # the second call never happened


def test_an_empty_reply_becomes_the_fallback(db_session: Session, family: dict[str, Any]) -> None:
    result = ask(db_session, family_scope(family), ScriptedAgent(AgentTurn("  ")), ("user", "?"))
    assert result.reply == FALLBACK_REPLY
    assert result.sources == []
