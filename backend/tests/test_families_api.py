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


def test_create_and_list_families(client: TestClient, alice: User, bob: User) -> None:
    created = create_family(client, alice, "  Sharma Family  ")
    create_family(client, alice, "Parents")
    bobs = create_family(client, bob, "Bob's Family")
    add_member(client, alice, created["id"])
    add_member(client, alice, created["id"], display_name="Dad", sex="male")
    add_member(client, bob, bobs["id"])

    assert created["name"] == "Sharma Family"
    assert created["patient_count"] == 0
    listed = client.get("/families", headers=auth_headers(alice)).json()
    # Sorted by name; counts include only each family's own members (and zero-member families).
    assert [(f["name"], f["patient_count"]) for f in listed] == [
        ("Parents", 0),
        ("Sharma Family", 2),
    ]


def test_family_names_are_unique_per_user(client: TestClient, alice: User, bob: User) -> None:
    create_family(client, alice, "Sharma Family")
    parents = create_family(client, alice, "Parents")
    headers = auth_headers(alice)

    duplicate = client.post("/families", json={"name": "Sharma Family"}, headers=headers)
    rename_clash = client.patch(
        f"/families/{parents['id']}", json={"name": "Sharma Family"}, headers=headers
    )

    assert duplicate.status_code == rename_clash.status_code == 409
    create_family(client, bob, "Sharma Family")  # other users may reuse the name


def test_rename_family(client: TestClient, alice: User) -> None:
    family = create_family(client, alice, "Sharma Family")
    url, headers = f"/families/{family['id']}", auth_headers(alice)

    renamed = client.patch(url, json={"name": "Sharmas"}, headers=headers)
    unchanged = client.patch(url, json={"name": "Sharmas"}, headers=headers)

    assert renamed.status_code == unchanged.status_code == 200
    assert client.get(url, headers=headers).json()["name"] == "Sharmas"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"name": "   "}, id="blank"),
        pytest.param({"name": "x" * 101}, id="too-long"),
        pytest.param({}, id="missing"),
        pytest.param({"name": "Sharmas", "shared": True}, id="unknown-field"),
    ],
)
def test_family_name_validation(client: TestClient, alice: User, body: dict[str, Any]) -> None:
    assert client.post("/families", json=body, headers=auth_headers(alice)).status_code == 422


def test_add_and_list_family_members(client: TestClient, alice: User) -> None:
    family = create_family(client, alice)
    mum = add_member(client, alice, family["id"], display_name="  Mum ", date_of_birth="1960-05-01")
    add_member(client, alice, family["id"], display_name="Dad", sex="male")
    headers = auth_headers(alice)

    assert mum["display_name"] == "Mum"
    assert mum["family_id"] == family["id"]
    members = client.get(f"/families/{family['id']}/patients", headers=headers).json()
    assert [m["display_name"] for m in members] == ["Dad", "Mum"]
    assert client.get(f"/families/{family['id']}", headers=headers).json()["patient_count"] == 2


def test_deleting_a_family_deletes_its_members(client: TestClient, alice: User) -> None:
    family = create_family(client, alice)
    member = add_member(client, alice, family["id"])
    headers = auth_headers(alice)

    assert client.delete(f"/families/{family['id']}", headers=headers).status_code == 204
    assert client.get(f"/families/{family['id']}", headers=headers).status_code == 404
    assert client.get(f"/patients/{member['id']}", headers=headers).status_code == 404
    assert client.get("/families", headers=headers).json() == []


FAMILY_ROUTES = [
    pytest.param("GET", "", None, id="get"),
    pytest.param("PATCH", "", {"name": "Taken Over"}, id="rename"),
    pytest.param("DELETE", "", None, id="delete"),
    pytest.param("GET", "/patients", None, id="list-members"),
    pytest.param("POST", "/patients", MUM, id="add-member"),
]


@pytest.mark.parametrize(("method", "suffix", "body"), FAMILY_ROUTES)
def test_other_users_cannot_tell_a_family_exists(
    client: TestClient,
    alice: User,
    bob: User,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    family = create_family(client, alice)
    add_member(client, alice, family["id"])
    headers = auth_headers(bob)

    alices = client.request(method, f"/families/{family['id']}{suffix}", json=body, headers=headers)
    missing = client.request(
        method, f"/families/{uuid.uuid4()}{suffix}", json=body, headers=headers
    )

    assert alices.status_code == missing.status_code == 404
    assert alices.json() == missing.json() == {"detail": "Family not found"}
    unchanged = client.get(f"/families/{family['id']}", headers=auth_headers(alice)).json()
    assert unchanged == family | {"patient_count": 1}
    assert client.get("/families", headers=headers).json() == []


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", ""),
        ("POST", ""),
        ("GET", "/{id}"),
        ("PATCH", "/{id}"),
        ("DELETE", "/{id}"),
        ("GET", "/{id}/patients"),
        ("POST", "/{id}/patients"),
    ],
)
def test_family_routes_require_authentication(
    client: TestClient, alice: User, method: str, suffix: str
) -> None:
    family = create_family(client, alice)

    response = client.request(
        method, f"/families{suffix.format(id=family['id'])}", json={"name": "X"} | MUM
    )

    assert response.status_code == 401
