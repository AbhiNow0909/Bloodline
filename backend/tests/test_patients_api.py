"""Family members ("patients") addressed directly by `/patients/{patient_id}`."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from tests.api_helpers import MUM, add_member, create_family
from tests.factories import add, auth_headers, build_user


@pytest.fixture
def alice(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def bob(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def member(client: TestClient, alice: User) -> dict[str, Any]:
    """A member of one of Alice's families."""
    family = create_family(client, alice)
    return add_member(client, alice, family["id"])


def test_owner_can_read_update_and_delete(
    client: TestClient, alice: User, member: dict[str, Any]
) -> None:
    url, headers = f"/patients/{member['id']}", auth_headers(alice)

    assert client.get(url, headers=headers).json() == member

    updated = client.patch(
        url, json={"display_name": "Mother", "date_of_birth": "1961-02-03"}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json() == member | {"display_name": "Mother", "date_of_birth": "1961-02-03"}

    cleared = client.patch(url, json={"date_of_birth": None}, headers=headers)
    assert cleared.json()["date_of_birth"] is None

    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"display_name": "   "}, id="blank-name"),
        pytest.param({"display_name": "x" * 101}, id="long-name"),
        pytest.param({"sex": "other"}, id="unknown-sex"),
        pytest.param({"date_of_birth": "2999-01-01"}, id="future-birth-date"),
        pytest.param({"nickname": "M"}, id="unknown-field"),
        pytest.param({"family_id": str(uuid.uuid4())}, id="family-id-in-body"),
    ],
)
def test_add_member_rejects_invalid_input(
    client: TestClient, alice: User, fields: dict[str, Any]
) -> None:
    family = create_family(client, alice)

    response = client.post(
        f"/families/{family['id']}/patients", json=MUM | fields, headers=auth_headers(alice)
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"display_name": None}, id="null-name"),
        pytest.param({"sex": None}, id="null-sex"),
        pytest.param({"sex": "unknown"}, id="unknown-sex"),
        pytest.param({"family_id": str(uuid.uuid4())}, id="move-to-other-family"),
    ],
)
def test_update_rejects_invalid_input(
    client: TestClient, alice: User, member: dict[str, Any], fields: dict[str, Any]
) -> None:
    response = client.patch(f"/patients/{member['id']}", json=fields, headers=auth_headers(alice))

    assert response.status_code == 422


def test_validation_errors_never_echo_the_members_name(client: TestClient, alice: User) -> None:
    family = create_family(client, alice)
    name = "Private Name " + "x" * 100

    response = client.post(
        f"/families/{family['id']}/patients",
        json=MUM | {"display_name": name},
        headers=auth_headers(alice),
    )

    assert response.status_code == 422
    assert "Private Name" not in response.text


PATIENT_ROUTES = [
    pytest.param("GET", None, id="get"),
    pytest.param("PATCH", {"display_name": "Changed"}, id="patch"),
    pytest.param("DELETE", None, id="delete"),
]


@pytest.mark.parametrize(("method", "body"), PATIENT_ROUTES)
def test_other_users_cannot_tell_a_member_exists(
    client: TestClient,
    alice: User,
    bob: User,
    member: dict[str, Any],
    method: str,
    body: dict[str, Any] | None,
) -> None:
    headers = auth_headers(bob)

    alices = client.request(method, f"/patients/{member['id']}", json=body, headers=headers)
    missing = client.request(method, f"/patients/{uuid.uuid4()}", json=body, headers=headers)

    assert alices.status_code == missing.status_code == 404
    assert alices.json() == missing.json() == {"detail": "Patient not found"}
    assert client.get(f"/patients/{member['id']}", headers=auth_headers(alice)).json() == member


@pytest.mark.parametrize(("method", "body"), PATIENT_ROUTES)
def test_member_routes_require_authentication(
    client: TestClient, member: dict[str, Any], method: str, body: dict[str, Any] | None
) -> None:
    response = client.request(method, f"/patients/{member['id']}", json=body)

    assert response.status_code == 401
