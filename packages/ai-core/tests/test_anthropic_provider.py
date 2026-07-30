"""The Anthropic adapter, against a stub client.

No network and no key. What is under test is the adapter's own logic: how it
builds a request, how it reads a response, and — the part that matters most —
how it maps provider exceptions onto the documented failure taxonomy.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.provider import StructuredRequest
from jip_ai.providers.anthropic import AnthropicProvider

SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def request() -> StructuredRequest:
    return StructuredRequest(
        system="system", user="user", json_schema=SCHEMA, max_output_tokens=1000, effort="medium"
    )


def message(
    text: str, *, stop_reason: str = "end_turn", usage: SimpleNamespace | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model="test-model",
        usage=usage
        or SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=20),
    )


class StubClient:
    """Records the call and returns (or raises) what the test set up."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_returns_the_parsed_payload_and_usage() -> None:
    client = StubClient(message(json.dumps({"skills": [{"name": "Python"}]})))

    result = AnthropicProvider(client).generate_structured(request(), model="test-model")

    assert result.payload == {"skills": [{"name": "Python"}]}
    assert result.usage.input_tokens == 100
    assert result.usage.cached_input_tokens == 20


def test_sends_the_schema_and_effort() -> None:
    client = StubClient(message("{}"))

    AnthropicProvider(client).generate_structured(request(), model="test-model")

    sent = client.calls[0]
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["output_config"]["effort"] == "medium"
    assert sent["max_tokens"] == 1000


def test_effort_is_omitted_when_unset() -> None:
    """Sending a guessed value would override the provider's own default."""
    client = StubClient(message("{}"))
    plain = StructuredRequest(system="s", user="u", json_schema=SCHEMA)

    AnthropicProvider(client).generate_structured(plain, model="test-model")

    assert "effort" not in client.calls[0]["output_config"]


def test_concatenates_text_blocks_and_skips_others() -> None:
    """Responses interleave block types; indexing content[0] reads whichever
    block happened to come first."""
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="considering"),
            SimpleNamespace(type="text", text='{"a":'),
            SimpleNamespace(type="text", text=" 1}"),
        ],
        stop_reason="end_turn",
        model="test-model",
        usage=None,
    )

    result = AnthropicProvider(StubClient(response)).generate_structured(
        request(), model="test-model"
    )

    assert result.payload == {"a": 1}


def test_truncated_output_is_reported_as_invalid() -> None:
    client = StubClient(message('{"skills": [', stop_reason="max_tokens"))

    with pytest.raises(AIError) as caught:
        AnthropicProvider(client).generate_structured(request(), model="test-model")

    assert caught.value.code is AIFailureCode.INVALID_OUTPUT
    assert "cut off" in str(caught.value)


def test_a_refusal_is_content_unavailable() -> None:
    """Not a transient fault: the same document would be declined again, so
    retrying it would only spend money."""
    client = StubClient(message("", stop_reason="refusal"))

    with pytest.raises(AIError) as caught:
        AnthropicProvider(client).generate_structured(request(), model="test-model")

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert not caught.value.is_retriable


@pytest.mark.parametrize(
    ("exception_name", "expected"),
    [
        ("RateLimitError", AIFailureCode.RATE_LIMIT),
        ("APITimeoutError", AIFailureCode.TIMEOUT),
        ("AuthenticationError", AIFailureCode.PROVIDER_ERROR),
        ("APIConnectionError", AIFailureCode.PROVIDER_ERROR),
        ("SomethingElseEntirely", AIFailureCode.PROVIDER_ERROR),
    ],
)
def test_provider_exceptions_are_classified(exception_name: str, expected: AIFailureCode) -> None:
    exception_type = type(exception_name, (Exception,), {})
    client = StubClient(exception_type("boom"))

    with pytest.raises(AIError) as caught:
        AnthropicProvider(client).generate_structured(request(), model="test-model")

    assert caught.value.code is expected


def test_a_429_status_is_a_rate_limit_even_under_another_class_name() -> None:
    error = type("WeirdError", (Exception,), {})("too many")
    error.status_code = 429

    with pytest.raises(AIError) as caught:
        AnthropicProvider(StubClient(error)).generate_structured(request(), model="test-model")

    assert caught.value.code is AIFailureCode.RATE_LIMIT


def _status_error(status: int, message: str) -> Exception:
    error: Exception = type("WeirdError", (Exception,), {})(message)
    error.status_code = status  # type: ignore[attr-defined]
    return error


def test_a_4xx_is_permanent_and_says_so() -> None:
    """DEV-015. A 400 means the provider read the request and refused it, so
    retrying spends live calls on a guaranteed failure — and the old message
    blamed connectivity for a billing problem."""
    error = _status_error(400, "Your credit balance is too low to access the Anthropic API.")

    with pytest.raises(AIError) as caught:
        AnthropicProvider(StubClient(error)).generate_structured(request(), model="test-model")

    assert caught.value.is_retriable is False
    assert "could not be reached" not in str(caught.value.args[0])
    assert "will not change the outcome" in str(caught.value.args[0])


def test_the_providers_own_explanation_survives_on_a_4xx() -> None:
    """It names the cause — a billing limit, a schema it will not compile — and
    it is the only record of why. It stays out of the user-facing message and
    goes to the log instead."""
    error = _status_error(400, "The compiled grammar is too large.")

    with pytest.raises(AIError) as caught:
        AnthropicProvider(StubClient(error)).generate_structured(request(), model="test-model")

    assert caught.value.details is not None
    assert "compiled grammar is too large" in caught.value.details
    assert "compiled grammar" not in str(caught.value.args[0])


def test_a_429_stays_retriable_despite_being_a_4xx() -> None:
    """The one 4xx that waiting does fix."""
    with pytest.raises(AIError) as caught:
        AnthropicProvider(StubClient(_status_error(429, "slow down"))).generate_structured(
            request(), model="test-model"
        )

    assert caught.value.code is AIFailureCode.RATE_LIMIT
    assert caught.value.is_retriable is True


def test_a_5xx_stays_retriable() -> None:
    """A server fault genuinely is the provider having a bad moment."""
    with pytest.raises(AIError) as caught:
        AnthropicProvider(
            StubClient(_status_error(503, "upstream unavailable"))
        ).generate_structured(request(), model="test-model")

    assert caught.value.code is AIFailureCode.PROVIDER_ERROR
    assert caught.value.is_retriable is True


def test_an_unclassified_failure_keeps_the_retriable_default() -> None:
    """Nothing about the override changes failures that carry no HTTP status."""
    with pytest.raises(AIError) as caught:
        AnthropicProvider(StubClient(RuntimeError("socket died"))).generate_structured(
            request(), model="test-model"
        )

    assert caught.value.is_retriable is True


def test_provider_detail_is_not_in_the_user_message() -> None:
    """Provider text can carry request ids and internal detail, which
    docs/10-api-contracts.md keeps out of client responses."""
    client = StubClient(type("RateLimitError", (Exception,), {})("org_abc123 quota exceeded"))

    with pytest.raises(AIError) as caught:
        AnthropicProvider(client).generate_structured(request(), model="test-model")

    assert "org_abc123" not in str(caught.value.args[0])
    assert caught.value.details is not None and "org_abc123" in caught.value.details
