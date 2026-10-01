"""Test data and a scripted model for the query agent. All names and values are made up."""

import copy
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.seed import load_metric_seeds, seed_metric_dictionary
from app.models import CanonicalMetric, Metric, Patient, Report
from app.services.extraction.header import IST
from app.services.llm import AgentTurn, ToolCall
from tests.factories import add, add_family, add_patient, build_metric, build_report


def seed_dictionary(session: Session) -> None:
    seed_metric_dictionary(session, load_metric_seeds())


def metric_id(session: Session, name: str) -> Any:
    return session.scalars(
        select(CanonicalMetric.id).where(CanonicalMetric.canonical_name == name)
    ).one()


def report_on(session: Session, patient: Patient, day: str, lab: str = "Example Labs") -> Report:
    """A confirmed report collected at 08:15 Indian time on `day` (YYYY-MM-DD)."""
    collected = datetime.fromisoformat(f"{day}T08:15:00").replace(tzinfo=IST)
    return add(
        session,
        build_report(patient, status="confirmed", lab_name=lab, collected_at=collected),
    )


def reading(
    session: Session,
    report: Report,
    test: str,
    value: str,
    unit: str,
    low: str | None,
    high: str | None,
    flag: str,
    *,
    mapped: bool = True,
) -> Metric:
    """A saved value on `report`. `test` is a dictionary name when mapped, else as printed."""
    numeric = Decimal(value) if value.replace(".", "", 1).isdigit() else None
    canonical = metric_id(session, test) if mapped else None
    unit_canonical = (
        session.get_one(CanonicalMetric, canonical).canonical_unit if canonical else None
    )
    return add(
        session,
        build_metric(
            report,
            canonical_metric_id=canonical,
            raw_name=test.upper(),
            value_text=value,
            value_numeric=numeric,
            unit=unit,
            value_canonical=numeric if canonical and unit == unit_canonical else None,
            unit_canonical=unit_canonical if canonical and unit == unit_canonical else None,
            reference_low=Decimal(low) if low else None,
            reference_high=Decimal(high) if high else None,
            flag=flag,
            collected_at=report.collected_at,
        ),
    )


def call(name: str, arguments: dict[str, Any] | str, call_id: str = "") -> ToolCall:
    text = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ToolCall(id=call_id or f"call-{name}", name=name, arguments=text)


class ScriptedAgent:
    """Plays back model turns in order and records exactly what would have been sent."""

    def __init__(self, *turns: AgentTurn) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        force_answer: bool,
    ) -> AgentTurn:
        self.requests.append(
            {
                "model": model,
                "messages": copy.deepcopy(list(messages)),
                "tools": copy.deepcopy(list(tools)),
                "force_answer": force_answer,
            }
        )
        return self.turns.pop(0)

    def sent_text(self) -> str:
        """Everything that went to the model, as one string (to look for names)."""
        return json.dumps(self.requests, ensure_ascii=False)

    def tool_results(self) -> list[dict[str, Any]]:
        """The tool results of the last request, parsed."""
        return [
            json.loads(m["content"]) for m in self.requests[-1]["messages"] if m["role"] == "tool"
        ]


ADDED = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))


def rao_family(db_session: Session) -> dict[str, Any]:
    """Amma (two reports, ferritin falling to low) and Appa (one report) in one family; a
    stranger with high LDL in another family."""
    seed_dictionary(db_session)
    ours = add_family(db_session, name="Rao family")
    # Labels follow the order members were added (A, then B).
    amma = add_patient(db_session, ours, display_name="Amma Rao", sex="female", created_at=ADDED[0])
    appa = add_patient(db_session, ours, display_name="Appa Rao", sex="male", created_at=ADDED[1])
    old = report_on(db_session, amma, "2024-03-03")
    new = report_on(db_session, amma, "2025-03-03", lab="Other Labs")
    reading(db_session, old, "Ferritin", "60.1", "ng/mL", "13", "150", "normal")
    reading(db_session, old, "Haemoglobin", "12.9", "g/dL", "12.0", "15.0", "normal")
    reading(db_session, new, "Ferritin", "8.2", "ng/mL", "13", "150", "low")
    reading(db_session, new, "Haemoglobin", "12.1", "g/dL", "12.0", "15.0", "normal")
    reading(db_session, new, "Urine Glucose", "Negative", "", None, None, "unknown", mapped=False)
    appa_report = report_on(db_session, appa, "2025-06-01")
    reading(db_session, appa_report, "LDL Cholesterol", "142", "mg/dL", None, "100", "high")

    stranger = add_patient(db_session, add_family(db_session), display_name="Stranger")
    theirs = report_on(db_session, stranger, "2025-01-01")
    reading(db_session, theirs, "LDL Cholesterol", "210", "mg/dL", None, "100", "high")
    reading(db_session, theirs, "Ferritin", "5.0", "ng/mL", "13", "150", "low")
    return {"amma": amma, "appa": appa, "stranger": stranger, "old": old, "new": new}
