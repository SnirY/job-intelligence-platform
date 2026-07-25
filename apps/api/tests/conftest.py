"""Shared fixtures for API tests.

Settings are resolved from the environment at import time by cached factories,
so every test module that builds the app must run with a predictable
configuration. ``_isolated_settings`` guarantees that.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jip_api.infrastructure.db.session import reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://unused:unused@127.0.0.1:1/unused"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


def _clear_caches() -> None:
    get_settings.cache_clear()
    reset_engine_cache()
    reset_task_caches()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give each test a clean, explicitly configured settings instance.

    The URLs always point at unroutable endpoints, never at whatever the
    developer or CI has configured: a unit test asserting "the dependency is
    down" must actually find it down, and a test that reaches a real database by
    accident must fail rather than quietly pass. Integration tests opt in to
    live infrastructure by overriding these in their own fixtures.
    """
    monkeypatch.setenv("JIP_ENVIRONMENT", "test")
    monkeypatch.setenv("JIP_DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", UNREACHABLE_REDIS_URL)
    monkeypatch.setenv("JIP_CONNECT_TIMEOUT_SECONDS", "1")

    # Authentication is left unconfigured, and pinned so explicitly because the
    # settings loader reads a repository .env when one exists. A developer with
    # working local credentials would otherwise silently invert the tests that
    # assert unconfigured behaviour — they would pass on CI and on a fresh
    # clone, and fail only on the machine that has a .env. Environment
    # variables take priority over the file, so empty values win here.
    monkeypatch.setenv("JIP_AUTH_ISSUER", "")
    monkeypatch.setenv("JIP_AUTH_JWKS_URL", "")
    monkeypatch.setenv("JIP_AUTH_AUTHORIZED_PARTIES", "")

    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def app() -> FastAPI:
    from jip_api.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False exercises the real 500 handler instead of
    # letting the exception propagate into the test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
