"""Processing job status and retry.

The polling half of the async pattern in ``docs/10-api-contracts.md``. Kept
separate from the resume routes because a job is not a resume — Phase 4 onward
will report job import and matching through exactly these two endpoints.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep
from jip_api.application.processing import jobs as jobs_uc
from jip_api.application.resumes import imports as imports_uc
from jip_api.core.responses import DataResponse
from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
    ProcessingStep,
)
from jip_api.infrastructure.db.session import get_session
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher

router = APIRouter(prefix="/processing-jobs", tags=["processing"])

SessionDep = Annotated[Session, Depends(get_session)]


class ProcessingJobPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ProcessingJobKind
    status: ProcessingJobStatus
    step: ProcessingStep
    entity_type: str
    entity_id: uuid.UUID
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    is_retriable: bool


@router.get(
    "/{job_id}",
    response_model=DataResponse[ProcessingJobPayload],
    summary="Get processing job status",
)
def read_job(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[ProcessingJobPayload]:
    job = jobs_uc.get_job(session, user.id, job_id)
    return DataResponse(data=ProcessingJobPayload.model_validate(job))


@router.post(
    "/{job_id}/retry",
    response_model=DataResponse[ProcessingJobPayload],
    summary="Retry a failed processing job",
)
def retry_job(
    user: CurrentUser, session: SessionDep, dispatcher: DispatcherDep, job_id: uuid.UUID
) -> DataResponse[ProcessingJobPayload]:
    """Queue a failed job again.

    Refused for a failure a retry cannot fix — a scanned PDF with no text layer
    will not gain one. The document is never re-uploaded and, where extraction
    already succeeded, never re-extracted: the retry resumes from the step that
    failed.
    """
    job = jobs_uc.get_job(session, user.id, job_id)
    jobs_uc.prepare_retry(session, job)
    session.commit()

    _dispatch(session, dispatcher, job)
    return DataResponse(data=ProcessingJobPayload.model_validate(job))


def _dispatch(session: Session, dispatcher: TaskDispatcher, job: ProcessingJob) -> None:
    """Re-queue a job by kind."""
    if ProcessingJobKind(job.kind) is ProcessingJobKind.RESUME_IMPORT:
        imports_uc.dispatch(session, dispatcher, job)
