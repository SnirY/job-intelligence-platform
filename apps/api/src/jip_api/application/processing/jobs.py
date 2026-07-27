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
    job.status = ProcessingJobStatus.COMPLETED
    job.step = ProcessingStep.COMPLETED
    job.error_code = None
    job.error_message = None
    job.is_retriable = False
    job.finished_at = dt.datetime.now(tz=dt.UTC)
    session.flush()
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
