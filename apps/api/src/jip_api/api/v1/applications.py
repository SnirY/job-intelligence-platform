"""The application tracker.

The routes from ``docs/10-api-contracts.md``. Every status change goes through
one service call that writes the status and its event together, because
``docs/11-engineering-standards.md`` requires exactly that and a second path
would be indistinguishable from correct until someone read a timeline with a
hole in it.

Each payload carries ``allowed_transitions`` rather than leaving the board to
infer them. The alternative is the Kanban duplicating the lifecycle table in
TypeScript, which is two copies of a rule that has to agree — and the one that
drifts is the one the user sees.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.applications import service
from jip_api.core.responses import DataResponse
from jip_api.domain.applications.models import (
    Application,
    ApplicationEventType,
    ApplicationSource,
    ApplicationStatus,
)
from jip_api.domain.applications.transitions import allowed_from
from jip_api.domain.jobs.models import Job
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/applications", tags=["applications"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class ApplicationPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    status: ApplicationStatus
    resume_version_id: uuid.UUID | None
    applied_at: dt.datetime | None
    source: ApplicationSource | None
    notes: str | None
    rejection_feedback: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

    # Denormalised for the board. A Kanban card shows the role and the company,
    # and fetching each job separately would be one request per card.
    job_title: str = ""
    company: str | None = None

    allowed_transitions: list[ApplicationStatus] = []
    days_in_stage: int | None = None
    """Derived from the events, not from a stored column.

    The history already records every move exactly; a denormalised
    ``entered_stage_at`` would be a second source of truth for the same fact,
    and it would drift the first time a status changed by a path that forgot to
    update it.
    """


class ApplicationEventPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: ApplicationEventType
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    occurred_at: dt.datetime
    summary: str
    detail: str | None


class CreateRequest(BaseModel):
    job_id: uuid.UUID
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: str | None = Field(default=None, max_length=5000)


class StatusRequest(BaseModel):
    status: ApplicationStatus
    occurred_at: dt.datetime | None = None
    detail: str | None = Field(default=None, max_length=2000)


class ApplyRequest(BaseModel):
    resume_version_id: uuid.UUID | None = None
    source: ApplicationSource | None = None
    applied_at: dt.datetime | None = None
    detail: str | None = Field(default=None, max_length=2000)


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    occurred_at: dt.datetime | None = None


class FeedbackRequest(BaseModel):
    feedback: str = Field(max_length=5000)


class UpdateRequest(BaseModel):
    """The freely-editable fields. Status is deliberately absent.

    Allowing it here would be the second write path the module docstring warns
    about — one that changes a status without recording why.
    """

    notes: str | None = Field(default=None, max_length=5000)


# --- routes -------------------------------------------------------------------


@router.post(
    "",
    response_model=DataResponse[ApplicationPayload],
    status_code=http_status.HTTP_201_CREATED,
    summary="Start tracking an application",
)
def create(
    user: CurrentUser, session: SessionDep, body: CreateRequest
) -> DataResponse[ApplicationPayload]:
    """Explicit, not automatic.

    A job the user glanced at is not a relationship with an opportunity. If
    every saved job produced an application, the two words would be synonyms and
    the funnel's first conversion rate would always be 100%.
    """
    application = service.create_application(
        session, user.id, job_id=body.job_id, status=body.status, notes=body.notes
    )
    session.commit()
    return DataResponse(data=_payload(session, application))


@router.get("", response_model=DataResponse[list[ApplicationPayload]], summary="List applications")
def list_applications(
    user: CurrentUser,
    session: SessionDep,
    include_archived: Annotated[bool, Query()] = False,
) -> DataResponse[list[ApplicationPayload]]:
    """Everything the board draws, in one request.

    Not paginated: this is a personal tracker, and a Kanban that only shows the
    first page of a column is worse than no board. If someone reaches a
    thousand applications, that is a different screen.
    """
    rows = service.list_applications(session, user.id, include_archived=include_archived)
    jobs = _jobs_for(session, [row.job_id for row in rows])
    stages = service.days_in_stage_for(session, [row.id for row in rows])

    return DataResponse(
        data=[_payload(session, row, jobs=jobs, days=stages.get(row.id)) for row in rows]
    )


@router.get(
    "/{application_id}",
    response_model=DataResponse[ApplicationPayload],
    summary="Get one application",
)
def read(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID
) -> DataResponse[ApplicationPayload]:
    application = service.get_application(session, user.id, application_id)
    return DataResponse(data=_payload(session, application))


@router.patch(
    "/{application_id}",
    response_model=DataResponse[ApplicationPayload],
    summary="Edit an application's notes",
)
def update(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID, body: UpdateRequest
) -> DataResponse[ApplicationPayload]:
    application = service.get_application(session, user.id, application_id)
    application.notes = (body.notes or "").strip() or None
    session.commit()
    return DataResponse(data=_payload(session, application))


@router.patch(
    "/{application_id}/status",
    response_model=DataResponse[ApplicationPayload],
    summary="Move an application to another status",
)
def change_status(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID, body: StatusRequest
) -> DataResponse[ApplicationPayload]:
    """One transaction: the status and the event that explains it.

    Refused with a written reason when the lifecycle forbids the move, because
    "invalid transition" tells the user nothing about what they did.
    """
    application = service.get_application(session, user.id, application_id)
    service.transition(
        session, application, body.status, occurred_at=body.occurred_at, detail=body.detail
    )
    session.commit()
    return DataResponse(data=_payload(session, application))


@router.post(
    "/{application_id}/apply",
    response_model=DataResponse[ApplicationPayload],
    summary="Record that the application was sent",
)
def apply(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID, body: ApplyRequest
) -> DataResponse[ApplicationPayload]:
    """Pins the exact resume version and freezes it.

    ``docs/07`` requires the date, the version, and the source preserved. The
    freeze is the part that matters afterwards: from here the document is what
    an employer read, and editing it would rewrite what was sent.
    """
    application = service.get_application(session, user.id, application_id)
    service.mark_applied(
        session,
        application,
        resume_version_id=body.resume_version_id,
        source=body.source,
        applied_at=body.applied_at,
        detail=body.detail,
    )
    session.commit()
    return DataResponse(data=_payload(session, application))


@router.get(
    "/{application_id}/events",
    response_model=DataResponse[list[ApplicationEventPayload]],
    summary="The application's timeline",
)
def read_events(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID
) -> DataResponse[list[ApplicationEventPayload]]:
    service.get_application(session, user.id, application_id)
    events = service.events_for(session, application_id)
    return DataResponse(data=[ApplicationEventPayload.model_validate(e) for e in events])


@router.post(
    "/{application_id}/notes",
    response_model=DataResponse[ApplicationEventPayload],
    status_code=http_status.HTTP_201_CREATED,
    summary="Add a note to the timeline",
)
def add_note(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID, body: NoteRequest
) -> DataResponse[ApplicationEventPayload]:
    application = service.get_application(session, user.id, application_id)
    event = service.add_note(session, application, body.text, occurred_at=body.occurred_at)
    session.commit()
    return DataResponse(data=ApplicationEventPayload.model_validate(event))


@router.post(
    "/{application_id}/feedback",
    response_model=DataResponse[ApplicationPayload],
    summary="Record feedback the employer actually gave",
)
def record_feedback(
    user: CurrentUser, session: SessionDep, application_id: uuid.UUID, body: FeedbackRequest
) -> DataResponse[ApplicationPayload]:
    """The user's record of what was said, in their words.

    Its own field rather than a note, because ``docs/07`` requires known
    feedback kept apart from system inference and forbids presenting a guessed
    reason as fact. Nothing writes here but this route.
    """
    application = service.get_application(session, user.id, application_id)
    service.record_feedback(session, application, body.feedback)
    session.commit()
    return DataResponse(data=_payload(session, application))


# --- helpers ------------------------------------------------------------------


def _jobs_for(session: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, Job]:
    if not job_ids:
        return {}
    rows = session.execute(select(Job).where(Job.id.in_(job_ids))).scalars()
    return {job.id: job for job in rows}


def _payload(
    session: Session,
    application: Application,
    *,
    jobs: dict[uuid.UUID, Job] | None = None,
    days: int | None = None,
) -> ApplicationPayload:
    payload = ApplicationPayload.model_validate(application)

    job = (jobs or {}).get(application.job_id) or session.get(Job, application.job_id)
    if job is not None:
        payload.job_title = job.title
        payload.company = job.company

    payload.allowed_transitions = sorted(allowed_from(application.status))
    payload.days_in_stage = (
        days if days is not None else service.days_in_stage(session, application.id)
    )
    return payload
