"""The provider boundary.

``GOAL.md`` requires business logic to be provider-independent, so everything
above this line speaks in prompts and JSON schemas and never in a vendor's SDK
types. A fake implementation is therefore a few lines, which is what lets the
normal test suite run with no network and no key
(``docs/11-engineering-standards.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What a call consumed."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    """Prompt-cache reads, billed at a fraction of the input rate. Tracked
    separately so a cost estimate does not charge full price for them."""


@dataclass(frozen=True, slots=True)
class StructuredResult:
    """A structured response, still untrusted.

    ``raw_text`` is kept alongside the parsed payload because when validation
    later rejects the output, the text is the only evidence of what the model
    actually said.
    """

    payload: dict[str, Any]
    raw_text: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredRequest:
    """One request for a schema-shaped answer."""

    system: str
    user: str
    json_schema: dict[str, Any]
    """JSON Schema the answer must satisfy. Sent to the provider so it can
    constrain generation, and checked again on the way back — a provider
    honouring it is a convenience, not a guarantee."""

    max_output_tokens: int = 8000
    effort: str | None = None
    """Reasoning depth, when the provider exposes one. ``None`` leaves the
    provider's default alone rather than guessing at a portable value."""


class LLMProvider(Protocol):
    """What the platform needs from a model provider.

    ``docs/10-api-contracts.md`` also lists ``generate_embedding``. It is absent
    until Phase 6 needs semantic retrieval: an unimplemented method on a
    Protocol is a promise nothing keeps.
    """

    @property
    def name(self) -> str:
        """Short identifier recorded on every ``AIRun``."""
        ...

    def generate_structured(self, request: StructuredRequest, *, model: str) -> StructuredResult:
        """Return a schema-shaped answer, or raise :class:`~jip_ai.failures.AIError`."""
        ...

    def generate_text(self, system: str, user: str, *, model: str, max_output_tokens: int) -> str:
        """Return free text. Used where no schema applies."""
        ...
