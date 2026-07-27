"""The resume import background task.

Deliberately thin. It owns the session, resolves infrastructure, and turns any
failure into a recorded job state — the pipeline itself lives in the application
layer, where it can be tested without RQ or Redis.

``docs/11-engineering-standards.md`` asks background tasks to be retry-safe,
observable, and associated with an entity. All three come from the job row: the
task takes its id, records progress on it, and leaves the document intact
whatever happens.
"""

from __future__ import annotations

import logging
import uuid

from jip_ai import AIError
from jip_api.application.processing import jobs as jobs_uc
from jip_api.application.resumes.pipeline import run_import
from jip_api.domain.processing.models import ProcessingJobStatus
from jip_api.infrastructure.ai import get_ai_provider, get_model_router
from jip_api.infrastructure.db.session import new_session
from jip_api.infrastructure.storage.s3 import get_object_storage
from jip_config import get_settings

logger = logging.getLogger(__name__)


def run_resume_import(job_id: str) -> dict[str, object]:
    """Process one uploaded resume.

    Returns a small summary for the queue's result record. Never raises for an
    expected failure: the outcome belongs on the job row, which the user polls,
    and an exception escaping here would only put it in RQ's failed registry
    where nothing looks for it.
    """
    settings = get_settings()
    session = new_session()

    try:
        job = jobs_uc.load_job(session, uuid.UUID(job_id))
        if job is None:
            logger.error("Resume import job not found", extra={"job_id": job_id})
            return {"job_id": job_id, "status": "MISSING"}

        if job.status is ProcessingJobStatus.COMPLETED:
            # A duplicate delivery. Doing the work again would mint a second
            # extraction version and a second review screen for one upload.
            logger.info("Resume import already completed", extra={"job_id": job_id})
            return {"job_id": job_id, "status": str(job.status)}

        try:
            result = run_import(
                session,
                get_object_storage(),
                get_ai_provider(),
                get_model_router(),
                job=job,
                max_input_chars=settings.ai_max_input_chars,
                max_attempts=settings.ai_max_attempts,
            )
        except AIError as error:
            session.rollback()
            jobs_uc.mark_failed(session, job, error)
            session.commit()
            return {"job_id": job_id, "status": "FAILED", "error_code": str(error.code)}
        except Exception as exc:
            session.rollback()
            jobs_uc.mark_unexpected_failure(session, job, exc)
            session.commit()
            return {"job_id": job_id, "status": "FAILED", "error_code": "PROVIDER_ERROR"}

        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "document_id": str(result.document_id),
            "candidates": result.candidate_count,
        }
    finally:
        session.close()
