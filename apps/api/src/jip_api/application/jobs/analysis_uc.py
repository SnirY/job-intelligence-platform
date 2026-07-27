"""Starting a job analysis, and reading one back.

``POST /api/v1/jobs/{id}/analysis`` answers 202 with a ``processing_job_id``
the frontend polls, following the same async contract as resume import
(``docs/10-api-contracts.md``). The job itself is the entity, so there is no
second id to return — unlike an upload, nothing new is created by asking for an
analysis.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from jip_ai import AIError, AIFailureCode
from jip_api.application.errors import ApplicationError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.jobs.analysis import JobAnalysis, JobRequirement, JobResponsibility
from jip_api.domain.jobs.models import Job
from jip_api.domain.processing.models import ProcessingJob, ProcessingJobKind
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)

ANALYZE_JOB_TASK = "jip_worker.tasks.jobs.run_job_analysis"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""

ENTITY_TYPE = "job"

_WHITESPACE = re.compile(r"\s+")


def analysis_source_hash(description: str | None) -> str | None:
    """Hash of the text an analysis read, for detecting later edits.

    Deliberately not :func:`jip_api.application.jobs.creation.content_hash`,
    which answers a different question. That one ignores descriptions under 200
    characters, because two jobs both saying "TBC" are not duplicates of each
    other. Here every change matters: a short description edited into a
    different short description makes its analysis just as stale as a long one
    would.
    """
    if not description:
        return None
    normalized = _WHITESPACE.sub(" ", description).strip().casefold()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class JobNotAnalyzableError(ApplicationError):
    """The job cannot be analysed: no description, or one is already running."""


@dataclass(frozen=True, slots=True)
class StartedAnalysis:
    """What the analysis endpoint returns."""

    job: Job
    processing_job: ProcessingJob


def start_analysis(
    session: Session,
    dispatcher: TaskDispatcher,
    *,
    user_id: uuid.UUID,
    job: Job,
) -> StartedAnalysis:
    """Queue an analysis for a job.

    Refuses rather than silently doing nothing in two cases, so a frontend
    showing the button on a job that cannot use it gets a 409 instead of a
    request that appears to work:

    - **No description.** There is nothing to read. A URL import still in
      flight is the common case, and the right answer is to wait.
    - **One already running.** Two concurrent analyses of the same job would
      race to write versions 2 and 3 of the same text, at double the cost.
    """
    if not (job.description or "").strip():
        raise JobNotAnalyzableError(
            "This job has no description yet, so there is nothing to analyse."
        )

    if job.status.is_analysis_in_flight:
        raise JobNotAnalyzableError("This job is already being analysed.")

    processing_job = jobs_uc.create_job(
        session,
        user_id=user_id,
        kind=ProcessingJobKind.JOB_ANALYSIS,
        entity_type=ENTITY_TYPE,
        entity_id=job.id,
    )
    session.commit()

    dispatch(session, dispatcher, processing_job)
    return StartedAnalysis(job=job, processing_job=processing_job)


def dispatch(session: Session, dispatcher: TaskDispatcher, job: ProcessingJob) -> ProcessingJob:
    """Enqueue an analysis, recording a queue outage as a retriable failure."""
    try:
        task = dispatcher.enqueue(ANALYZE_JOB_TASK, str(job.id))
    except Exception as exc:
        logger.warning("Could not enqueue job analysis", exc_info=exc, extra={"job": str(job.id)})
        jobs_uc.mark_failed(
            session,
            job,
            AIError(
                AIFailureCode.PROVIDER_ERROR,
                "The analysis could not be started. Your job is saved — try again.",
                details=f"{type(exc).__name__}: {exc}",
            ),
        )
        session.commit()
        return job

    job.task_id = task.id
    session.commit()
    return job


# --- reads --------------------------------------------------------------------


def latest_analysis(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> JobAnalysis | None:
    """The newest analysis version for a job."""
    statement = (
        owned(JobAnalysis, user_id)
        .where(JobAnalysis.job_id == job_id)
        .order_by(desc(JobAnalysis.version))
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def get_analysis_version(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID, version: int
) -> JobAnalysis:
    """One specific version, or raise.

    Exists so a user reading an older analysis can keep reading it after a
    reanalysis lands — versions are kept precisely so they stay reachable.
    """
    analysis = session.execute(
        owned(JobAnalysis, user_id).where(
            JobAnalysis.job_id == job_id, JobAnalysis.version == version
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise ResourceNotFoundError("Analysis not found.")
    return analysis


def analysis_versions(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> list[int]:
    """Every version number for a job, newest first."""
    statement = (
        owned(JobAnalysis, user_id)
        .where(JobAnalysis.job_id == job_id)
        .order_by(desc(JobAnalysis.version))
        .with_only_columns(JobAnalysis.version)
    )
    return [int(row) for row in session.execute(statement).scalars()]


def requirements_for(session: Session, analysis_id: uuid.UUID) -> list[JobRequirement]:
    """Every requirement in an analysis, in the posting's own order.

    Not scoped by user: the caller resolved the analysis through an
    ownership-checked query, and the analysis owns its requirements.
    """
    statement = (
        select(JobRequirement)
        .where(JobRequirement.analysis_id == analysis_id)
        .order_by(JobRequirement.source_order, JobRequirement.id)
    )
    return list(session.execute(statement).scalars())


def responsibilities_for(session: Session, analysis_id: uuid.UUID) -> list[JobResponsibility]:
    """Every responsibility in an analysis, in the posting's own order."""
    statement = (
        select(JobResponsibility)
        .where(JobResponsibility.analysis_id == analysis_id)
        .order_by(JobResponsibility.source_order, JobResponsibility.id)
    )
    return list(session.execute(statement).scalars())


def latest_processing_job(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> ProcessingJob | None:
    """The most recent analysis attempt for a job.

    A job can have several over its life — one per reanalysis or retry — and
    the newest is the one whose state the user is watching.
    """
    statement = (
        owned(ProcessingJob, user_id)
        .where(
            ProcessingJob.kind == ProcessingJobKind.JOB_ANALYSIS,
            ProcessingJob.entity_type == ENTITY_TYPE,
            ProcessingJob.entity_id == job_id,
        )
        .order_by(desc(ProcessingJob.created_at))
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def is_stale(job: Job, analysis: JobAnalysis | None) -> bool:
    """Whether the description has changed since an analysis read it.

    A fact rather than a guess: the hash of the text the analysis read is
    stored on it. Returns ``False`` when there is nothing to compare, because
    "we cannot tell" must not be presented to the user as "out of date".
    """
    if analysis is None or analysis.source_content_hash is None:
        return False
    current = analysis_source_hash(job.description)
    return current is not None and current != analysis.source_content_hash
