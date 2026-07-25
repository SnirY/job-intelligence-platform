"""Infrastructure diagnostic tasks.

These are not product features. They exist so the queue path — API enqueues,
Redis stores, worker executes, result comes back — can be exercised end to end
by tests and by an operator checking a deployment.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class PingResult(TypedDict):
    """Result returned by :func:`ping`."""

    task: str
    echo: str
    completed_at: str


def ping(message: str = "ping") -> PingResult:
    """Echo ``message`` back with a completion timestamp.

    Deliberately has no side effects, so it is safe to run against any
    environment and safe to retry.
    """
    logger.info("Executing ping task", extra={"task": "ping"})
    return PingResult(
        task="ping",
        echo=message,
        completed_at=dt.datetime.now(tz=dt.UTC).isoformat(),
    )
