"""Readiness against live PostgreSQL and Redis."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jip_api.infrastructure.db.session import get_engine, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def live_client(postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("JIP_DATABASE_URL", postgres_url)
    monkeypatch.setenv("JIP_REDIS_URL", redis_url)
    get_settings.cache_clear()
    reset_engine_cache()
    reset_task_caches()

    from jip_api.main import create_app

    return TestClient(create_app())


def test_readiness_is_green_with_live_dependencies(live_client: TestClient) -> None:
    response = live_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "ready",
            "dependencies": {
                "database": {"status": "ok", "detail": None},
                "redis": {"status": "ok", "detail": None},
            },
        }
    }


def test_engine_executes_a_real_query(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves the configured driver and URL actually reach PostgreSQL."""
    import sqlalchemy

    monkeypatch.setenv("JIP_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    reset_engine_cache()

    with get_engine().connect() as connection:
        assert connection.execute(sqlalchemy.text("SELECT 1")).scalar_one() == 1
        version = connection.execute(sqlalchemy.text("SHOW server_version")).scalar_one()

    assert version
