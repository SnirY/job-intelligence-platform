"""Wiring for the Anthropic adapter.

Separated from ``factory`` so the import of the provider SDK happens only when
that provider is actually selected.
"""

from __future__ import annotations

from jip_ai.providers.anthropic import AnthropicProvider, build_anthropic_client
from jip_config import Settings


def build_anthropic_provider(settings: Settings) -> AnthropicProvider:
    """Construct the adapter with a configured client."""
    assert settings.ai_api_key is not None  # checked by the caller
    return AnthropicProvider(
        build_anthropic_client(
            settings.ai_api_key,
            timeout_seconds=settings.ai_request_timeout_seconds,
        )
    )
