"""Which provider answers for a board.

A dictionary, and deliberately not a plugin mechanism. Adding a board provider
means writing a module and adding a line here, which is the whole ceremony —
`providers/README.md` in career-ops describes the same shape and it is the right
one at this size.

`scan` is here rather than in the API because it is the part every caller would
otherwise write again: fetch each board, keep going when one fails, and report
what happened per board rather than as one aggregate that hides which company
went missing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from jip_sources.base import JobSource
from jip_sources.http import DEFAULT_TIMEOUT_SECONDS, BoardUnavailable
from jip_sources.models import BoardRef, RawPosting
from jip_sources.providers.ashby import AshbySource
from jip_sources.providers.greenhouse import GreenhouseSource
from jip_sources.providers.lever import LeverSource

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, JobSource] = {
    source.name: source for source in (GreenhouseSource(), AshbySource(), LeverSource())
}


class UnknownProvider(KeyError):
    """No provider by that name."""


def get_provider(name: str) -> JobSource:
    try:
        return PROVIDERS[name]
    except KeyError as error:
        raise UnknownProvider(f"No job source named {name!r}") from error


@dataclass(frozen=True, slots=True)
class BoardOutcome:
    """What happened to one board in a scan."""

    board: BoardRef
    postings: Sequence[RawPosting] = field(default_factory=tuple)
    error: str | None = None
    error_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class ScanResult:
    """What happened to all of them.

    Per board rather than a single list plus a count, because "we read four of
    your five boards" is only actionable if the screen can say which one is
    missing. An aggregate would let a company quietly stop being watched.
    """

    outcomes: Sequence[BoardOutcome]

    @property
    def postings(self) -> list[RawPosting]:
        return [posting for outcome in self.outcomes for posting in outcome.postings]

    @property
    def failures(self) -> list[BoardOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.succeeded]


def scan(
    boards: Iterable[BoardRef], *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> ScanResult:
    """Read every board, and never let one failure end the run.

    A board that is unreachable, misconfigured or has changed shape is recorded
    and skipped. Ten watched companies must not become zero postings because one
    of them is having an outage.
    """
    outcomes: list[BoardOutcome] = []

    for board in boards:
        try:
            provider = get_provider(board.provider)
        except UnknownProvider as error:
            outcomes.append(
                BoardOutcome(board=board, error=str(error), error_code="UNKNOWN_PROVIDER")
            )
            continue

        try:
            postings = provider.fetch(board, timeout_seconds=timeout_seconds)
        except BoardUnavailable as error:
            logger.info(
                "Board could not be read",
                extra={"provider": board.provider, "board": board.token, "code": error.code},
            )
            outcomes.append(BoardOutcome(board=board, error=str(error), error_code=error.code))
            continue
        except Exception as error:  # pragma: no cover - a defect in a provider
            # A provider raising anything else is a bug here rather than a bad
            # response, and it still must not take the other boards down with
            # it. Logged loudly, recorded quietly.
            logger.exception(
                "Provider raised unexpectedly",
                extra={"provider": board.provider, "board": board.token},
            )
            outcomes.append(
                BoardOutcome(
                    board=board, error=f"{type(error).__name__}: {error}", error_code="INTERNAL"
                )
            )
            continue

        outcomes.append(BoardOutcome(board=board, postings=tuple(postings)))

    return ScanResult(outcomes=tuple(outcomes))
