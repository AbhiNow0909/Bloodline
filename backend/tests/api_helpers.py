"""Small HTTP helpers shared by the API tests."""

from typing import Any

from fastapi.testclient import TestClient

from app.models import User
from tests.factories import auth_headers

MUM: dict[str, Any] = {"display_name": "Mum", "sex": "female"}


def create_family(client: TestClient, owner: User, name: str = "Test Family") -> dict[str, Any]:
    response = client.post("/families", json={"name": name}, headers=auth_headers(owner))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def add_member(client: TestClient, owner: User, family_id: str, **fields: Any) -> dict[str, Any]:
    response = client.post(
        f"/families/{family_id}/patients", json=MUM | fields, headers=auth_headers(owner)
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
