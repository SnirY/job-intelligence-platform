"""Starting a resume import, and reading its state back.

``POST /api/v1/resumes/import`` answers 202 with a ``source_document_id``, a
``processing_job_id``, and a status (``docs/10-api-contracts.md``). Both ids are
returned because they answer different questions: the document is the thing the
user uploaded and keeps, the job is one attempt at processing it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from jip_ai import AIError, AIFailureCode
from jip_api.application.documents.upload import UploadedFile, store_uploaded_document
from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.documents.models import (
    DocumentExtraction,
    DocumentExtractionItem,
    DocumentKind,
    DocumentStatus,
    SourceDocument,
)
from jip_api.domain.processing.models import ProcessingJob, ProcessingJobKind
from jip_api.infrastructure.storage.base import ObjectStorage
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)

RESUME_IMPORT_TASK = "jip_worker.tasks.resumes.run_resume_import"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""

ENTITY_TYPE = "source_document"


@dataclass(frozen=True, slots=True)
class StartedImport:
    """What the import endpoint returns."""

    document: SourceDocument
    job: ProcessingJob


def start_resume_import(
    session: Session,
    storage: ObjectStorage,
    dispatcher: TaskDispatcher,
    *,
    user_id: uuid.UUID,
    upload: UploadedFile,
    max_bytes: int,
) -> StartedImport:
    """Store the upload, record a job, and queue the work.

    The order matters. The file and its row are committed *before* the task is
    enqueued, so a worker that picks the job up immediately always finds the
    document already there. Enqueuing first would leave a race in which the
    worker looks for a row the API has not written yet.

    A dispatch failure is recorded as a retriable job failure rather than
    losing the upload: the document is stored and the user can try again
    (``GOAL.md``: failures must not destroy user work).
    """
    document = store_uploaded_document(
        session,
        storage,
        user_id=user_id,
        upload=upload,
        max_bytes=max_bytes,
        kind=DocumentKind.RESUME,
    )

    job = jobs_uc.create_job(
        session,
        user_id=user_id,
        kind=ProcessingJobKind.RESUME_IMPORT,
        entity_type=ENTITY_TYPE,
        entity_id=document.id,
    )
    session.commit()

    dispatch(session, dispatcher, job)
    return StartedImport(document=document, job=job)


def dispatch(session: Session, dispatcher: TaskDispatcher, job: ProcessingJob) -> ProcessingJob:
    """Enqueue a job, recording a queue outage as a retriable failure."""
    try:
        task = dispatcher.enqueue(RESUME_IMPORT_TASK, str(job.id))
    except Exception as exc:
        logger.warning("Could not enqueue resume import", exc_info=exc, extra={"job": str(job.id)})
        jobs_uc.mark_failed(
            session,
            job,
            AIError(
                AIFailureCode.PROVIDER_ERROR,
                "Processing could not be started. Your file was saved — try again.",
                details=f"{type(exc).__name__}: {exc}",
            ),
        )
        session.commit()
        return job

    job.task_id = task.id
    session.commit()
    return job


# --- reads --------------------------------------------------------------------


def get_document(session: Session, user_id: uuid.UUID, document_id: uuid.UUID) -> SourceDocument:
    """Return one of the user's documents, or raise."""
    document = session.execute(
        owned(SourceDocument, user_id).where(SourceDocument.id == document_id)
    ).scalar_one_or_none()
    if document is None:
        raise ResourceNotFoundError("Document not found.")
    return document


def list_documents(session: Session, user_id: uuid.UUID) -> list[SourceDocument]:
    """The user's uploads, newest first."""
    statement = owned(SourceDocument, user_id).order_by(desc(SourceDocument.created_at))
    return list(session.execute(statement).scalars())


def latest_job_for_document(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID
) -> ProcessingJob | None:
    """The most recent job for a document.

    A document can have several over its life — one per retry — and the newest
    is the one whose state the user is watching.
    """
    statement = (
        owned(ProcessingJob, user_id)
        .where(ProcessingJob.entity_type == ENTITY_TYPE, ProcessingJob.entity_id == document_id)
        .order_by(desc(ProcessingJob.created_at))
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def latest_extraction(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentExtraction | None:
    """The newest extraction version for a document."""
    statement = (
        owned(DocumentExtraction, user_id)
        .where(DocumentExtraction.source_document_id == document_id)
        .order_by(desc(DocumentExtraction.version))
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def extraction_items(session: Session, extraction_id: uuid.UUID) -> list[DocumentExtractionItem]:
    """Every candidate in an extraction, in display order.

    Not scoped by user: the caller has already resolved the extraction through
    an ownership-checked query, and the extraction owns its items.
    """
    statement = (
        select(DocumentExtractionItem)
        .where(DocumentExtractionItem.extraction_id == extraction_id)
        .order_by(
            DocumentExtractionItem.candidate_type,
            DocumentExtractionItem.display_order,
            DocumentExtractionItem.id,
        )
    )
    return list(session.execute(statement).scalars())


def signed_download_url(
    storage: ObjectStorage, document: SourceDocument, *, expires_in_seconds: int
) -> str:
    """A temporary link to the original file.

    Signed and short-lived because resume files are personal data. Ownership is
    enforced before this is reached — the URL itself grants access to anyone
    holding it, which is exactly why it expires.
    """
    return storage.create_signed_url(document.storage_key, expires_in_seconds=expires_in_seconds)


def document_is_processing(document: SourceDocument) -> bool:
    """Whether work is still in flight for this document."""
    return document.status in {
        DocumentStatus.UPLOADED,
        DocumentStatus.EXTRACTING,
        DocumentStatus.EXTRACTED,
        DocumentStatus.PARSING,
    }
