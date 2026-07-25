"""The error envelope defined in ``docs/10-api-contracts.md``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from jip_api.core.context import REQUEST_ID_HEADER
from jip_api.core.errors import APIError


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_failure_returns_422_with_details(app: FastAPI) -> None:
    @app.get("/api/v1/_test/validated")
    def _validated(count: int) -> dict[str, int]:  # pragma: no cover - invoked via HTTP
        return {"count": count}

    with TestClient(app) as client:
        response = client.get("/api/v1/_test/validated", params={"count": "not-a-number"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]


def test_api_error_maps_to_its_declared_status_and_code(app: FastAPI) -> None:
    class TeapotError(APIError):
        status_code = status.HTTP_409_CONFLICT
        code = "ALREADY_EXISTS"
        message = "That resource already exists."

    @app.get("/api/v1/_test/conflict")
    def _conflict() -> None:  # pragma: no cover - invoked via HTTP
        raise TeapotError(details={"field": "name"})

    with TestClient(app) as client:
        response = client.get("/api/v1/_test/conflict")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "ALREADY_EXISTS",
        "message": "That resource already exists.",
        "details": {"field": "name"},
        "request_id": response.headers[REQUEST_ID_HEADER],
    }


def test_unexpected_exception_does_not_leak_internal_detail(app: FastAPI) -> None:
    @app.get("/api/v1/_test/boom")
    def _boom() -> None:  # pragma: no cover - invoked via HTTP
        raise RuntimeError("connection string postgres://user:hunter2@db/prod")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/_test/boom")

    assert response.status_code == 500
    body = response.text
    assert "hunter2" not in body
    assert "RuntimeError" not in body
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize("supplied", ["abc-123", None])
def test_every_response_carries_a_request_id(client: TestClient, supplied: str | None) -> None:
    headers = {REQUEST_ID_HEADER: supplied} if supplied else {}
    response = client.get("/api/v1/health", headers=headers)

    returned = response.headers[REQUEST_ID_HEADER]
    assert returned
    if supplied:
        assert returned == supplied


def test_validator_raising_value_error_yields_422_not_500(app: FastAPI) -> None:
    """Regression: a custom field_validator used to produce a 500.

    Pydantic puts the raised ValueError object into the error's ``ctx``.
    Serialising that directly fails, so the 422 became an unhandled 500 — and
    the caller was told the server had broken when their input was simply
    invalid.
    """
    from pydantic import BaseModel, field_validator

    class Body(BaseModel):
        name: str

        @field_validator("name")
        @classmethod
        def not_blank(cls, value: str) -> str:
            if not value.strip():
                raise ValueError("name must not be blank")
            return value

    @app.post("/api/v1/_test/custom-validator")
    def _endpoint(body: Body) -> dict[str, str]:  # pragma: no cover - invoked via HTTP
        return {"name": body.name}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/_test/custom-validator", json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]
