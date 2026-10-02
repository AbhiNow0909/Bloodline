"""Explanations from the real Groq API, on made-up data.

Skipped unless GROQ_API_KEY is set (it is not in CI). Deselect locally with `-m "not live"`.
Only facts about made-up results are sent: no names, no dates.
"""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.agent import ChatScope
from app.services.insights import explain_insights, member_insights
from app.services.llm import get_structuring_client
from tests.agent_helpers import rao_family, reading, report_on

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(get_settings().groq_api_key is None, reason="GROQ_API_KEY is not set"),
]


class Recording:
    """The real client, recording what was sent."""

    def __init__(self) -> None:
        self.real = get_structuring_client()
        self.sent: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> str:
        self.sent.append(kwargs)
        return self.real.complete_json(**kwargs)


def test_real_explanations_follow_the_rules(db_session: Session) -> None:
    data = rao_family(db_session)
    amma = data["amma"]
    newest = report_on(db_session, amma, "2025-09-05")
    reading(db_session, newest, "Ferritin", "20.0", "ng/mL", "13", "150", "normal")  # back in
    reading(db_session, newest, "Haemoglobin", "16.1", "g/dL", "12.0", "15.0", "high")
    reading(db_session, data["old"], "HbA1c", "4.0", "%", None, "5.7", "normal")
    reading(db_session, newest, "HbA1c", "5.5", "%", None, "5.7", "normal")  # +37.5 %
    found = member_insights(db_session, [amma.id])[amma.id]
    assert {i.kind for i in found} == {"outside_range", "big_change", "back_in_range"}
    client = Recording()

    explanations = explain_insights(
        client, get_settings().agent_model, ChatScope.for_member(amma), found
    )

    # Every finding explained, each passing the number check (checked inside).
    assert [(e.metric_id, e.kind) for e in explanations] == [(i.metric.id, i.kind) for i in found]
    for explanation in explanations:
        text = explanation.text.casefold()
        assert "you have" not in text
        assert not {"you", "your"} & set(text.replace(".", " ").replace(",", " ").split())
        assert "amma" not in text
        assert len(explanation.text) < 800
    assert "Amma" not in str(client.sent)
    print(*(f"{e.kind}: {e.text}" for e in explanations), sep="\n")
