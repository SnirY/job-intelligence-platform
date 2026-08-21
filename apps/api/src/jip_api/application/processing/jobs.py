"""Processing job lifecycle.

The job row is what makes async work observable and retriable
(``docs/10-api-contracts.md``). Transitions live here rather than being written
inline wherever work happens, so "a failed job records why and whether a retry
is safe" is one rule in one place instead of a convention.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.orm import Session

from jip_ai import AIError, AIFailureCode
from jip_api.application.errors import ApplicationError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
    ProcessingStep,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5


class JobNotRetriableError(ApplicationError):
    """The job cannot be retried: it is not failed, the failure is permanent, or
    it has already used its attempts."""


class JobSupersededError(ApplicationError):
    """Somebody else gave this job a verdict while the worker was still running.

    The reaper is the only thing that does this today. It marks a job FAILED
    after a threshold and releases the entity, which is a decision made **about
    a worker it cannot see** — a hung process and a dead one look identical from
    the outside, and the threshold has to choose.

    So the reaper's verdict has to bind. Without that, a worker that stalls on a
    model call for half an hour and then finishes writes its results over a
    failure the user has already been shown, and if they retried in the meantime
    the posting is analysed twice.
    """


def create_job(
    session: Session,
    *,
    user_id: uuid.UUID,
    kind: ProcessingJobKind,
    entity_type: str,
    entity_id: uuid.UUID,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ProcessingJob:
    """Record a job as pending. Does not enqueue it."""
    job = ProcessingJob(
        user_id=user_id,
        kind=kind,
        status=ProcessingJobStatus.PENDING,
        step=ProcessingStep.QUEUED,
        entity_type=entity_type,
        entity_id=entity_id,
        attempts=0,
        max_attempts=max_attempts,
        is_retriable=False,
    )
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> ProcessingJob:
    """Return one of the user's jobs, or raise."""
    job = session.execute(
        owned(ProcessingJob, user_id).where(ProcessingJob.id == job_id)
    ).scalar_one_or_none()
    if job is None:
        raise ResourceNotFoundError("Processing job not found.")
    return job


def load_job(session: Session, job_id: uuid.UUID) -> ProcessingJob | None:
    """Return a job without scoping to a user.

    For the worker only, which runs on behalf of the job's owner and has no
    request context. Every user-facing path uses :func:`get_job`.
    """
    return session.get(ProcessingJob, job_id)


def mark_running(session: Session, job: ProcessingJob, step: ProcessingStep) -> ProcessingJob:
    """Move a job into RUNNING, counting the attempt."""
    if job.status is not ProcessingJobStatus.RUNNING:
        job.attempts += 1
        job.started_at = dt.datetime.now(tz=dt.UTC)
    job.status = ProcessingJobStatus.RUNNING
    job.step = step
    job.error_code = None
    job.error_message = None
    session.flush()
    return job


def advance(session: Session, job: ProcessingJob, step: ProcessingStep) -> ProcessingJob:
    """Record progress within a running job, for the polling frontend."""
    job.step = step
    session.flush()
    return job


def mark_completed(session: Session, job: ProcessingJob) -> ProcessingJob:
    """Finish a job, but only if it is still the one in flight.

    Conditional, and that is the whole point. ``mark_completed`` used to assign
    COMPLETED unconditionally, so a job the reaper had already failed would be
    quietly resurrected by the worker it had given up on — the row would read
    COMPLETED after the user had been told it failed, and any retry they started
    in the meantime would already be running.

    Written as ``UPDATE ... WHERE status = 'RUNNING'`` rather than a read
    followed by a write, because the two are not the same under concurrency: the
    reaper commits from a different session, and a check that passed a moment
    ago is not a check that still holds. One statement decides and reports what
    it did.

    Raises :class:`JobSupersededError` when it decided nothing. The caller has a
    transaction full of work that nobody wants and must roll it back — the entity
    was released when the job was failed, so committing now would leave a
    completed analysis attached to a job that says it never ran.
    """
    now = dt.datetime.now(tz=dt.UTC)

    # `Session.execute` is typed as returning `Result`, which does not declare
    # `rowcount`; an UPDATE always yields a `CursorResult` at runtime.
    claimed = cast(
        "CursorResult[Any]",
        session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job.id,
                ProcessingJob.status == ProcessingJobStatus.RUNNING,
            )
            .values(
                status=ProcessingJobStatus.COMPLETED,
                step=ProcessingStep.COMPLETED,
                error_code=None,
                error_message=None,
                is_retriable=False,
                finished_at=now,
            )
        ),
    )

    if claimed.rowcount == 0:
        session.refresh(job)
        logger.warning(
            "Refused to complete a job that is no longer running",
            extra={
                "job_id": str(job.id),
                "kind": str(job.kind),
                "status": str(job.status),
            },
        )
        raise JobSupersededError(
            f"This job is {job.status}, not running. Its work has been discarded."
        )

    session.refresh(job)
    return job


def mark_failed(session: Session, job: ProcessingJob, error: AIError) -> ProcessingJob:
    """Record a classified failure.

    ``is_retriable`` combines the failure's own classification with the attempt
    budget: a genuinely transient failure that has already burned five attempts
    is not worth offering the user a button for.
    """
    job.status = ProcessingJobStatus.FAILED
    job.error_code = str(error.code)
    job.error_message = str(error.args[0]) if error.args else str(error.code)
    job.is_retriable = error.is_retriable and job.attempts < job.max_attempts
    job.finished_at = dt.datetime.now(tz=dt.UTC)
    session.flush()

    logger.warning(
        "Processing job failed",
        extra={
            "job_id": str(job.id),
            "error_code": job.error_code,
            "attempts": job.attempts,
            "retriable": job.is_retriable,
            # The provider's own explanation, which the user-facing message
            # deliberately does not carry. Without it here it is dropped
            # entirely, and DEV-015 is the case that makes that expensive: the
            # cause was "credit balance too low" and nothing recorded it.
            "detail": error.details,
        },
    )
    return job


def mark_unexpected_failure(session: Session, job: ProcessingJob, exc: Exception) -> ProcessingJob:
    """Record a failure that was not already classified.

    A bug, not a provider problem. Retriable, because the common cause is a
    transient environment fault; the message stays generic because an internal
    exception must not reach the browser (``docs/10-api-contracts.md``).
    """
    logger.exception("Processing job raised an unexpected error", extra={"job_id": str(job.id)})
    return mark_failed(
        session,
        job,
        AIError(
            AIFailureCode.PROVIDER_ERROR,
            "Something went wrong while processing this document.",
            details=f"{type(exc).__name__}: {exc}",
        ),
    )


def prepare_retry(session: Session, job: ProcessingJob) -> ProcessingJob:
    """Reset a failed job so it can be dispatched again.

    Refuses anything that is not a safe retry rather than quietly doing nothing,
    so a frontend showing a retry button on a job that cannot be retried gets a
    409 instead of a silent no-op.
    """
    if job.status is not ProcessingJobStatus.FAILED:
        raise JobNotRetriableError("Only a failed job can be retried.")
    if not job.is_retriable:
        raise JobNotRetriableError("This failure cannot be fixed by trying again.")
    if job.attempts >= job.max_attempts:
        raise JobNotRetriableError("This job has already been retried too many times.")

    job.status = ProcessingJobStatus.PENDING
    job.step = ProcessingStep.QUEUED
    job.error_code = None
    job.error_message = None
    job.is_retriable = False
    job.finished_at = None
    session.flush()
    return job
