"""Liveness endpoint and readiness failure behaviour.

The readiness cases here run against deliberately unreachable dependencies, so
they assert the failure contract without needing live infrastructure. The
success path is covered in ``tests/integration/test_readiness.py``.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from jip_api import __version__
from jip_api.core.context import REQUEST_ID_HEADER


def test_health_reports_service_metadata(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "ok",
            "service": "api",
            "version": __version__,
            "environment": "test",
        }
    }


def test_health_does_not_require_dependencies(client: TestClient) -> None:
    """Liveness must stay green when PostgreSQL and Redis are unreachable.

    Otherwise an orchestrator restarts a healthy API process every time a
    downstream dependency has a bad minute.
    """
    assert client.get("/api/v1/health").status_code == 200


def test_readiness_reports_503_when_dependencies_are_down(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_UNAVAILABLE"
    assert set(error["details"]["unavailable"]) == {"database", "redis"}
    assert error["details"]["dependencies"]["database"]["status"] == "unavailable"
    assert error["details"]["dependencies"]["redis"]["status"] == "unavailable"


def test_readiness_probe_is_bounded_when_dependencies_hang(client: TestClient) -> None:
    """Regression: an unbounded probe took over two minutes to answer.

    Connect timeouts (``JIP_CONNECT_TIMEOUT_SECONDS``, set to 1s by the test
    fixture) cap it. Without them an orchestrator's readiness check times out
    instead of receiving the 503 that tells it what is actually wrong.
    """
    started = time.perf_counter()
    response = client.get("/api/v1/health/ready")
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert elapsed < 15, f"readiness probe took {elapsed:.1f}s with a 1s connect timeout"


def test_readiness_failure_carries_the_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready", headers={REQUEST_ID_HEADER: "probe-123"})

    assert response.headers[REQUEST_ID_HEADER] == "probe-123"
    assert response.json()["error"]["request_id"] == "probe-123"
