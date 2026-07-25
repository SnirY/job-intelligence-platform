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

    # --- Authentication ---
    # Provider-neutral on purpose: these are OIDC concepts, not vendor ones, so
    # moving to a different issuer is configuration rather than code.
    # See docs/adr/0004-clerk-as-authentication-provider.md and ADR-0005.
    #
    # Verification is offline against a public JWKS, so no provider secret
    # belongs here. The API image deliberately carries no auth credential.
    auth_provider: str = Field(
        default="clerk",
        description="Identifier stored on new users, recording which issuer vouched for them.",
    )
    auth_issuer: str | None = Field(
        default=None,
        description="Expected `iss` claim, e.g. https://your-app.clerk.accounts.dev",
    )
    auth_authorized_parties: CommaSeparated = Field(
        default_factory=list,
        description="Permitted `azp` values, i.e. the origins allowed to use this API.",
    )
    auth_jwks_url: str | None = Field(
        default=None,
        description="Overrides the JWKS URL derived from auth_issuer.",
    )
    auth_jwks_cache_seconds: int = 3600
    auth_leeway_seconds: int = 5

    _split_origins = field_validator("cors_allowed_origins", mode="before")(_split_csv)
    _split_queues = field_validator("worker_queues", mode="before")(_split_csv)
    _split_parties = field_validator("auth_authorized_parties", mode="before")(_split_csv)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def resolved_auth_jwks_url(self) -> str:
        """JWKS document location.

        Derived from the issuer unless explicitly overridden. Raises rather than
        returning a placeholder: a wrong JWKS URL means every token fails to
        verify, and that is far easier to diagnose at startup than as a blanket
        401 at runtime.
        """
        if self.auth_jwks_url:
            return self.auth_jwks_url
        if not self.auth_issuer:
            raise ValueError(
                "Authentication is not configured: set JIP_AUTH_ISSUER (or JIP_AUTH_JWKS_URL)."
            )
        return f"{self.auth_issuer.rstrip('/')}/.well-known/jwks.json"

    @property
    def authentication_configured(self) -> bool:
        return bool(self.auth_issuer or self.auth_jwks_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so configuration is resolved once per process. Tests that need a
    different configuration should construct :class:`Settings` directly or call
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
