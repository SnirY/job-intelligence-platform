"""Resume import endpoints.

The three routes in ``docs/10-api-contracts.md`` — import, review, confirm —
plus two the workflow needs to be usable: listing what has been uploaded, and a
signed link to the original file.

Import answers 202, not 201: parsing takes tens of seconds, and holding the
request open for it would time out on any real deployment.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep, StorageDep
from jip_api.application.documents.upload import ALLOWED_UPLOAD_TYPES, UploadedFile
from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.resumes import confirm as confirm_uc
from jip_api.application.resumes import imports as imports_uc
from jip_api.core.responses import DataResponse
from jip_api.domain.documents.models import (
    CandidateDecision,
    CandidateType,
    DocumentStatus,
    TextSource,
)
from jip_api.domain.processing.models import ProcessingJobStatus, ProcessingStep
from jip_api.infrastructure.db.session import get_session
from jip_config import Settings, get_settings

router = APIRouter(prefix="/resumes", tags=["resumes"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# --- payloads -----------------------------------------------------------------


class ImportAcceptedPayload(BaseModel):
    """The documented 202 body."""

    source_document_id: uuid.UUID
    processing_job_id: uuid.UUID
    status: ProcessingJobStatus


class ProcessingJobPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProcessingJobStatus
    step: ProcessingStep
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    is_retriable: bool


class DocumentPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    extraction_error: str | None
    text_source: TextSource | None
    ocr_confidence: float | None
    created_at: Any


class ImportSummaryPayload(BaseModel):
    """One upload and the state of its processing."""

    document: DocumentPayload
    job: ProcessingJobPayload | None


class ExtractionItemPayload(BaseModel):
    """One review candidate.

    ``payload`` and ``edited_payload`` are untyped on purpose: the shape differs
    per candidate type, and the frontend renders by type. Everything inside was
    validated against ``ResumeParseResult`` before being stored.
    """

    id: uuid.UUID
    candidate_type: CandidateType
    parent_item_id: uuid.UUID | None
    display_order: int
    payload: dict[str, Any]
    edited_payload: dict[str, Any] | None
    confidence: int | None
    source_text: str | None
    decision: CandidateDecision
    target_entity_type: str | None
    target_entity_id: uuid.UUID | None


class ExtractionPayload(BaseModel):
    """The review screen's data."""

    id: uuid.UUID
    version: int
    prompt_version: str
    model: str
    provider: str
    warnings: list[str]
    confirmed_at: Any
    items: list[ExtractionItemPayload]


class ExtractionReviewPayload(BaseModel):
    """Everything the review screen needs in one request.

    Aggregated rather than split across three polls: the frontend needs the job
    state and the extraction together to decide what to render, and fetching
    them separately would show a "processing" screen next to a finished result.
    """

    document: DocumentPayload
    job: ProcessingJobPayload | None
    extraction: ExtractionPayload | None


class SignedUrlPayload(BaseModel):
    url: str
    expires_in_seconds: int


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    action: confirm_uc.ConfirmAction
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Only for EDIT. Merged over the extracted payload.",
    )


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DecisionRequest] = Field(min_length=1, max_length=1000)


class AppliedItemPayload(BaseModel):
    item_id: uuid.UUID
    candidate_type: CandidateType
    outcome: confirm_uc.ConfirmOutcome
    target_entity_type: str | None
    target_entity_id: uuid.UUID | None
    detail: str | None


class ConfirmationPayload(BaseModel):
    applied: list[AppliedItemPayload]
    created_count: int
    remaining_pending: int


# --- routes -------------------------------------------------------------------


@router.post(
    "/import",
    response_model=DataResponse[ImportAcceptedPayload],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a resume for import",
)
def import_resume(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    dispatcher: DispatcherDep,
    file: Annotated[UploadFile, File(description="A PDF or DOCX resume.")],
) -> DataResponse[ImportAcceptedPayload]:
    """Store the file and queue it for processing.

    Reads the upload fully into memory, which is safe because
    ``JIP_MAX_UPLOAD_BYTES`` bounds it — the bytes have to be in hand anyway to
    hash them and check their magic bytes before anything is stored.
    """
    data = file.file.read(settings.max_upload_bytes + 1)
    started = imports_uc.start_resume_import(
        session,
        storage,
        dispatcher,
        user_id=user.id,
        upload=UploadedFile(
            filename=file.filename or "resume",
            content_type=file.content_type or "",
            data=data,
        ),
        max_bytes=settings.max_upload_bytes,
    )

    return DataResponse(
        data=ImportAcceptedPayload(
            source_document_id=started.document.id,
            processing_job_id=started.job.id,
            status=ProcessingJobStatus(started.job.status),
        )
    )


@router.get(
    "/imports",
    response_model=DataResponse[list[ImportSummaryPayload]],
    summary="List uploaded resumes",
)
def list_imports(
    user: CurrentUser, session: SessionDep
) -> DataResponse[list[ImportSummaryPayload]]:
    documents = imports_uc.list_documents(session, user.id)
    return DataResponse(
        data=[
            ImportSummaryPayload(
                document=DocumentPayload.model_validate(document),
                job=_job_payload(imports_uc.latest_job_for_document(session, user.id, document.id)),
            )
            for document in documents
        ]
    )


@router.get(
    "/imports/{source_document_id}/extraction",
    response_model=DataResponse[ExtractionReviewPayload],
    summary="Review what was extracted",
)
def read_extraction(
    user: CurrentUser, session: SessionDep, source_document_id: uuid.UUID
) -> DataResponse[ExtractionReviewPayload]:
    """Return the document, its job state, and the latest extraction.

    Answers while processing is still running, with a null extraction. That is
    what the frontend polls: the alternative — 404 until ready — is
    indistinguishable from a document that does not exist.
    """
    document = imports_uc.get_document(session, user.id, source_document_id)
    job = imports_uc.latest_job_for_document(session, user.id, source_document_id)
    extraction = imports_uc.latest_extraction(session, user.id, source_document_id)

    payload: ExtractionPayload | None = None
    if extraction is not None:
        items = imports_uc.extraction_items(session, extraction.id)
        payload = ExtractionPayload(
            id=extraction.id,
            version=extraction.version,
            prompt_version=extraction.prompt_version,
            model=extraction.model,
            provider=extraction.provider,
            warnings=list(extraction.warnings),
            confirmed_at=extraction.confirmed_at,
            items=[
                ExtractionItemPayload(
                    id=item.id,
                    candidate_type=CandidateType(item.candidate_type),
                    parent_item_id=item.parent_item_id,
                    display_order=item.display_order,
                    payload=item.payload,
                    edited_payload=item.edited_payload,
                    confidence=item.confidence,
                    source_text=item.source_text,
                    decision=CandidateDecision(item.decision),
                    target_entity_type=item.target_entity_type,
                    target_entity_id=item.target_entity_id,
                )
                for item in items
            ],
        )

    return DataResponse(
        data=ExtractionReviewPayload(
            document=DocumentPayload.model_validate(document),
            job=_job_payload(job),
            extraction=payload,
        )
    )


@router.post(
    "/imports/{source_document_id}/confirm",
    response_model=DataResponse[ConfirmationPayload],
    summary="Accept, edit, or ignore extracted items",
)
def confirm_extraction(
    user: CurrentUser,
    session: SessionDep,
    source_document_id: uuid.UUID,
    body: ConfirmRequest,
) -> DataResponse[ConfirmationPayload]:
    """Apply the user's decisions to their career profile.

    Every write goes through the career application services. Sending the same
    decisions again is safe: an item that already produced a record reports
    ``ALREADY_APPLIED`` and writes nothing.
    """
    imports_uc.get_document(session, user.id, source_document_id)
    extraction = imports_uc.latest_extraction(session, user.id, source_document_id)
    if extraction is None:
        raise ResourceNotFoundError("There is nothing to confirm for this document yet.")

    result = confirm_uc.confirm_extraction(
        session,
        user_id=user.id,
        extraction=extraction,
        decisions=[
            confirm_uc.Decision(item_id=d.item_id, action=d.action, payload=d.payload)
            for d in body.decisions
        ],
    )
    session.commit()

    return DataResponse(
        data=ConfirmationPayload(
            applied=[
                AppliedItemPayload(
                    item_id=item.item_id,
                    candidate_type=item.candidate_type,
                    outcome=item.outcome,
                    target_entity_type=item.target_entity_type,
                    target_entity_id=item.target_entity_id,
                    detail=item.detail,
                )
                for item in result.applied
            ],
            created_count=result.created_count,
            remaining_pending=result.remaining_pending,
        )
    )


@router.get(
    "/imports/{source_document_id}/file",
    response_model=DataResponse[SignedUrlPayload],
    summary="Get a temporary link to the original file",
)
def read_document_url(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    source_document_id: uuid.UUID,
) -> DataResponse[SignedUrlPayload]:
    """Return a short-lived signed URL.

    Ownership is checked before the URL is minted, and the URL expires — a
    permanent public link to a resume would make it readable by anyone who ever
    saw it.
    """
    document = imports_uc.get_document(session, user.id, source_document_id)
    ttl = settings.storage_signed_url_ttl_seconds
    return DataResponse(
        data=SignedUrlPayload(
            url=imports_uc.signed_download_url(storage, document, expires_in_seconds=ttl),
            expires_in_seconds=ttl,
        )
    )


@router.get(
    "/supported-formats",
    response_model=DataResponse[list[str]],
    summary="File types the importer accepts",
)
def read_supported_formats() -> DataResponse[list[str]]:
    """The formats that work end to end.

    Served from the same table upload validation uses, so the accept filter in
    the browser cannot drift from what the API will take.
    """
    return DataResponse(data=sorted(ALLOWED_UPLOAD_TYPES))


def _job_payload(job: object | None) -> ProcessingJobPayload | None:
    return ProcessingJobPayload.model_validate(job) if job is not None else None
