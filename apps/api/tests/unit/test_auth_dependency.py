"""Behaviour of the auth dependency when authentication is not configured.

Regression cover for a defect CI caught: because the token verifier was a
FastAPI dependency, it was constructed before the handler ran. On an instance
with no Clerk settings that construction raised, so a request carrying no
credential at all came back as an opaque 500 instead of 401.

The distinction matters operationally. 401 says "you did not authenticate";
503 says "we could not check". Collapsing both into 500 hides a deployment
misconfiguration behind what looks like an application crash.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

ME = "/api/v1/users/me"


def test_missing_token_is_401_even_when_authentication_is_unconfigured(
    client: TestClient,
) -> None:
    """The base test settings configure no Clerk issuer."""
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_malformed_header_is_401_even_when_authentication_is_unconfigured(
    client: TestClient,
) -> None:
    response = client.get(ME, headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert response.status_code == 401


def test_presented_token_reports_503_when_authentication_is_unconfigured(
    client: TestClient,
) -> None:
    """A caller with a credential we cannot verify is not an unauthenticated one.

    Returning 401 here would tell an operator their token is bad when the real
    fault is a missing JIP_AUTH_ISSUER on the server.
    """
    response = client.get(ME, headers={"Authorization": "Bearer a.b.c"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_unconfigured_authentication_never_returns_500(client: TestClient) -> None:
    for headers in ({}, {"Authorization": "Bearer a.b.c"}, {"Authorization": "garbage"}):
        assert client.get(ME, headers=headers).status_code != 500
