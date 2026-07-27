"""Retrying the retriable, and nothing else.

``docs/11-engineering-standards.md`` wants background tasks retry-safe, and
``docs/10-api-contracts.md`` wants AI failures classified. Those combine into
one rule: retry only what the classification says could succeed. A retry loop
that ignores the code turns a permanently unparseable document into five
identical charges.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from jip_ai.failures import AIError

logger = logging.getLogger(__name__)


def run_with_retry[T](
    operation: Callable[[int], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``operation`` until it succeeds or stops being worth retrying.

    ``operation`` receives the 1-based attempt number so it can record one trace
    per attempt — a trace that only reports the final outcome hides the fact
    that a "successful" parse cost three calls.

    ``sleep`` is injected so tests exercise the backoff logic without spending
    the wall-clock time it describes.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    last_error: AIError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation(attempt)
        except AIError as error:
            last_error = error
            if not error.is_retriable or attempt == max_attempts:
                raise

            delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            # Jitter, because several documents queued together would otherwise
            # retry in lockstep and rebuild the burst that caused the rate limit.
            delay += random.uniform(0, delay / 2)
            logger.info(
                "Retrying AI call",
                extra={"attempt": attempt, "failure_code": str(error.code), "delay": delay},
            )
            sleep(delay)

    # Unreachable: the loop either returns or raises. Present so the function is
    # total for a type checker rather than falling off the end.
    raise last_error if last_error is not None else RuntimeError("retry loop did not run")
