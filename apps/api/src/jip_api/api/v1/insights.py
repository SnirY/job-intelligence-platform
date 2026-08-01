"""`GET /api/v1/insights/*`.

Three of the five routes ``docs/10-api-contracts.md`` lists. The two that are
missing are missing on purpose, and the reasons are different:

- **`/insights/roles`** — role analysis is average alignment per role family.
  An average of scores, scores built from importance weights, and importance is
  the field DEV-026 measured moving on unchanged input. It waits for
  calibration rather than shipping a figure that moves when nothing has.
- **`/insights/applications/funnel`** — the inputs are stable, since statuses
  are typed by a person rather than inferred. What it lacks is rows. ``docs/07``
  requires explicit minimum-data thresholds, and a conversion rate is the
  clearest case of a number that means nothing until there is something to
  divide by.

Both are absent rather than present-and-empty, because an endpoint returning
zeroes is indistinguishable from one that is broken, and a route that exists is
a promise the frontend will eventually call.

Every payload here carries ``analysed_jobs``. No figure on this screen is
quotable without its denominator.
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
from jip_api.core.responses import DataResponse
from jip_api.domain.jobs.analysis import RequirementImportance
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


def _payloads(skills: list[SkillDemand]) -> list[SkillDemandPayload]:
    return [SkillDemandPayload.model_validate(skill) for skill in skills]
