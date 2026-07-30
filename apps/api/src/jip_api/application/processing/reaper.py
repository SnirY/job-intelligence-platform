"""Failing jobs whose worker never reported back.

DEV-013. The lifecycle assumes the worker writes a status: PENDING becomes
RUNNING becomes COMPLETED or FAILED. A worker that dies *before* the first write
breaks that assumption, and nothing in the system notices — the row stays
PENDING with ``started_at IS NULL``, the traceback goes to ``rq:failed:default``
where nothing reads it, and the user sees "Waiting to start" indefinitely.

There is no recovery from that state. ``prepare_retry`` requires FAILED, there
is no cancel, and no clock touches the row. Recovery today means deleting it in
SQL.

**Reaped on read rather than by a scheduler.** The stack has RQ but no
``rq-scheduler``, and adding one to run a sweep would be a new moving part for a
job that only matters while somebody is waiting for it. The frontend polls
``GET /processing-jobs/{id}``, so a stalled job is noticed exactly when someone
is looking — and a job nobody is looking at costs nothing by staying stale.

The trade is real and worth naming: a stalled job nobody polls is never reaped,
so this is not a garbage collector. It is a recovery path, which is what the
issue actually asked for.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from jip_api.domain.documents.models import DocumentStatus, SourceDocument
from jip_api.domain.jobs.models import Job, JobProcessingStatus
from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
)

logger = logging.getLogger(__name__)

STALLED = "STALLED"
"""Its own code rather than a borrowed ``AIFailureCode``.

Nothing about this is an AI failure — no model was reached, and often no work
started at all. Filing it as ``PROVIDER_ERROR`` would put it in the same bucket
as an outage and make the two indistinguishable in ``processing_jobs``.
"""

_PENDING_MESSAGE = (
    "This never started. The worker may have been down or restarting when it "
    "was queued. Nothing was lost — try again."
)

_RUNNING_MESSAGE = (
    "This started but never finished, so the worker probably stopped partway. "
    "Any step that already completed is kept — try again to resume from there."
)


def reap_if_stalled(
    session: Session,
    job: ProcessingJob,
    *,
    pending_timeout_seconds: int,
    running_timeout_seconds: int,
    now: dt.datetime | None = None,
) -> bool:
    """Fail ``job`` if it has been unattended too long. Returns whether it did.

    ``now`` is injectable so the thresholds can be tested without waiting them
    out — the alternative is a test that sleeps for five minutes, which nobody
    runs twice.
    """
    moment = now or dt.datetime.now(tz=dt.UTC)

    if job.status is ProcessingJobStatus.PENDING:
        # created_at, not started_at: a PENDING job has never started, which is
        # the whole complaint.
        since, limit, message = job.created_at, pending_timeout_seconds, _PENDING_MESSAGE
    elif job.status is ProcessingJobStatus.RUNNING:
        since, limit, message = (
            job.started_at or job.created_at,
            running_timeout_seconds,
            _RUNNING_MESSAGE,
        )
    else:
        return False

    if since is None or (moment - _aware(since)).total_seconds() < limit:
        return False

    job.status = ProcessingJobStatus.FAILED
    job.error_code = STALLED
    job.error_message = message
    # Retriable by definition: nothing about the input was rejected, so the
    # attempt that never happened is exactly the one worth making again. The
    # attempt budget still applies, so a job stuck in a crash loop cannot be
    # retried forever.
    job.is_retriable = job.attempts < job.max_attempts
    job.finished_at = moment

    _release_entity(session, job)
    session.flush()

    logger.warning(
        "Reaped a stalled processing job",
        extra={
            "job_id": str(job.id),
            "kind": str(job.kind),
            "attempts": job.attempts,
            "retriable": job.is_retriable,
        },
    )
    return True


def _release_entity(session: Session, job: ProcessingJob) -> None:
    """Put the thing the job was working on back into an actionable state.

    Without this the job reports failed while its document still says PARSING,
    and the screen shows a spinner beside a retry button. The worker's own
    failure handlers do the same repair; this is the path they never reached.
    """
    if ProcessingJobKind(job.kind) is ProcessingJobKind.RESUME_IMPORT:
        document = session.get(SourceDocument, job.entity_id)
        if document is not None and document.status not in {
            DocumentStatus.PARSED,
            DocumentStatus.CONFIRMED,
        }:
            document.status = DocumentStatus.FAILED
        return

    if ProcessingJobKind(job.kind) is ProcessingJobKind.JOB_ANALYSIS:
        target = session.get(Job, job.entity_id)
        # ANALYSIS_FAILED rather than FAILED: the description is intact, and
        # FAILED is what the UI reads to offer a paste box.
        if target is not None and target.status.has_content:
            target.status = JobProcessingStatus.ANALYSIS_FAILED


def _aware(value: dt.datetime) -> dt.datetime:
    """Treat a naive timestamp as UTC.

    Columns are ``timezone=True``, but SQLite and some drivers still hand back
    naive values, and subtracting those raises rather than comparing wrongly.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
