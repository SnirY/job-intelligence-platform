"""Runtime settings shared by the API and the worker.

Configuration is read from the process environment (and, for local development,
from a ``.env`` file at the repository root). Values that have no safe default
are required: a missing database or Redis URL fails loudly at startup instead of
silently falling back to something that only appears to work.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment the process is running in."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


def _split_csv(value: Any) -> Any:
    """Parse a comma-separated environment value into a list of strings.

    Environment variables cannot carry native lists, and the JSON form that
    pydantic-settings expects by default is awkward to write in ``.env`` files
    and Compose manifests. Anything that is not a string is passed through
    untouched so programmatic construction keeps working.
    """
    if not isinstance(value, str):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


# NoDecode stops pydantic-settings from JSON-decoding the raw environment value
# before validation, which is what lets _split_csv see the comma-separated form.
CommaSeparated = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Backend runtime settings.

    All variables use the ``JIP_`` prefix so platform configuration is easy to
    distinguish from unrelated environment variables on shared hosts.
    """

    model_config = SettingsConfigDict(
        env_prefix="JIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"

    database_url: str = Field(
        description="SQLAlchemy URL for PostgreSQL, e.g. postgresql+psycopg://user:pass@host:5432/db",
    )
    redis_url: str = Field(
        description="Redis URL used for the RQ task queue, e.g. redis://host:6379/0",
    )

    # A readiness probe must answer quickly even when a dependency is wedged:
    # without a bound, an unreachable host turns "is this ready" into a request
    # that hangs for minutes instead of reporting the outage.
    connect_timeout_seconds: int = 5

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_allowed_origins: CommaSeparated = Field(default_factory=lambda: ["http://localhost:3000"])

    worker_queues: CommaSeparated = Field(default_factory=lambda: ["default"])

    _split_origins = field_validator("cors_allowed_origins", mode="before")(_split_csv)
    _split_queues = field_validator("worker_queues", mode="before")(_split_csv)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so configuration is resolved once per process. Tests that need a
    different configuration should construct :class:`Settings` directly or call
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
