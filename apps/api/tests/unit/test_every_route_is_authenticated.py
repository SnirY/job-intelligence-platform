"""No route reaches user data without a caller.

``docs/11-engineering-standards.md`` lists four minimum security tests, and all
four are covered — cross-user job access, cross-user resume download,
private-network URL fetching, unsupported uploads. Every user-owned router also
has its own cross-user test.

All of that is per-route, written by whoever added the route. This is the part
that does not depend on remembering: it reads the API's own published surface,
so a route added next month is covered the moment it exists.

The check is deliberately not "does this route enforce ownership" — that needs
two users and real data, and lives in the integration suites. It is the cheaper
and more absolute question underneath: **can an anonymous caller reach it at
all.** A route answering anything but 401 to a request with no token is either
public on purpose, in which case it belongs in ``PUBLIC`` below with a reason,
or public by accident.

The surface comes from ``app.openapi()`` rather than from walking
``app.routes``. FastAPI nests included routers inside wrappers whose own
``.routes`` are more wrappers, and a walk of the top level finds zero endpoints
— which is how the first draft of this file passed while testing nothing. The
OpenAPI document is the same list the client generates from, carries the final
prefixed paths, and does not move when FastAPI's internals do.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PUBLIC: frozenset[str] = frozenset(
    {
        # Liveness and readiness. Deliberately open: a probe cannot hold a
        # token, and neither reveals anything about any user.
        "/api/v1/health",
        "/api/v1/health/ready",
        # The MIME types the importer accepts. A static capability list, taking
        # no user and reading nothing — the browser needs it to build the file
        # picker's accept filter, and gating it would mean the picker could not
        # be built until after sign-in.
        "/api/v1/resumes/supported-formats",
    }
)

PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def _published_routes() -> list[tuple[str, str]]:
    """Every (method, path) the API advertises, minus the deliberate few."""
    from jip_api.main import create_app

    schema = create_app().openapi()
    return sorted(
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"} and path not in PUBLIC
    )


ROUTES = _published_routes()


def test_the_api_surface_was_actually_read() -> None:
    """Guards the guard.

    Without this, a change to how the surface is discovered would leave the
    file green while checking nothing — the exact failure it exists to catch
    elsewhere, and the one the first draft of this file actually had.
    """
    assert len(ROUTES) >= 30, f"only found {len(ROUTES)} routes; the discovery is broken"


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=lambda value: str(value))
def test_an_anonymous_request_is_rejected(method: str, path: str) -> None:
    from jip_api.main import create_app

    concrete = path
    while "{" in concrete:
        start = concrete.index("{")
        end = concrete.index("}", start)
        concrete = concrete[:start] + PLACEHOLDER + concrete[end + 1 :]

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.request(method, concrete)

    # 401 specifically, not "not 200". A 422 would mean the request body was
    # parsed before the caller was checked, and a 404 would mean a lookup ran.
    assert response.status_code == 401, (
        f"{method} {path} answered {response.status_code} without a token. "
        "If it is public on purpose, add it to PUBLIC and say why."
    )
