"""Model routing, cost estimation, and run tracing."""

from __future__ import annotations

import pytest

from jip_ai.failures import AIFailureCode
from jip_ai.provider import TokenUsage
from jip_ai.routing import AIOperation, ModelPricing, ModelRouter, build_router
from jip_ai.tracing import AIRunTrace, compute_input_hash, timed


def test_routes_the_configured_operation() -> None:
    router = build_router(
        resume_parse_model="test-model",
        resume_parse_max_output_tokens=1234,
        resume_parse_effort="low",
    )

    route = router.route(AIOperation.RESUME_PARSE)

    assert route.model == "test-model"
    assert route.max_output_tokens == 1234
    assert route.effort == "low"


def test_an_unrouted_operation_fails_loudly() -> None:
    """Silently falling back to some default model is how an expensive
    operation ends up on the wrong one without anyone noticing."""
    router = ModelRouter({})

    with pytest.raises(ValueError, match="No model configured"):
        router.route(AIOperation.RESUME_PARSE)


def test_cost_estimate_counts_cached_input_separately() -> None:
    pricing = ModelPricing(
        input_per_million=5.0, output_per_million=25.0, cached_input_per_million=0.5
    )

    cost = pricing.estimate(
        TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=1_000_000)
    )

    assert cost == pytest.approx(30.5)


# --- tracing ------------------------------------------------------------------


def test_input_hash_is_stable() -> None:
    assert compute_input_hash("a", "b") == compute_input_hash("a", "b")


def test_input_hash_separates_its_parts() -> None:
    """Length-prefixed, so a prompt version cannot bleed into a model name.

    Without it, ("ab", "c") and ("a", "bc") would hash identically and a
    re-parse under a new prompt version could reuse the old result.
    """
    assert compute_input_hash("ab", "c") != compute_input_hash("a", "bc")


def test_hash_is_sha256_shaped() -> None:
    digest = compute_input_hash("resume_parser_v1", "model", "text")

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def _trace() -> AIRunTrace:
    return AIRunTrace(
        operation="RESUME_PARSE",
        provider="fake",
        model="test-model",
        prompt_version="resume_parser_v1",
        input_hash="0" * 64,
    )


def test_latency_is_recorded_on_success() -> None:
    trace = _trace()

    with timed(trace):
        trace.mark_success(TokenUsage(input_tokens=10, output_tokens=5), cost=0.01)

    assert trace.succeeded
    assert trace.latency_ms is not None and trace.latency_ms >= 0


def test_latency_is_recorded_when_the_call_raises() -> None:
    """A failed call still cost time, and a trace that only times successes
    cannot answer why a document took two minutes to fail."""
    trace = _trace()

    with pytest.raises(RuntimeError), timed(trace):
        raise RuntimeError("provider exploded")

    assert trace.latency_ms is not None


def test_failure_is_recorded_with_its_code() -> None:
    trace = _trace()
    trace.mark_failure(AIFailureCode.RATE_LIMIT, "slow down")

    assert not trace.succeeded
    assert trace.failure_code is AIFailureCode.RATE_LIMIT
    assert trace.error_message == "slow down"
