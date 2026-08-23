"""The contract a board provider satisfies.

One method, and a deliberately narrow one. A provider turns a board reference
into postings and does nothing else — it does not decide whether a posting is
interesting, does not deduplicate, does not touch a database, and does not know
that a `Job` exists.

Everything a provider might be tempted to do beyond this belongs to the caller,
where it can be done once for every provider rather than three times slightly
differently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from jip_sources.models import BoardRef, RawPosting


class JobSource(Protocol):
    """Reads one company's board."""

    name: str
    """The identifier used in configuration and in `BoardRef.provider`."""

    def fetch(self, board: BoardRef, *, timeout_seconds: float) -> Sequence[RawPosting]:
        """Every open posting on ``board``.

        Raises :class:`jip_sources.http.BoardUnavailable` if the board cannot be
        read. An empty sequence means the board was read and has nothing open,
        which is not a failure.

        A posting the provider cannot make sense of is skipped rather than
        raised: one malformed row in a hundred should cost that row, not the
        other ninety-nine.
        """
        ...
