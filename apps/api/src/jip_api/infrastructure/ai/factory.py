"""Building the AI provider and router from configuration.

Infrastructure: it is the only place that knows which adapter is in use.
Application services take an ``LLMProvider`` and a ``ModelRouter`` as arguments,
which is what lets a test pass a fake without patching anything.
"""

from __future__ import annotations

from functools import lru_cache

from jip_ai import AIError, AIFailureCode, LLMProvider, ModelRouter, build_router
from jip_config import Settings, get_settings


def build_provider(settings: Settings) -> LLMProvider:
    """Construct the configured provider.

    Raises a classified :class:`AIError` when AI is unconfigured, rather than
    returning a stub that answers plausibly. ``docs/11-engineering-standards.md``
    is explicit: never return fake intelligence when AI is unavailable.
    """
    if not settings.ai_api_key:
        raise AIError(
            AIFailureCode.PROVIDER_ERROR,
            "AI is not configured on this server.",
            details="JIP_AI_API_KEY is unset",
        )

    if settings.ai_provider == "anthropic":
        from jip_api.infrastructure.ai.anthropic_provider import build_anthropic_provider

        return build_anthropic_provider(settings)

    raise AIError(
        AIFailureCode.PROVIDER_ERROR,
        "AI is not configured on this server.",
        details=f"unknown provider {settings.ai_provider!r}",
    )


def build_model_router(settings: Settings) -> ModelRouter:
    """Construct the routing table from settings."""
    return build_router(
        resume_parse_model=settings.ai_resume_parse_model,
        resume_parse_max_output_tokens=settings.ai_resume_parse_max_output_tokens,
        resume_parse_effort=settings.ai_resume_parse_effort or None,
        job_parse_model=settings.ai_job_parse_model or None,
        job_parse_max_output_tokens=settings.ai_job_parse_max_output_tokens,
        job_parse_effort=settings.ai_job_parse_effort or None,
        job_analysis_model=settings.ai_job_analysis_model or None,
        job_analysis_max_output_tokens=settings.ai_job_analysis_max_output_tokens,
        job_analysis_effort=settings.ai_job_analysis_effort or None,
    )


@lru_cache(maxsize=1)
def get_model_router() -> ModelRouter:
    """Process-wide router. Cheap to build, but cached for consistency with the
    other factories so a settings change is picked up in one place."""
    return build_model_router(get_settings())


@lru_cache(maxsize=1)
def get_ai_provider() -> LLMProvider:
    """Process-wide provider.

    Cached because the underlying SDK client holds a connection pool; building
    one per document would open a fresh pool for every upload.
    """
    return build_provider(get_settings())


def reset_ai_caches() -> None:
    """Drop the cached provider and router. Used by tests that reconfigure AI."""
    get_ai_provider.cache_clear()
    get_model_router.cache_clear()
