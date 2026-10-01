"""The query agent against the real Groq API, on made-up data.

Skipped unless GROQ_API_KEY is set (it is not in CI). Deselect locally with `-m "not live"`.
Only synthetic values and pseudonymous labels are sent; the test checks that no name was.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.agent import ChatScope, ChatTurn, ToolContext, answer
from app.services.llm import AgentTurn, get_agent_client
from tests.agent_helpers import rao_family
from tests.embedding_helpers import FakeEmbedder

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(get_settings().groq_api_key is None, reason="GROQ_API_KEY is not set"),
]

TODAY = date(2026, 9, 30)


class Recording:
    """The real client, recording everything sent (to check for names)."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.real = get_agent_client()

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        force_answer: bool,
    ) -> AgentTurn:
        self.sent.append([dict(m) for m in messages])
        return self.real.complete_with_tools(
            model=model, messages=messages, tools=tools, force_answer=force_answer
        )


def ask(session: Session, scope: ChatScope, question: str) -> tuple[Any, Recording]:
    client = Recording()
    result = answer(
        client=client,
        model=get_settings().agent_model,
        tools=ToolContext(session, FakeEmbedder(), scope, TODAY),
        history=[ChatTurn("user", question)],
        today=TODAY,
    )
    return result, client


def test_member_chat_answers_from_the_tools(db_session: Session) -> None:
    family = rao_family(db_session)
    result, client = ask(
        db_session,
        ChatScope.for_member(family["amma"]),
        "What was Amma's most recent ferritin, and is it within the lab's range?",
    )
    assert result.tool_calls >= 1
    assert "8.2" in result.reply
    assert "2025" in result.reply
    assert result.sources
    assert "amma" not in json.dumps(client.sent).casefold()


def test_family_chat_finds_who_has_high_ldl(db_session: Session) -> None:
    family = rao_family(db_session)
    scope = ChatScope.for_family("Rao family", [family["amma"], family["appa"]])
    result, client = ask(db_session, scope, "Who in the Rao family has high LDL cholesterol?")

    assert "Appa Rao" in result.reply
    assert "142" in result.reply
    assert "Stranger" not in result.reply
    sent = json.dumps(client.sent).casefold()
    for word in ("amma", "appa", "rao"):
        assert word not in sent, word
