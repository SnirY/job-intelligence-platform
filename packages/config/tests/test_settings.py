"""Tests for the shared settings contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jip_config import Environment, Settings

DATABASE_URL = "postgresql+psycopg://jip:secret@localhost:5432/jip"
REDIS_URL = "redis://localhost:6379/0"


def test_required_urls_have_no_default() -> None:
    """A missing database or Redis URL must fail loudly rather than default."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]

    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert {"database_url", "redis_url"} <= missing


def test_comma_separated_lists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("JIP_CORS_ALLOWED_ORIGINS", "http://localhost:3000, https://app.example.com")
    monkeypatch.setenv("JIP_WORKER_QUEUES", "default,high")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == ["http://localhost:3000", "https://app.example.com"]
    assert settings.worker_queues == ["default", "high"]


def test_defaults_are_local_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment is Environment.LOCAL
    assert settings.is_production is False
    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    assert settings.worker_queues == ["default"]


def test_production_environment_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("JIP_ENVIRONMENT", "production")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment is Environment.PRODUCTION
    assert settings.is_production is True
