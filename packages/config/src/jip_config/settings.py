"""Runtime settings shared by the API and the worker.

Configuration is read from the process environment (and, for local development,
from a ``.env`` file at the repository root). Values that have no safe default
are required: a missing database or Redis URL fails loudly at startup instead of
silently falling back to something that only appears to work.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, get_args

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment the process is running in."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


def _optional(annotation: Any) -> bool:
    """Whether a field's type admits ``None``.

    ``str | None`` is a `types.UnionType` at runtime, and `X | None` written in
    a `from __future__ import annotations` module resolves to the same thing by
    the time pydantic has built the field. Checking the resolved annotation
    rather than the source text means a field spelled `Optional[str]` behaves
    identically.
    """
    return type(None) in get_args(annotation)


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

ENV_FILE_VARIABLE = "JIP_ENV_FILE"


def _find_env_file() -> Path | str:
    """Locate the ``.env``, searching upward from the working directory.

    A bare relative ``".env"`` is resolved against the current directory, so
    running a tool from a subdirectory — ``alembic upgrade head`` from
    ``apps/api/``, say — would silently miss the repository's ``.env`` and fail
    with "field required" instead of pointing at the real problem.

    ``JIP_ENV_FILE`` overrides the search. Finding nothing is fine: containers
    and CI pass real environment variables, which take priority over any file.
    """
    override = os.environ.get(ENV_FILE_VARIABLE)
    if override:
        return Path(override)

    start = Path.cwd().resolve()
    for directory in (start, *start.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate

    return ".env"


class Settings(BaseSettings):
    """Backend runtime settings.

    All variables use the ``JIP_`` prefix so platform configuration is easy to
    distinguish from unrelated environment variables on shared hosts.
    """

    model_config = SettingsConfigDict(
        env_prefix="JIP_",
        env_file=_find_env_file(),
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

    # --- Object storage (S3-compatible) ---
    # Uploaded files never go in the database (docs/04-system-architecture.md).
    # Endpoint URL is configurable so the same adapter serves AWS S3, MinIO,
    # and R2 without a code change.
    storage_bucket: str | None = None
    storage_endpoint_url: str | None = Field(
        default=None,
        description="Leave unset for AWS S3; set for MinIO or another S3-compatible service.",
    )
    storage_region: str = "us-east-1"
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_signed_url_ttl_seconds: int = 900
    storage_server_side_encryption: str | None = Field(
        default=None,
        description=(
            'Sent as ServerSideEncryption on upload when set, e.g. "AES256" or "aws:kms". '
            "Leave unset for S3 implementations without a key service — MinIO answers "
            "NotImplemented — and note AWS S3 encrypts at rest by default."
        ),
    )

    # --- Uploads ---
    max_upload_bytes: int = 10 * 1024 * 1024
    """Refused above this size.

    Bounded because an unbounded upload is a denial-of-service vector: the file
    is read into memory to hash and scan it before anything is stored.
    """

    # --- AI ---
    # Model routing is configuration, not code (docs/05-ai-and-matching.md), so
    # a cost or quality decision can be revisited without a deploy.
    ai_provider: str = Field(
        default="anthropic",
        description="Which LLM adapter to build. Recorded on every AIRun.",
    )
    ai_api_key: str | None = Field(
        default=None,
        description=(
            "Provider API key. With none set, AI features fail with a clear "
            "PROVIDER_ERROR instead of silently returning nothing."
        ),
    )
    ai_request_timeout_seconds: float = 120.0
    """Generous, because parsing a long resume is a slow call — but bounded, so
    a wedged provider surfaces as a classified TIMEOUT rather than a worker
    thread stuck forever."""

    ai_max_attempts: int = 3
    """Attempts per AI operation, including the first. Each one is traced."""

    ai_resume_parse_model: str = "claude-opus-5"
    ai_resume_parse_max_output_tokens: int = 16000
    ai_resume_parse_effort: str | None = Field(
        default="medium",
        description=(
            "Reasoning depth for resume parsing, when the provider exposes one. "
            "Extraction rarely needs the ceiling; unset to use the provider default."
        ),
    )

    # Job intelligence routes two operations, because they are two different
    # tasks: parsing reads the posting, analysis interprets it. Empty falls back
    # to the resume model, so adding these did not change what a deployment that
    # has not set them runs.
    ai_job_parse_model: str | None = None
    ai_job_parse_max_output_tokens: int = 16000
    ai_job_parse_effort: str | None = "medium"

    ai_job_analysis_model: str | None = None
    ai_job_analysis_max_output_tokens: int = 4000
    """Smaller than a parse on purpose: the analysis returns a handful of fields
    and its reasoning, not every requirement in the posting."""

    # Explanation only, and short: the model restates a decided result rather
    # than producing one, so it needs neither a big budget nor deep reasoning.
    ai_match_explain_model: str | None = None
    ai_match_explain_max_output_tokens: int = 1000
    ai_match_explain_effort: str | None = None

    # Tailoring routes two operations, because docs/09-mvp-roadmap.md forbids
    # one call that rewrites a document. Rewriting gets the larger budget: it
    # returns a suggestion per line, where strategy returns one plan.
    ai_resume_strategy_model: str | None = None
    ai_resume_strategy_max_output_tokens: int = 3000
    ai_resume_strategy_effort: str | None = "medium"

    ai_resume_rewrite_model: str | None = None
    ai_resume_rewrite_max_output_tokens: int = 8000
    ai_resume_rewrite_effort: str | None = "medium"

    ai_job_analysis_effort: str | None = Field(
        default="medium",
        description=(
            "Reasoning depth for job analysis. Seniority is a judgement from "
            "several weak signals, which is the case for reasoning if there is one."
        ),
    )

    # --- Job URL import ---
    # Fetching a page the user chose is the one place the server talks to an
    # address it did not pick. Both bounds are denial-of-service controls, not
    # product limits: without them a slow or enormous page is something the
    # user can point the worker at.
    job_fetch_timeout_seconds: float = 15.0
    job_fetch_max_bytes: int = 3 * 1024 * 1024

    ai_max_input_chars: int = 60_000
    """Ceiling on the document text sent to a model.

    A resume is a few thousand characters; anything near this limit is a
    different kind of document. Truncation is reported to the user as a warning
    rather than hidden, so a partial parse is never presented as a full one.
    """

    # How long a processing job may sit in each state before it is presumed
    # dead. DEV-013: a worker that raised before writing a status left the row
    # PENDING forever, with no retry, no cancel, and nothing to age it out.
    #
    # The two differ by an order of magnitude on purpose. A job that was never
    # picked up is stuck the moment the queue is being drained at all, so five
    # minutes is already generous. A job that started is doing real work — a
    # resume parse with retries and backoff takes minutes legitimately — and
    # killing it early would turn a slow success into a reported failure.
    processing_pending_timeout_seconds: int = 300
    processing_running_timeout_seconds: int = 1800

    _split_origins = field_validator("cors_allowed_origins", mode="before")(_split_csv)
    _split_queues = field_validator("worker_queues", mode="before")(_split_csv)
    _split_parties = field_validator("auth_authorized_parties", mode="before")(_split_csv)

    @field_validator("*", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: Any, info: ValidationInfo) -> Any:
        """Treat an empty environment variable as absent, for optional strings.

        DEV-039. An optional setting has three states — absent, empty, and set —
        and this code handled two. Pydantic resolves ``JIP_AI_..._EFFORT=`` to
        ``""`` rather than ``None``, and the provider asks
        ``if request.effort is not None``, so an empty value was forwarded to the
        API as a literal effort level.

        Every ``.env.example`` comment already promises the opposite: *"leave
        empty to use the provider's own default"*. Worse, the file ships
        ``JIP_AI_MATCH_EXPLAIN_EFFORT=`` empty, taking its own advice — so
        ``cp .env.example .env``, the first line of the README quick start,
        produced a deployment sending ``effort: ""`` on every match explanation.

        Fixed here rather than at each call site, because "empty means unset" is
        a property of how this project reads its environment, and the version
        written at one call site is the version the next one forgets.

        **Only for fields that can actually be unset.** A required string with an
        empty value is a misconfiguration, and turning it into ``None`` would
        swap a clear "field required" for a confusing type error.
        """
        if value != "":
            return value

        annotation = cls.model_fields[info.field_name].annotation if info.field_name else None
        return None if _optional(annotation) else value

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

    @property
    def ai_configured(self) -> bool:
        """Whether a model call could be made at all."""
        return bool(self.ai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so configuration is resolved once per process. Tests that need a
    different configuration should construct :class:`Settings` directly or call
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
