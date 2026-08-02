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

One test rather than a parametrised eighty-five, because the app has to be
built *inside* a test: ``conftest`` configures settings in an autouse fixture,
and collection happens before any fixture runs. The second draft built it at
import time and failed on CI, where there is no ``.env`` to fall back on.
Reporting every offending route at once is better output anyway.
"""

from __future__ import annotations

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


def _concrete(path: str) -> str:
    """Fill path parameters with a placeholder.

    The value never matters: the request has to be rejected before anything
    reads it, which is the property under test.
    """
    while "{" in path:
        start = path.index("{")
        end = path.index("}", start)
        path = path[:start] + PLACEHOLDER + path[end + 1 :]
    return path


def test_no_route_answers_an_anonymous_request() -> None:
    from jip_api.main import create_app

    app = create_app()
    routes = sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"} and path not in PUBLIC
    )

    # Guards the guard: a change to how the surface is discovered would
    # otherwise leave this green while checking nothing, which is the exact
    # failure it exists to catch elsewhere — and which the first draft had.
    assert len(routes) >= 30, f"only found {len(routes)} routes; the discovery is broken"

    reachable: list[str] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        for method, path in routes:
            response = client.request(method, _concrete(path))
            # 401 specifically, not "not 200". A 422 would mean the body was
            # parsed before the caller was checked; a 404 that a lookup ran.
            if response.status_code != 401:
                reachable.append(f"{method} {path} -> {response.status_code}")

    listing = "\n  ".join(reachable)
    assert not reachable, (
        f"these answered without a token:\n  {listing}\n"
        "If one is public on purpose, add it to PUBLIC and say why."
    )
