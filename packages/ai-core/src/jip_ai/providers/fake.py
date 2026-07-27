"""A provider that answers from a script.

``docs/11-engineering-standards.md`` forbids live model calls in the normal test
suite. This is how the whole parse path — prompt rendering, structured parsing,
schema and business validation, tracing, retry — is exercised deterministically.

It ships in the package rather than in a test directory because the evaluation
suite and any local run without a key need it too.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from typing import Any

from jip_ai.failures import AIError
from jip_ai.provider import StructuredRequest, StructuredResult, TokenUsage

PROVIDER_NAME = "fake"


class FakeLLMProvider:
    """Returns queued responses in order.

    A queue entry is either a payload to return or an :class:`AIError` to raise,
    which is what makes failure classification and retry testable without
    monkeypatching anything.
    """

    def __init__(self, responses: Iterable[dict[str, Any] | AIError | str] = ()) -> None:
        self._responses: deque[dict[str, Any] | AIError | str] = deque(responses)
        self.requests: list[StructuredRequest] = []
        """Every request received, so a test can assert on what was actually
        sent — that the resume text reached the prompt, for instance."""

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def queue(self, response: dict[str, Any] | AIError | str) -> None:
        self._responses.append(response)

    def generate_structured(self, request: StructuredRequest, *, model: str) -> StructuredResult:
        self.requests.append(request)
        response = self._next()

        # A raw string models a provider returning malformed output, which is
        # how INVALID_OUTPUT handling gets covered without a real bad response.
        raw_text = response if isinstance(response, str) else json.dumps(response)
        payload = {} if isinstance(response, str) else response

        if isinstance(response, str):
            from jip_ai.structured import parse_structured_output

            payload = parse_structured_output(raw_text)

        return StructuredResult(
            payload=payload,
            raw_text=raw_text,
            model=model,
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
            stop_reason="end_turn",
        )

    def generate_text(self, system: str, user: str, *, model: str, max_output_tokens: int) -> str:
        response = self._next()
        return response if isinstance(response, str) else json.dumps(response)

    def _next(self) -> dict[str, Any] | str:
        if not self._responses:
            raise AssertionError("FakeLLMProvider ran out of queued responses.")
        response = self._responses.popleft()
        if isinstance(response, AIError):
            raise response
        return response
