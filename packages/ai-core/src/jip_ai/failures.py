"""How AI calls fail, and whether trying again could help.

The taxonomy is fixed by ``docs/10-api-contracts.md``. Classifying a failure is
not cosmetic: it decides whether the user is offered a retry, and
``docs/11-engineering-standards.md`` forbids both swallowing a failure silently
and returning fake intelligence in its place.
"""

from __future__ import annotations

import enum


class AIFailureCode(enum.StrEnum):
    """The six failure classes named in ``docs/10-api-contracts.md``."""

    PROVIDER_ERROR = "PROVIDER_ERROR"
    """The provider answered with an error, or could not be reached."""

    RATE_LIMIT = "RATE_LIMIT"
    """We are over quota. Waiting helps; changing the input does not."""

    TIMEOUT = "TIMEOUT"
    """No answer within the budget."""

    INVALID_OUTPUT = "INVALID_OUTPUT"
    """The model returned something that is not the requested shape."""

    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    """Well-formed output that breaks a business rule, so it must not persist."""

    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    """There was nothing usable to send. A scanned resume with no text layer is
    the canonical case, and no number of retries will put text into it."""


# Whether a retry could plausibly succeed. INVALID_OUTPUT and VALIDATION_FAILURE
# are retriable because generation is not deterministic — a second attempt on the
# same input often parses. CONTENT_UNAVAILABLE is not: the input itself is the
# problem, and retrying only spends money to fail identically.
_RETRIABLE: frozenset[AIFailureCode] = frozenset(
    {
        AIFailureCode.PROVIDER_ERROR,
        AIFailureCode.RATE_LIMIT,
        AIFailureCode.TIMEOUT,
        AIFailureCode.INVALID_OUTPUT,
        AIFailureCode.VALIDATION_FAILURE,
    }
)


class AIError(Exception):
    """A classified AI failure.

    Carries the code rather than leaving callers to match on message text, which
    is how a provider changing its wording silently turns a retriable failure
    into a permanent one.
    """

    def __init__(
        self,
        code: AIFailureCode,
        message: str,
        *,
        details: str | None = None,
        retriable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details
        """Provider-side detail. Logged, never returned to the browser
        (``docs/10-api-contracts.md``: no stack traces or provider keys)."""

        self.retriable = retriable
        """Overrides the code's default when the code alone cannot decide.

        ``PROVIDER_ERROR`` covers both "we could not reach it" and "it answered
        with an error", and those differ exactly on whether waiting helps. A
        400 is a permanent PROVIDER_ERROR: the code is right and retrying is
        not. See DEV-015 — before this existed, a "credit balance too low"
        reply was retried five times, each one a live call that could not
        succeed.

        ``None`` means "use the code's default", which is what every failure
        that is not classified by HTTP status still does.
        """

    @property
    def is_retriable(self) -> bool:
        if self.retriable is not None:
            return self.retriable
        return self.code in _RETRIABLE

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"
