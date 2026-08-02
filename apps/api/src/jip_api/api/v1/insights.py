"""`GET /api/v1/insights/*`.

All five routes ``docs/10-api-contracts.md`` lists, plus resume performance.

Role analysis shipped later than the rest and for a reason worth keeping: it was
held back on DEV-026, which said requirement importance moves between readings
and therefore poisons any average of alignment scores. Two five-reading
measurements found otherwise — keyed by resolved skill, importance moved once in
twenty-four labels across two postings, and what actually varies is which
requirements get extracted and how they are worded. That varies between
alternative readings of one posting, and in production a posting is read once.

So the blocker was never importance. It is sample size, which is the rule
``docs/07`` already states twice and which every figure here now carries:

- a share is quoted with the number of postings it was counted over;
- a role family's average alignment is null below three jobs;
- no conversion rate is computed below five applications, though the stage
  counts are still shown, because those are facts.

Nothing is ever zero where it means "not measured". Zero is a claim.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.insights.demand import (
    MINIMUM_JOBS,
    DemandReport,
    SkillDemand,
    build_demand,
    build_gaps,
)
from jip_api.application.insights.gaps import GapState
from jip_api.application.insights.performance import (
    MINIMUM_APPLICATIONS,
    MINIMUM_JOBS_PER_ROLE,
    build_funnel,
    build_resume_performance,
    build_roles,
)
from jip_api.core.responses import DataResponse
from jip_api.domain.jobs.analysis import RequirementImportance, RoleFamily
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/insights", tags=["insights"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class SkillDemandPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    skill_id: uuid.UUID | None
    name: str
    catalogued: bool
    jobs: int
    share: int
    importance: dict[RequirementImportance, int]
    role_families: dict[str, int]
    state: GapState
    held: bool


class DemandPayload(BaseModel):
    analysed_jobs: int
    """The denominator. Always sent, so the client cannot render a share
    without the sample it came from."""

    minimum_jobs: int
    """The threshold, sent rather than duplicated in TypeScript — the number
    and the sentence explaining it have to agree, and two copies drift."""

    above_threshold: bool
    skills: list[SkillDemandPayload]


class GapsPayload(BaseModel):
    analysed_jobs: int
    minimum_jobs: int
    above_threshold: bool
    gaps: list[SkillDemandPayload]


class OverviewPayload(BaseModel):
    analysed_jobs: int
    minimum_jobs: int
    above_threshold: bool
    skills_tracked: int
    gaps_found: int
    top_skills: list[SkillDemandPayload]
    top_gaps: list[SkillDemandPayload]


# --- routes -------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=DataResponse[OverviewPayload],
    summary="What the saved jobs add up to",
)
def read_overview(user: CurrentUser, session: SessionDep) -> DataResponse[OverviewPayload]:
    report = build_demand(session, user.id)
    gaps = build_gaps(report)

    return DataResponse(
        data=OverviewPayload(
            analysed_jobs=report.analysed_jobs,
            minimum_jobs=MINIMUM_JOBS,
            above_threshold=report.is_above_threshold,
            skills_tracked=len(report.skills),
            gaps_found=len(gaps),
            top_skills=_payloads(report.skills[:5]),
            top_gaps=_payloads(gaps[:5]),
        )
    )


@router.get(
    "/skills/demand",
    response_model=DataResponse[DemandPayload],
    summary="Which skills the saved jobs ask for",
)
def read_demand(user: CurrentUser, session: SessionDep) -> DataResponse[DemandPayload]:
    report = build_demand(session, user.id)

    return DataResponse(
        data=DemandPayload(
            analysed_jobs=report.analysed_jobs,
            minimum_jobs=MINIMUM_JOBS,
            above_threshold=report.is_above_threshold,
            skills=_payloads(report.skills),
        )
    )


@router.get(
    "/skills/gaps",
    response_model=DataResponse[GapsPayload],
    summary="Which of those the profile does not answer",
)
def read_gaps(user: CurrentUser, session: SessionDep) -> DataResponse[GapsPayload]:
    report: DemandReport = build_demand(session, user.id)

    return DataResponse(
        data=GapsPayload(
            analysed_jobs=report.analysed_jobs,
            minimum_jobs=MINIMUM_JOBS,
            above_threshold=report.is_above_threshold,
            gaps=_payloads(build_gaps(report)),
        )
    )


class RoleInsightPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_family: RoleFamily
    jobs: int
    matched: int
    average_alignment: int | None
    """Null below the threshold, and null when nothing in the family scored.
    Never zero, which would be a claim about fit rather than about data."""

    applications: int


class RolesPayload(BaseModel):
    minimum_jobs: int
    roles: list[RoleInsightPayload]


class FunnelStagePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    reached: int


class FunnelPayload(BaseModel):
    applications: int
    minimum_applications: int
    rates_are_meaningful: bool
    """Whether the client may divide these counts. Sent rather than left to the
    frontend to decide, so the threshold lives in one place."""

    stages: list[FunnelStagePayload]


class ResumeInsightPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resume_version_id: uuid.UUID
    label: str
    sent: int
    reached_interview: int
    offers: int


class ResumePerformancePayload(BaseModel):
    minimum_applications: int
    rates_are_meaningful: bool
    versions: list[ResumeInsightPayload]


@router.get(
    "/roles",
    response_model=DataResponse[RolesPayload],
    summary="How the saved jobs group by role family",
)
def read_roles(user: CurrentUser, session: SessionDep) -> DataResponse[RolesPayload]:
    report = build_roles(session, user.id)

    return DataResponse(
        data=RolesPayload(
            minimum_jobs=MINIMUM_JOBS_PER_ROLE,
            roles=[RoleInsightPayload.model_validate(role) for role in report.roles],
        )
    )


@router.get(
    "/applications/funnel",
    response_model=DataResponse[FunnelPayload],
    summary="How far applications have got",
)
def read_funnel(user: CurrentUser, session: SessionDep) -> DataResponse[FunnelPayload]:
    report = build_funnel(session, user.id)

    return DataResponse(
        data=FunnelPayload(
            applications=report.applications,
            minimum_applications=MINIMUM_APPLICATIONS,
            rates_are_meaningful=report.rates_are_meaningful,
            stages=[FunnelStagePayload.model_validate(stage) for stage in report.stages],
        )
    )


@router.get(
    "/resumes",
    response_model=DataResponse[ResumePerformancePayload],
    summary="What happened after each resume version was sent",
)
def read_resume_performance(
    user: CurrentUser, session: SessionDep
) -> DataResponse[ResumePerformancePayload]:
    versions = build_resume_performance(session, user.id)

    return DataResponse(
        data=ResumePerformancePayload(
            minimum_applications=MINIMUM_APPLICATIONS,
            rates_are_meaningful=sum(v.sent for v in versions) >= MINIMUM_APPLICATIONS,
            versions=[ResumeInsightPayload.model_validate(version) for version in versions],
        )
    )


def _payloads(skills: list[SkillDemand]) -> list[SkillDemandPayload]:
    return [SkillDemandPayload.model_validate(skill) for skill in skills]
