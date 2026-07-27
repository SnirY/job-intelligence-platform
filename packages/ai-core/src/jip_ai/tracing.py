"""Recording what each AI call did.

``docs/09-mvp-roadmap.md`` gates AI features on a run trace. The dataclass here
is deliberately persistence-free — ``jip_ai`` must not know about SQLAlchemy —
so the API layer maps it onto the ``ai_runs`` table.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from jip_ai.failures import AIFailureCode
from jip_ai.provider import TokenUsage


def compute_input_hash(*parts: str) -> str:
    """Stable hash of everything that determines a result.

    Callers pass the prompt version, the model, and the rendered input.
    ``docs/10-api-contracts.md`` asks for input hashes on expensive repeatable
    operations, and this is what lets a re-upload of an identical resume reuse
    a stored extraction instead of paying for the same call twice.

    Parts are length-prefixed so ("ab", "c") and ("a", "bc") hash differently —
    plain concatenation would make a prompt version bleed into a model name.
    """
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
    return digest.hexdigest()


@dataclass(slots=True)
class AIRunTrace:
    """One attempt at one operation, successful or not.

    Mutable, unlike most types here: it is filled in as the call proceeds, and
    it has to be completable from an exception handler.
    """

    operation: str
    provider: str
    model: str
    prompt_version: str
    input_hash: str

    attempt: int = 1
    succeeded: bool = False
    failure_code: AIFailureCode | None = None
    error_message: str | None = None
    latency_ms: int | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float | None = None

    def mark_success(self, usage: TokenUsage, *, cost: float | None) -> None:
        self.succeeded = True
        self.usage = usage
        self.estimated_cost_usd = cost

    def mark_failure(self, code: AIFailureCode, message: str) -> None:
        self.succeeded = False
        self.failure_code = code
        self.error_message = message


@contextmanager
def timed(trace: AIRunTrace) -> Iterator[AIRunTrace]:
    """Record elapsed time on ``trace``, including when the call raises.

    A monotonic clock, so a system time adjustment mid-call cannot produce a
    negative latency.
    """
    started = time.perf_counter()
    try:
        yield trace
    finally:
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
