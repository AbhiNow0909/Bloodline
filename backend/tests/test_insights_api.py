"""GET /patients/{id}/insights, the family overview's insights, and
POST /patients/{id}/insights/explain with a scripted model."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_explanation_client_factory
from app.config import get_settings
from app.main import app
from app.models import Family, User
from app.schemas.chat import DISCLAIMER
from app.services.llm import LLMNotConfiguredError, LLMRequestError, LLMUnavailableError
from tests.agent_helpers import rao_family
from tests.factories import add, auth_headers, build_user
from tests.structuring_data import FakeChatClient


@pytest.fixture
def family(db_session: Session) -> dict[str, Any]:
    data = rao_family(db_session)
    family = db_session.get_one(Family, data["amma"].family_id)
    data["family"] = family
    data["owner"] = db_session.get_one(User, family.owner_id)
    return data


@pytest.fixture
def model() -> Iterator[FakeChatClient]:
    fake = FakeChatClient(
        {"explanations": [{"id": "1", "text": "This result is below the lab's usual range."}]}
    )
    app.dependency_overrides[get_explanation_client_factory] = lambda: lambda: fake
    yield fake
    app.dependency_overrides.pop(get_explanation_client_factory, None)


def test_a_members_insights(client: TestClient, family: dict[str, Any]) -> None:
    amma = family["amma"]

    response = client.get(f"/patients/{amma.id}/insights", headers=auth_headers(family["owner"]))

    assert response.status_code == 200, response.text
    (ferritin,) = response.json()
    assert ferritin["kind"] == "outside_range"
    assert ferritin["patient_id"] == str(amma.id)
    assert ferritin["metric"]["canonical_name"] == "Ferritin"
    assert ferritin["latest"]["value_text"] == "8.2"
    assert ferritin["latest"]["flag"] == "low"
    assert ferritin["compared_with"]["value_canonical"] == "60.1"
    assert (ferritin["change"], ferritin["percent_change"]) == ("-51.9", -86.4)
    assert (ferritin["reference_low"], ferritin["reference_high"]) == ("13", "150")
    assert ferritin["outside_in_a_row"] == 1
    assert ferritin["results_compared"] == 2


def test_the_family_overview_lists_each_members_insights(
    client: TestClient, family: dict[str, Any]
) -> None:
    response = client.get(
        f"/families/{family['family'].id}/overview", headers=auth_headers(family["owner"])
    )

    assert response.status_code == 200, response.text
    members = {m["patient"]["display_name"]: m for m in response.json()["members"]}
    assert [i["metric"]["canonical_name"] for i in members["Amma Rao"]["insights"]] == ["Ferritin"]
    assert [i["metric"]["canonical_name"] for i in members["Appa Rao"]["insights"]] == [
        "LDL Cholesterol"
    ]


def test_explanations_with_the_disclaimer(
    client: TestClient, family: dict[str, Any], model: FakeChatClient
) -> None:
    amma = family["amma"]

    response = client.post(
        f"/patients/{amma.id}/insights/explain", headers=auth_headers(family["owner"])
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "explanations": [
            {
                "metric_id": response.json()["explanations"][0]["metric_id"],
                "kind": "outside_range",
                "text": "This result is below the lab's usual range.",
            }
        ],
        "disclaimer": DISCLAIMER,
    }
    (call,) = model.calls
    assert call["model"] == get_settings().agent_model
    assert "Amma" not in str(call)


def test_no_findings_means_no_call(
    client: TestClient, db_session: Session, model: FakeChatClient
) -> None:
    owner = add(db_session, build_user())
    family_id = client.post(
        "/families", json={"name": "Quiet family"}, headers=auth_headers(owner)
    ).json()["id"]
    member = client.post(
        f"/families/{family_id}/patients",
        json={"display_name": "Nani", "sex": "female"},
        headers=auth_headers(owner),
    ).json()

    response = client.post(
        f"/patients/{member['id']}/insights/explain", headers=auth_headers(owner)
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"explanations": [], "disclaimer": DISCLAIMER}
    assert model.calls == []


@pytest.mark.parametrize(
    ("failure", "status", "detail"),
    [
        (
            LLMNotConfiguredError("GROQ_API_KEY is not set"),
            503,
            "GROQ_API_KEY is not set, so explanations are not available.",
        ),
        (
            LLMUnavailableError("busy"),
            503,
            "The assistant is busy right now. Please try again in a minute.",
        ),
        (
            LLMRequestError("rejected"),
            502,
            "The explanations could not be written. Please try again.",
        ),
        ("not json", 502, "The explanations could not be written. Please try again."),
    ],
)
def test_ai_failures_become_clear_errors(
    client: TestClient, family: dict[str, Any], failure: Any, status: int, detail: str
) -> None:
    def factory() -> FakeChatClient:
        if isinstance(failure, LLMNotConfiguredError):
            raise failure
        return FakeChatClient(failure)

    app.dependency_overrides[get_explanation_client_factory] = lambda: factory
    try:
        response = client.post(
            f"/patients/{family['amma'].id}/insights/explain",
            headers=auth_headers(family["owner"]),
        )
    finally:
        app.dependency_overrides.pop(get_explanation_client_factory, None)

    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_a_name_in_the_facts_is_never_sent(
    client: TestClient, db_session: Session, family: dict[str, Any], model: FakeChatClient
) -> None:
    family["amma"].display_name = "Ferritin"
    db_session.flush()

    response = client.post(
        f"/patients/{family['amma'].id}/insights/explain", headers=auth_headers(family["owner"])
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "The explanations could not be written safely."}
    assert model.calls == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_only_the_owner(
    client: TestClient, db_session: Session, family: dict[str, Any], method: str
) -> None:
    path = f"/patients/{family['amma'].id}/insights" + ("/explain" if method == "POST" else "")
    stranger = add(db_session, build_user())

    assert client.request(method, path).status_code == 401
    response = client.request(method, path, headers=auth_headers(stranger))
    assert response.status_code == 404
    assert response.json() == {"detail": "Patient not found"}
