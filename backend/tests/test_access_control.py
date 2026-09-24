"""Structural guard for Principle 2: every route that takes a family or family-member id
must resolve it through the ownership check. A new route that forgets it fails here
instead of silently exposing another user's family."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts

from app.api.deps import get_owned_family, get_owned_patient
from app.main import app

# FastAPI >= 0.141 keeps included routers nested, so routes are walked with
# `iter_route_contexts` (full paths and dependencies) rather than `app.routes`.
ROUTES = list(iter_route_contexts(app.routes))


def _depends_on(dependant: Dependant, target: Callable[..., Any]) -> bool:
    return any(dep.call is target or _depends_on(dep, target) for dep in dependant.dependencies)


@pytest.mark.parametrize(
    ("path_parameter", "check"),
    [
        pytest.param("{family_id}", get_owned_family, id="family"),
        pytest.param("{patient_id}", get_owned_patient, id="patient"),
    ],
)
def test_every_scoped_route_checks_ownership(
    path_parameter: str, check: Callable[..., Any]
) -> None:
    scoped = [route for route in ROUTES if path_parameter in (route.path or "")]
    unchecked = [
        f"{sorted(route.methods or ())} {route.path}"
        for route in scoped
        if not _depends_on(route.dependant, check)
    ]

    assert scoped, f"expected at least one route with {path_parameter}"
    assert unchecked == []
