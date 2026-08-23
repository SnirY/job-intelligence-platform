"""Is this posting still open?

```text
Fetch the URL → read the status → alive, gone, or we could not tell
```

Zero inference and zero cost: one request, and the HTTP status decides. Nothing
here calls a model, and nothing here reads the page.

**The rule the whole module exists to hold: unknown is not gone.** A refusal, a
timeout, a rate limit and a server fault all mean we were unable to look, which
is a different fact from the posting having closed. Presenting the first as the
second is the defect shape the twelve-stage walkthrough kept finding — a correct
observation rendered as a claim it cannot support — and here it would tell
someone a live role had closed.

So an inconclusive check writes nothing at all. `last_seen_alive_at` and
`closed_detected_at` stay null, and null keeps meaning never observed.

**What this cannot see, stated because the gap matters more than the coverage:**

- A posting that answers 200 with "this role is no longer accepting
  applications" reads as alive. The status is the only thing trusted here, and
  that page's status is 200. Detecting it means reading the body, which is a
  heuristic per board rather than one rule.
- A posting that redirects to a careers index reads as alive, for the same
  reason: `fetch_url` follows the redirect and reports the index's 200.

Both are under-reporting, which is the direction to fail in. Neither can be
fixed without guessing, and a wrong "closed" costs more than a missing one.
"""

from __future__ import annotations

import datetime as dt
import enum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jip_api.domain.jobs.models import Job
from jip_api.infrastructure.fetching import FetchError, fetch_url

logger = logging.getLogger(__name__)

LIVENESS_TASK = "jip_worker.tasks.jobs.run_job_liveness_check"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""

GONE_STATUSES = frozenset({404, 410})
"""The only two statuses read as closed.

404 is what every ATS returns for a pulled posting. 410 says the same thing
more explicitly. Nothing else is admitted: 403 is a refusal, 429 is a rate
limit, and a 5xx is the far end having a bad day. None of those are evidence
about the posting.
"""

BLOCKED_STATUSES = frozenset({401, 403, 429})
"""We were not allowed to look. Recorded to make that legible in a log."""


class LivenessVerdict(enum.StrEnum):
    """What one check concluded."""

    ALIVE = "ALIVE"
    """The URL answered. The posting exists."""

    GONE = "GONE"
    """The URL answered that the posting is not there."""

    UNKNOWN = "UNKNOWN"
    """We could not tell. **Writes nothing.**"""


class LivenessReason(enum.StrEnum):
    """Why the verdict came out as it did. For logs and debugging, not display.

    Kept separate from the verdict because three different failures collapse
    into UNKNOWN, and losing which one it was makes an operational problem
    invisible.
    """

    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    BLOCKED = "BLOCKED"
    SERVER_ERROR = "SERVER_ERROR"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNREACHABLE = "UNREACHABLE"
    NO_URL = "NO_URL"


@dataclass(frozen=True, slots=True)
class LivenessReading:
    """A classified observation, before anything is written."""

    verdict: LivenessVerdict
    reason: LivenessReason
    status: int | None = None


@dataclass(frozen=True, slots=True)
class LivenessOutcome:
    """What one check produced, after the job row was updated."""

    job_id: uuid.UUID
    verdict: LivenessVerdict
    reason: LivenessReason
    status: int | None = None
    checked_at: dt.datetime | None = None
    """When the observation was recorded. Null when nothing was written, which
    is every UNKNOWN."""


def classify(status: int | None) -> LivenessReading:
    """Turn an HTTP status into a verdict.

    Pure, and the only place the mapping lives. Takes a status rather than a
    response so both branches of the fetch — the one that returned and the one
    that raised — arrive at the same function.

    ``None`` means the request never reached a server: DNS failure, a target
    the safety layer refused, a redirect loop. Unreachable is not gone.
    """
    if status is None:
        return LivenessReading(LivenessVerdict.UNKNOWN, LivenessReason.UNREACHABLE)

    if status in GONE_STATUSES:
        return LivenessReading(LivenessVerdict.GONE, LivenessReason.NOT_FOUND, status)

    if status < 400:
        # A redirect never surfaces here — `fetch_url` follows it and reports
        # where it landed — so in practice this is 2xx.
        return LivenessReading(LivenessVerdict.ALIVE, LivenessReason.OK, status)

    if status in BLOCKED_STATUSES:
        return LivenessReading(LivenessVerdict.UNKNOWN, LivenessReason.BLOCKED, status)

    if status >= 500:
        return LivenessReading(LivenessVerdict.UNKNOWN, LivenessReason.SERVER_ERROR, status)

    return LivenessReading(LivenessVerdict.UNKNOWN, LivenessReason.INCONCLUSIVE, status)


def run_liveness_check(
    session: Session,
    job: Job,
    *,
    timeout_seconds: float,
    max_bytes: int,
    now: dt.datetime | None = None,
) -> LivenessOutcome:
    """Check one posting and record what was observed.

    Never raises for an expected failure, for the same reason the import
    pipeline does not: the outcome belongs on the job row the user is looking
    at, not in a traceback nothing reads.
    """
    if not job.source_url:
        # Pasted and hand-entered jobs have no URL to check. Not a failure —
        # there is simply nothing to ask.
        return LivenessOutcome(
            job_id=job.id,
            verdict=LivenessVerdict.UNKNOWN,
            reason=LivenessReason.NO_URL,
        )

    try:
        result = fetch_url(job.source_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    except FetchError as error:
        # `FetchError.status` is set wherever a response arrived, which is what
        # separates a 404 from a DNS failure. A body too large or of the wrong
        # type still came back with a status, and a status under 400 means the
        # posting is there — this check does not care that we could not read it.
        reading = classify(error.status)
        logger.info(
            "Liveness check could not read the posting",
            extra={
                "job_id": str(job.id),
                "code": error.code,
                "status": error.status,
                "verdict": str(reading.verdict),
            },
        )
    else:
        reading = classify(result.status)

    return _record(session, job, reading, now=now or dt.datetime.now(tz=dt.UTC))


def _record(
    session: Session,
    job: Job,
    reading: LivenessReading,
    *,
    now: dt.datetime,
) -> LivenessOutcome:
    """Apply a reading to the job row.

    Never touches `archived_at` and never touches `status`. Archiving is a
    decision the user made about their own list, and a posting closing is not
    that decision being made for them.
    """
    if reading.verdict is LivenessVerdict.UNKNOWN:
        # The rule, in one branch: an inconclusive check leaves no trace. It
        # must not look like a check that concluded something.
        return LivenessOutcome(
            job_id=job.id,
            verdict=reading.verdict,
            reason=reading.reason,
            status=reading.status,
        )

    if reading.verdict is LivenessVerdict.ALIVE:
        job.last_seen_alive_at = now
        # A posting that answers again is open again. Leaving the old date in
        # place would keep a reposted or restored role marked closed forever,
        # and the column means "since when", not "ever".
        job.closed_detected_at = None
    elif job.closed_detected_at is None:
        # First detection only. A later check must not move the date forward,
        # or "closed on the 3rd" silently becomes "closed today" and the field
        # stops answering the question it exists for.
        job.closed_detected_at = now

    session.flush()

    logger.info(
        "Liveness check recorded",
        extra={
            "job_id": str(job.id),
            "verdict": str(reading.verdict),
            "status": reading.status,
        },
    )
    return LivenessOutcome(
        job_id=job.id,
        verdict=reading.verdict,
        reason=reading.reason,
        status=reading.status,
        checked_at=now,
    )
