import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_patient_access
from app.main import app
from app.models import Patient, User, UserPatientAccess
from tests.factories import add, auth_headers, build_user

MUM: dict[str, Any] = {"display_name": "Mum", "sex": "female"}


@pytest.fixture
def alice(db_session: Session) -> User:
    return add(db_session, build_user())


@pytest.fixture
def bob(db_session: Session) -> User:
    return add(db_session, build_user())


def _create(client: TestClient, owner: User, **fields: Any) -> dict[str, Any]:
    response = client.post("/patients", json=MUM | fields, headers=auth_headers(owner))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_patient_makes_the_creator_its_owner(
    client: TestClient, db_session: Session, alice: User
) -> None:
    patient = _create(client, alice, display_name="  Mum  ", date_of_birth="1960-05-01")

    assert patient["display_name"] == "Mum"
    assert patient["sex"] == "female"
    assert patient["date_of_birth"] == "1960-05-01"
    assert patient["role"] == "owner"
    access = db_session.get(UserPatientAccess, (alice.id, uuid.UUID(patient["id"])))
    assert access is not None
    assert access.role == "owner"


def test_list_shows_only_the_users_own_patients(client: TestClient, alice: User, bob: User) -> None:
    _create(client, alice, display_name="Mum")
    _create(client, alice, display_name="Dad", sex="male")
    _create(client, bob, display_name="Bob's Gran")

    response = client.get("/patients", headers=auth_headers(alice))

    assert response.status_code == 200
    assert [p["display_name"] for p in response.json()] == ["Dad", "Mum"]


def test_owner_can_read_update_and_delete(client: TestClient, alice: User) -> None:
    patient = _create(client, alice)
    url, headers = f"/patients/{patient['id']}", auth_headers(alice)

    assert client.get(url, headers=headers).json() == patient

    updated = client.patch(
        url, json={"display_name": "Mother", "date_of_birth": "1961-02-03"}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json() | {"display_name": "Mum", "date_of_birth": None} == patient

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
    ],
)
def test_create_rejects_invalid_input(
    client: TestClient, alice: User, fields: dict[str, Any]
) -> None:
    response = client.post("/patients", json=MUM | fields, headers=auth_headers(alice))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"display_name": None}, id="null-name"),
        pytest.param({"sex": None}, id="null-sex"),
        pytest.param({"sex": "unknown"}, id="unknown-sex"),
    ],
)
def test_update_rejects_invalid_input(
    client: TestClient, alice: User, fields: dict[str, Any]
) -> None:
    patient = _create(client, alice)

    response = client.patch(f"/patients/{patient['id']}", json=fields, headers=auth_headers(alice))

    assert response.status_code == 422


PATIENT_ROUTES = [
    pytest.param("GET", None, id="get"),
    pytest.param("PATCH", {"display_name": "Changed"}, id="patch"),
    pytest.param("DELETE", None, id="delete"),
]


@pytest.mark.parametrize(("method", "body"), PATIENT_ROUTES)
def test_other_users_cannot_tell_a_patient_exists(
    client: TestClient, alice: User, bob: User, method: str, body: dict[str, Any] | None
) -> None:
    patient = _create(client, alice)
    headers = auth_headers(bob)

    someone_elses = client.request(method, f"/patients/{patient['id']}", json=body, headers=headers)
    nonexistent = client.request(method, f"/patients/{uuid.uuid4()}", json=body, headers=headers)

    assert someone_elses.status_code == nonexistent.status_code == 404
    assert someone_elses.json() == nonexistent.json() == {"detail": "Patient not found"}
    assert client.get(f"/patients/{patient['id']}", headers=auth_headers(alice)).json() == patient


@pytest.mark.parametrize(
    ("method", "body", "expected_status"),
    [
        pytest.param("GET", None, 200, id="get"),
        pytest.param("PATCH", {"display_name": "Changed"}, 403, id="patch"),
        pytest.param("DELETE", None, 403, id="delete"),
    ],
)
def test_viewers_can_read_but_not_change(
    client: TestClient,
    db_session: Session,
    alice: User,
    bob: User,
    method: str,
    body: dict[str, Any] | None,
    expected_status: int,
) -> None:
    patient = _create(client, alice)
    add(db_session, UserPatientAccess(user_id=bob.id, patient_id=patient["id"], role="viewer"))

    response = client.request(
        method, f"/patients/{patient['id']}", json=body, headers=auth_headers(bob)
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == patient | {"role": "viewer"}
    assert client.get(f"/patients/{patient['id']}", headers=auth_headers(alice)).json() == patient


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/patients"),
        ("POST", "/patients"),
        ("GET", "/patients/{id}"),
        ("PATCH", "/patients/{id}"),
        ("DELETE", "/patients/{id}"),
    ],
)
def test_patient_routes_require_authentication(
    client: TestClient, db_session: Session, method: str, path: str
) -> None:
    patient = add(db_session, Patient(display_name="Mum", sex="female"))

    response = client.request(method, path.format(id=patient.id), json=MUM)

    assert response.status_code == 401


def _depends_on(dependant: Dependant, target: Callable[..., Any]) -> bool:
    return any(dep.call is target or _depends_on(dep, target) for dep in dependant.dependencies)


def test_every_patient_scoped_route_checks_access() -> None:
    """Guards future phases: a new /patients/{patient_id}/... route without the access
    dependency fails here instead of silently exposing another family member's data.

    FastAPI >= 0.141 keeps included routers nested, so routes are walked with
    `iter_route_contexts` (full paths and dependencies) rather than `app.routes`."""
    scoped = [c for c in iter_route_contexts(app.routes) if "{patient_id}" in (c.path or "")]
    unchecked = [
        f"{sorted(c.methods or ())} {c.path}"
        for c in scoped
        if not _depends_on(c.dependant, get_patient_access)
    ]

    assert scoped, "expected at least one patient-scoped route"
    assert unchecked == []


def test_validation_errors_never_echo_the_patients_name(client: TestClient, alice: User) -> None:
    name = "Private Name " + "x" * 100

    response = client.post(
        "/patients", json=MUM | {"display_name": name}, headers=auth_headers(alice)
    )

    assert response.status_code == 422
    assert "Private Name" not in response.text
