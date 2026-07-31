"""Building the provider, and what happens when it cannot be built.

DEV-021. Both failures here are configuration, and configuration does not fix
itself between attempts. Marked permanent so the UI does not offer a retry
button that cannot possibly work — which is what it did, indefinitely, because
the failure happens before the job records an attempt and the counter therefore
never advanced past "attempt 0 of 5".
"""

from __future__ import annotations

import pytest

from jip_ai import AIError, AIFailureCode
from jip_api.infrastructure.ai.factory import build_provider
from jip_config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://x/y",
            "auth_issuer": "https://example.test",
            **overrides,
        }
    )


def test_a_missing_key_is_a_permanent_failure() -> None:
    with pytest.raises(AIError) as caught:
        build_provider(_settings(ai_api_key=""))

    assert caught.value.code is AIFailureCode.PROVIDER_ERROR
    assert caught.value.is_retriable is False, "no number of retries sets an env var"


def test_the_message_names_the_cause_for_an_operator() -> None:
    """The user cannot act on this; the person running the server can."""
    with pytest.raises(AIError) as caught:
        build_provider(_settings(ai_api_key=""))

    assert "not configured" in str(caught.value.args[0])
    assert caught.value.details is not None and "JIP_AI_API_KEY" in caught.value.details


def test_an_unknown_provider_is_also_permanent() -> None:
    with pytest.raises(AIError) as caught:
        build_provider(_settings(ai_api_key="sk-test", ai_provider="not-a-provider"))

    assert caught.value.is_retriable is False
