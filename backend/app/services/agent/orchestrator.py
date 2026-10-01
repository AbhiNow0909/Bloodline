"""The query agent's loop: the model asks for tools, we run them in scope, it answers.

At most `MAX_TOOL_ROUNDS` rounds of tool calls; after that the model must answer with what it
has. Before every call, everything about to be sent is checked for family members' names
(Principle 2), and nothing is sent if one is found.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.services.agent.prompt import system_prompt
from app.services.agent.tools import Source, ToolContext
from app.services.llm import AgentClient

MAX_TOOL_ROUNDS = 5
FALLBACK_REPLY = "I couldn't find an answer to that. Try asking about a specific test or report."


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AgentAnswer:
    reply: str  # for the user: labels already mapped back to names
    sources: list[Source]
    tool_calls: int


def _outgoing_text(
    messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
) -> list[str]:
    texts = [str(m.get("content") or "") for m in messages]
    texts += [c["function"]["arguments"] for m in messages for c in m.get("tool_calls", [])]
    texts.append(json.dumps(tools))
    return texts


def answer(
    *,
    client: AgentClient,
    model: str,
    tools: ToolContext,
    history: Sequence[ChatTurn],
    today: date,
) -> AgentAnswer:
    """Answer the last user turn of `history` (earlier turns give context)."""
    scope = tools.scope
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(scope, today)}]
    messages += [{"role": t.role, "content": scope.pseudonymize(t.content)} for t in history]
    specs = tools.specs()
    calls = 0

    for round_number in range(MAX_TOOL_ROUNDS + 1):
        force_answer = round_number == MAX_TOOL_ROUNDS
        scope.check_outgoing(_outgoing_text(messages, specs))
        turn = client.complete_with_tools(
            model=model, messages=messages, tools=specs, force_answer=force_answer
        )
        if not turn.tool_calls or force_answer:
            text = turn.content.strip() or FALLBACK_REPLY
            return AgentAnswer(scope.depseudonymize(text), tools.sources(), calls)

        messages.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in turn.tool_calls
                ],
            }
        )
        for call in turn.tool_calls:
            calls += 1
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": tools.run(call.name, call.arguments),
                }
            )
    raise AssertionError("unreachable: the last round always answers")
