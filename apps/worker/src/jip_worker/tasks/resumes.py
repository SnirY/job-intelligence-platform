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
from jip_api.application.resumes import cover_letters as cover_letters_uc
from jip_api.application.resumes.pipeline import run_import
from jip_api.domain.jobs.models import Job
from jip_api.domain.processing.models import ProcessingJobStatus
from jip_api.domain.resumes.cover_letters import CoverLetter, CoverLetterStatus
from jip_api.infrastructure.ai import get_ai_provider, get_model_router
from jip_api.infrastructure.db.session import new_session
from jip_api.infrastructure.extraction.ocr import get_ocr_engine
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
                # Resolved here with the rest of the infrastructure, and `None`
                # when OCR is off or Tesseract is not installed. The pipeline
                # gets an engine or nothing and needs no opinion about which.
                ocr=get_ocr_engine(),
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
                extra={"job_id": job_id},
            )
            return {"job_id": job_id, "status": "SUPERSEDED"}
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


def run_cover_letter_draft(letter_id: str) -> dict[str, object]:
    """Draft one cover letter.

    Takes the *letter's* id rather than a processing job's. The row exists
    before this runs, in DRAFTING, so the user has something to look at and
    something that survives a failure — the same argument `importing.py` makes
    for creating the job row before the fetch.

    Never raises for an expected failure. A model that will not answer is an
    outcome that belongs on the letter, where the person waiting for it is
    looking.
    """
    settings = get_settings()
    session = new_session()

    try:
        letter = session.get(CoverLetter, uuid.UUID(letter_id))
        if letter is None:
            logger.error("Cover letter not found", extra={"letter_id": letter_id})
            return {"letter_id": letter_id, "status": "MISSING"}

        if letter.status is not CoverLetterStatus.DRAFTING:
            # A duplicate delivery, or a letter the user has already edited.
            # Drafting again would overwrite what they wrote.
            logger.info(
                "Skipping cover letter draft, it is not awaiting one",
                extra={"letter_id": letter_id, "status": str(letter.status)},
            )
            return {"letter_id": letter_id, "status": str(letter.status)}

        job = session.get(Job, letter.job_id)
        if job is None:
            logger.error("Job gone for cover letter", extra={"letter_id": letter_id})
            return {"letter_id": letter_id, "status": "MISSING"}

        try:
            outcome = cover_letters_uc.run_draft(
                session,
                get_ai_provider(),
                get_model_router(),
                letter=letter,
                job=job,
                max_attempts=settings.ai_max_attempts,
            )
        except Exception as exc:
            # A defect, not a refused draft. The row keeps its angle so the user
            # can try again, and the message stays generic because internal
            # detail must not reach the browser (docs/10-api-contracts.md).
            session.rollback()
            logger.exception(
                "Cover letter draft raised unexpectedly", extra={"letter_id": letter_id}
            )
            letter = session.get(CoverLetter, uuid.UUID(letter_id))
            if letter is not None:
                letter.status = CoverLetterStatus.FAILED
                letter.error = "Something went wrong while writing that letter. Try again."
            session.commit()
            return {"letter_id": letter_id, "status": "FAILED", "error_code": type(exc).__name__}

        session.commit()
        return {
            "letter_id": letter_id,
            "status": str(outcome.letter.status),
            "claims": len(outcome.report.claims) if outcome.report else 0,
        }
    finally:
        session.close()
