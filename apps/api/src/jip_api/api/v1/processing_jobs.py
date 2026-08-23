"""Processing job status and retry.

The polling half of the async pattern in ``docs/10-api-contracts.md``. Kept
separate from the resume routes because a job is not a resume — Phase 4 onward
will report job import and matching through exactly these two endpoints.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep
from jip_api.application.jobs import analysis_uc
from jip_api.application.processing import jobs as jobs_uc
from jip_api.application.processing import reaper
from jip_api.application.resumes import imports as imports_uc
from jip_api.core.responses import DataResponse
from jip_api.domain.documents.models import SourceDocument
from jip_api.domain.jobs.models import Job
from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
    ProcessingStep,
)
from jip_api.infrastructure.db.session import get_session
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher
from jip_config import get_settings

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

    can_be_retried: bool
    """Whether trying again could plausibly work.

    Sent rather than left for the caller to derive: three fields have to agree,
    and a screen that recomputed the rule would be a second place for it to
    drift from `prepare_retry`."""

    is_dead: bool
    """Failed, and no retry will change that. The dead-letter answer."""

    finished_at: dt.datetime | None


class FailedJobPayload(ProcessingJobPayload):
    """A failure, with enough context to know what it was.

    `entity_id` alone says nothing to a person — it is a UUID for a resume or a
    job they would have to go and look up. `entity_label` is what that row is
    called, resolved once here rather than by a screen making N more requests.
    """

    entity_label: str | None


@router.get(
    "/failures",
    response_model=DataResponse[list[FailedJobPayload]],
    summary="Background work that did not finish",
)
def read_failures(user: CurrentUser, session: SessionDep) -> DataResponse[list[FailedJobPayload]]:
    """Everything that failed, newest first.

    Phase 11 listed a dead-letter path and "any view across failures" as the
    half of retry flows that did not exist. Until now a failed job was reachable
    only by its id, so the only way to find one was to already know it had
    failed.

    Declared before `/{job_id}` on purpose: FastAPI matches in declaration
    order, and the other way round "failures" is a job id that fails to parse as
    a UUID.
    """
    failures = jobs_uc.list_failures(session, user.id)
    return DataResponse(data=[_failure_payload(session, job) for job in failures])


def _failure_payload(session: Session, job: ProcessingJob) -> FailedJobPayload:
    """One failure, with the name of the thing it was working on.

    Resolved here rather than by the screen, which would otherwise make one
    request per row to turn a UUID into a filename. Unknown entity types return
    `None` rather than raising: a job kind added later must show up in this list
    as an unlabelled row, not break the page that is supposed to be reporting
    trouble.
    """
    # Built in one pass rather than validated and then assigned: `entity_label`
    # is required and does not exist on the ORM row, so validating first raises
    # before there is anything to assign to.
    return FailedJobPayload(
        **ProcessingJobPayload.model_validate(job).model_dump(),
        entity_label=_entity_label(session, job),
    )


def _entity_label(session: Session, job: ProcessingJob) -> str | None:
    if job.entity_type == "job":
        row = session.get(Job, job.entity_id)
        return row.title if row else None
    if job.entity_type == "source_document":
        document = session.get(SourceDocument, job.entity_id)
        return document.original_filename if document else None
    return None


@router.get(
    "/{job_id}",
    response_model=DataResponse[ProcessingJobPayload],
    summary="Get processing job status",
)
def read_job(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[ProcessingJobPayload]:
    """Status, with a stalled job failed on the way past.

    The read is where a dead job is noticed, because this is what the frontend
    polls — see DEV-013 and the reasoning in ``reaper.py``. Without it a worker
    that died before writing a status leaves "Waiting to start" on screen with
    no action available and nothing that will ever change it.
    """
    job = jobs_uc.get_job(session, user.id, job_id)

    settings = get_settings()
    if reaper.reap_if_stalled(
        session,
        job,
        pending_timeout_seconds=settings.processing_pending_timeout_seconds,
        running_timeout_seconds=settings.processing_running_timeout_seconds,
    ):
        session.commit()

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
    """Re-queue a job by kind.

    Every kind must appear here. A missing branch is silent: the job is set back
    to PENDING and never enqueued, so a retry returns 200 and puts it straight
    back into the stalled state the retry was meant to escape.
    """
    kind = ProcessingJobKind(job.kind)
    if kind is ProcessingJobKind.RESUME_IMPORT:
        imports_uc.dispatch(session, dispatcher, job)
    elif kind is ProcessingJobKind.JOB_ANALYSIS:
        analysis_uc.dispatch(session, dispatcher, job)
