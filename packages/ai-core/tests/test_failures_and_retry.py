"""Failure classification and retry.

The pair matters more than either alone: retrying is driven entirely by the
classification, so a wrong code means either a permanently broken document is
retried five times, or a transient blip is reported as final.
"""

from __future__ import annotations

import pytest

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.retry import run_with_retry


@pytest.mark.parametrize(
    "code",
    [
        AIFailureCode.PROVIDER_ERROR,
        AIFailureCode.RATE_LIMIT,
        AIFailureCode.TIMEOUT,
        AIFailureCode.INVALID_OUTPUT,
        AIFailureCode.VALIDATION_FAILURE,
    ],
)
def test_transient_failures_are_retriable(code: AIFailureCode) -> None:
    assert AIError(code, "boom").is_retriable


def test_content_unavailable_is_not_retriable() -> None:
    """A document with no text will not grow any on a second attempt."""
    assert not AIError(AIFailureCode.CONTENT_UNAVAILABLE, "no text").is_retriable


def test_an_explicit_override_beats_the_codes_default() -> None:
    """DEV-015. PROVIDER_ERROR covers both "could not reach it" and "it
    answered with an error", and those differ exactly on whether waiting
    helps."""
    assert not AIError(AIFailureCode.PROVIDER_ERROR, "refused", retriable=False).is_retriable
    assert AIError(AIFailureCode.CONTENT_UNAVAILABLE, "odd", retriable=True).is_retriable


def test_an_absent_override_leaves_the_default_alone() -> None:
    assert AIError(AIFailureCode.PROVIDER_ERROR, "unreachable").is_retriable


def test_a_permanent_provider_error_costs_exactly_one_call() -> None:
    """The concrete cost DEV-015 recorded: five live calls against a billing
    limit that no wait could clear."""
    attempts: list[int] = []

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise AIError(AIFailureCode.PROVIDER_ERROR, "refused", retriable=False)

    with pytest.raises(AIError):
        run_with_retry(operation, max_attempts=5, sleep=lambda _: None)

    assert attempts == [1]


def test_returns_the_first_success() -> None:
    calls: list[int] = []

    def operation(attempt: int) -> str:
        calls.append(attempt)
        return "ok"

    result = run_with_retry(operation, sleep=lambda _: None)

    assert result == "ok"
    assert calls == [1]


def test_retries_a_retriable_failure_then_succeeds() -> None:
    attempts: list[int] = []

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        if attempt == 1:
            raise AIError(AIFailureCode.RATE_LIMIT, "slow down")
        return "recovered"

    result = run_with_retry(operation, max_attempts=3, sleep=lambda _: None)

    assert result == "recovered"
    assert attempts == [1, 2]


def test_does_not_retry_a_permanent_failure() -> None:
    attempts: list[int] = []

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise AIError(AIFailureCode.CONTENT_UNAVAILABLE, "nothing to read")

    with pytest.raises(AIError) as caught:
        run_with_retry(operation, max_attempts=5, sleep=lambda _: None)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert attempts == [1], "a permanent failure must cost exactly one call"


def test_gives_up_after_max_attempts() -> None:
    attempts: list[int] = []

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise AIError(AIFailureCode.TIMEOUT, "too slow")

    with pytest.raises(AIError):
        run_with_retry(operation, max_attempts=3, sleep=lambda _: None)

    assert attempts == [1, 2, 3]


def test_backoff_grows_between_attempts() -> None:
    delays: list[float] = []

    def operation(attempt: int) -> str:
        raise AIError(AIFailureCode.RATE_LIMIT, "slow down")

    with pytest.raises(AIError):
        run_with_retry(
            operation,
            max_attempts=4,
            base_delay_seconds=1.0,
            sleep=delays.append,
        )

    assert len(delays) == 3
    # Jittered, so exact values are not asserted — only that each wait is longer
    # than the last, which is what stops a rate limit being hammered.
    assert delays[0] < delays[1] < delays[2]


def test_rejects_a_nonsensical_attempt_count() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run_with_retry(lambda _: "never", max_attempts=0)
