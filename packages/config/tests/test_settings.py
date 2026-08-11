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


# --- an empty value is not a value (DEV-039) ----------------------------------


def test_an_empty_optional_setting_reads_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEV-039, and the case that shipped.

    `.env.example` documents "leave empty to use the provider's own default" and
    then ships `JIP_AI_MATCH_EXPLAIN_EFFORT=` empty, taking its own advice.
    Pydantic resolved that to `""`, the provider asks `if effort is not None`,
    and an empty string went to the API as a literal effort level.
    """
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("JIP_AI_MATCH_EXPLAIN_EFFORT", "")
    monkeypatch.setenv("JIP_AI_RESUME_PARSE_EFFORT", "")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.ai_match_explain_effort is None
    assert settings.ai_resume_parse_effort is None


def test_a_set_optional_setting_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The normalisation must not eat real values."""
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("JIP_AI_RESUME_PARSE_EFFORT", "high")

    assert Settings(_env_file=None).ai_resume_parse_effort == "high"  # type: ignore[call-arg]


def test_an_empty_required_setting_is_not_turned_into_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A required string set to empty is a misconfiguration, and `None` would
    swap a clear "field required" for a confusing type error.

    `log_level` is the case: it has a default, but it cannot be `None`.
    """
    monkeypatch.setenv("JIP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JIP_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("JIP_LOG_LEVEL", "")

    assert Settings(_env_file=None).log_level == ""  # type: ignore[call-arg]
