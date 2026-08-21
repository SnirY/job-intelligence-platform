"""The job background tasks: URL import, and analysis.

Both thin, like the resume task. Each owns its session and turns every outcome
into a recorded state the user can see. The pipelines are in the application
layer, where they can be tested without RQ.

A remote fetch is the reason the first one is background work at all — it takes
seconds, and a page that hangs would otherwise hold an HTTP request open until
something upstream gave up. The second is background work for the usual AI
reason: two model calls take longer than a request should.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from jip_ai import AIError
from jip_api.application.jobs.analysis_pipeline import run_analysis
from jip_api.application.jobs.creation import mark_fetch_failed, record_import
from jip_api.application.jobs.importing import run_url_import
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.jobs.models import Job, JobImportMethod, JobProcessingStatus
from jip_api.domain.processing.models import ProcessingJobStatus
from jip_api.infrastructure.ai import get_ai_provider, get_model_router
from jip_api.infrastructure.db.session import new_session
from jip_config import get_settings

logger = logging.getLogger(__name__)


def run_job_url_import(job_id: str) -> dict[str, object]:
    """Fetch one job's URL and store what came back.

    Never raises for an expected failure: the outcome belongs on the job row,
    which the user is looking at. An exception escaping here would land in RQ's
    failed registry where nothing looks for it.
    """
    settings = get_settings()
    session = new_session()

    try:
        job = session.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.error("Job not found for URL import", extra={"job_id": job_id})
            return {"job_id": job_id, "status": "MISSING"}

        if job.status is not JobProcessingStatus.FETCHING:
            # A duplicate delivery, or a job the user has already filled in by
            # hand. Fetching again would overwrite what they typed.
            logger.info(
                "Skipping URL import, job is not awaiting a fetch",
                extra={"job_id": job_id, "status": str(job.status)},
            )
            return {"job_id": job_id, "status": str(job.status)}

        try:
            outcome = run_url_import(
                session,
                job,
                timeout_seconds=settings.job_fetch_timeout_seconds,
                max_bytes=settings.job_fetch_max_bytes,
            )
        except Exception as exc:
            # A bug, not a fetch failure. The job keeps its URL so the user can
            # retry or paste; the message stays generic because internal detail
            # must not reach the browser (docs/10-api-contracts.md).
            session.rollback()
            logger.exception("Job URL import raised unexpectedly", extra={"job_id": job_id})
            job = session.get(Job, uuid.UUID(job_id))
            if job is not None:
                mark_fetch_failed(
                    session,
                    job,
                    message="Something went wrong while importing that link. Try again.",
                )
                record_import(
                    session,
                    job,
                    import_method=JobImportMethod.URL,
                    source_url=job.source_url,
                    error=f"{type(exc).__name__}: {exc}",
                    error_code="INTERNAL_ERROR",
                )
            session.commit()
            return {"job_id": job_id, "status": "FAILED", "error_code": "INTERNAL_ERROR"}

        session.commit()
        return {
            "job_id": job_id,
            "status": "COMPLETED" if outcome.succeeded else "FAILED",
            "characters": outcome.characters,
            "error_code": outcome.error_code,
        }
    finally:
        session.close()


def run_job_analysis(processing_job_id: str) -> dict[str, object]:
    """Parse and analyse one job.

    Takes the *processing job's* id rather than the job's, unlike the import
    task above. The two differ because the outcomes live in different places: an
    import records itself on the job, while an analysis is an attempt that can
    fail, be retried, and be counted — all of which is on the processing job
    row, exactly as resume import does it.
    """
    settings = get_settings()
    session = new_session()

    try:
        processing_job = jobs_uc.load_job(session, uuid.UUID(processing_job_id))
        if processing_job is None:
            logger.error("Analysis job not found", extra={"job_id": processing_job_id})
            return {"job_id": processing_job_id, "status": "MISSING"}

        if processing_job.status is ProcessingJobStatus.COMPLETED:
            # A duplicate delivery. Running again would mint a second analysis
            # version of the same text, at twice the cost.
            logger.info("Job analysis already completed", extra={"job_id": processing_job_id})
            return {"job_id": processing_job_id, "status": str(processing_job.status)}

        try:
            result = run_analysis(
                session,
                get_ai_provider(),
                get_model_router(),
                job=processing_job,
                max_input_chars=settings.ai_max_input_chars,
                max_attempts=settings.ai_max_attempts,
            )
        except jobs_uc.JobSupersededError:
            # Somebody already decided this job's fate — the reaper, after the
            # stall threshold. Roll the work back and leave their verdict alone.
            # Recording a failure here would replace a correct and specific
            # STALLED with a generic one, and the user may already have retried
            # on the strength of it.
            session.rollback()
            logger.warning(
                "Discarded work for a job that was no longer running",
                extra={"job_id": processing_job_id},
            )
            return {"job_id": processing_job_id, "status": "SUPERSEDED"}
        except AIError as error:
            session.rollback()
            jobs_uc.mark_failed(session, processing_job, error)
            _record_analysis_failure(session, processing_job.entity_id)
            session.commit()
            return {
                "job_id": processing_job_id,
                "status": "FAILED",
                "error_code": str(error.code),
            }
        except Exception as exc:
            session.rollback()
            jobs_uc.mark_unexpected_failure(session, processing_job, exc)
            _record_analysis_failure(session, processing_job.entity_id)
            session.commit()
            return {
                "job_id": processing_job_id,
                "status": "FAILED",
                "error_code": "PROVIDER_ERROR",
            }

        return {
            "job_id": processing_job_id,
            "status": "COMPLETED",
            "analysis_id": str(result.analysis_id),
            "version": result.version,
            "requirements": result.requirement_count,
        }
    finally:
        session.close()


def _record_analysis_failure(session: Session, job_id: uuid.UUID) -> None:
    """Put the job back into a state the user can act on.

    The rollback that precedes this discards whatever the pipeline had set, so
    a job that failed mid-parse would otherwise sit in PARSING forever with
    nothing running. ANALYSIS_FAILED rather than FAILED: the description is
    intact, and FAILED is what the UI reads to offer a paste box.
    """
    target = session.get(Job, job_id)
    if target is None:  # pragma: no cover - the job was deleted mid-analysis
        return
    if target.status.has_content:
        target.status = JobProcessingStatus.ANALYSIS_FAILED
