"""`GET /api/v1/dashboard`.

One aggregate endpoint, as ``docs/10-api-contracts.md`` specifies, rather than
the six the screen would otherwise need. The alternative is a home page that
cannot render until six requests have all returned, and which shows six
separate loading states on a slow connection.

The payloads here are shapes, not decisions. Every value comes from
:mod:`jip_api.application.dashboard.service`, which reads what the other phases
already stored — this module's only job is to name the fields and let FastAPI
serialise them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.dashboard.actions import ActionKind
from jip_api.application.dashboard.service import build_dashboard
from jip_api.core.responses import DataResponse
from jip_api.domain.applications.models import ApplicationStatus
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class CurrentStatePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    jobs_saved: int
    jobs_analysed: int
    jobs_matched: int
    applications_live: int
    profile_skills: int


class PipelineStagePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: ApplicationStatus
    count: int
    before_applying: bool


class OpportunityPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    title: str
    company: str | None
    score: int | None
    alignment_label: str | None
    is_stale: bool
    has_application: bool


class NextActionPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: ActionKind
    subject: str
    reason: str
    """The evidence behind the suggestion.

    Required rather than optional, because ``docs/07`` asks every insight to
    carry the observation it came from — an action with no reason is a
    recommendation the user has to take on trust.
    """

    job_id: uuid.UUID | None
    application_id: uuid.UUID | None


class ActivityPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: dt.datetime
    kind: str
    subject: str
    job_id: uuid.UUID | None


class SkillGapPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: uuid.UUID
    name: str
    asked_by_jobs: int


class DashboardPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state: CurrentStatePayload
    pipeline: list[PipelineStagePayload]
    opportunities: list[OpportunityPayload]
    actions: list[NextActionPayload]
    activity: list[ActivityPayload]
    skill_gaps: list[SkillGapPayload]


# --- route --------------------------------------------------------------------


@router.get("", response_model=DataResponse[DashboardPayload], summary="Everything at a glance")
def read_dashboard(user: CurrentUser, session: SessionDep) -> DataResponse[DashboardPayload]:
    """The home screen, assembled from what already exists.

    Answers 200 with empty lists for a new account rather than 404. There is
    nothing missing — the user simply has not done anything yet, and the screen
    says so in its own words.
    """
    return DataResponse(data=DashboardPayload.model_validate(build_dashboard(session, user.id)))
