"""`GET`/`POST /api/v1/skill-candidates`.

DEV-062, candidate 2. The review queue for technologies a posting named and the
canonical catalogue could not resolve.

**Authenticated but not user-scoped, and that is the unusual thing here.** Every
other collection in this API is filtered by `user_id`; `skills` and
`skill_aliases` are not, because the catalogue is shared, and the queue that
feeds it inherits that. One reviewer accepting "Playwright" makes the name
resolvable for everyone.

That is safe for a reason worth stating rather than assuming: **nothing in the
queue is profile data.** A candidate holds a term a public job posting used and
a count of how many postings used it. It carries no reference to a user, a job,
or a match.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.jobs import skill_candidates as candidates_uc
from jip_api.core.responses import DataResponse
from jip_api.domain.career.skills import CandidateStatus, SkillCategory
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/skill-candidates", tags=["skill-candidates"])

SessionDep = Annotated[Session, Depends(get_session)]

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class CandidatePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    normalized_name: str
    display_name: str
    occurrences: int
    status: CandidateStatus
    resolved_skill_id: uuid.UUID | None
    note: str | None
    example_source_text: str | None
    """The posting's own sentence. Without it a reviewer deciding `CAN` is
    guessing at a three-letter string that is also an ordinary English word."""
    example_job_title: str | None


class AcceptAsAliasRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: uuid.UUID
    """The catalogue entry this name is another way of writing."""

    note: Note | None = None


class AcceptAsNewSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: SkillCategory
    canonical_name: str | None = Field(default=None, min_length=1, max_length=120)
    """Lets the reviewer correct the posting's spelling. The posting's own
    wording is kept as an alias either way, so the requirement still resolves."""

    note: Note | None = None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note | None = None
    """Why this is not a skill. Optional, and worth filling in — the queue is
    rebuilt from the postings, so a rejection is the only record of a decision
    somebody will otherwise re-make."""


@router.get(
    "",
    response_model=DataResponse[list[CandidatePayload]],
    summary="List skill names awaiting review",
)
def read_candidates(
    _: CurrentUser, session: SessionDep, status_filter: CandidateStatus | None = None
) -> DataResponse[list[CandidatePayload]]:
    rows = candidates_uc.list_candidates(session, status_filter)
    return DataResponse(data=[CandidatePayload.model_validate(row) for row in rows])


@router.post(
    "/refresh",
    response_model=DataResponse[list[CandidatePayload]],
    summary="Rebuild the queue from stored requirements",
)
def refresh(_: CurrentUser, session: SessionDep) -> DataResponse[list[CandidatePayload]]:
    """Re-resolve, then re-count.

    The re-resolve half matters more than the queue: a catalogue migration adds
    skills and nothing points the already-stored requirements at them, so names
    sit unresolved while the skill they mean is right there. That is what
    happened to HTML and CSS.
    """
    rows = candidates_uc.refresh_candidates(session)
    session.commit()
    return DataResponse(data=[CandidatePayload.model_validate(row) for row in rows])


@router.post(
    "/{candidate_id}/accept-alias",
    response_model=DataResponse[CandidatePayload],
    summary="Map the name onto an existing skill",
)
def accept_alias(
    _: CurrentUser, session: SessionDep, candidate_id: uuid.UUID, body: AcceptAsAliasRequest
) -> DataResponse[CandidatePayload]:
    row = candidates_uc.accept_as_alias(session, candidate_id, body.skill_id, body.note)
    session.commit()
    return DataResponse(data=CandidatePayload.model_validate(row))


@router.post(
    "/{candidate_id}/accept-new",
    response_model=DataResponse[CandidatePayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add the name to the catalogue as a new skill",
)
def accept_new(
    _: CurrentUser, session: SessionDep, candidate_id: uuid.UUID, body: AcceptAsNewSkillRequest
) -> DataResponse[CandidatePayload]:
    row = candidates_uc.accept_as_new_skill(
        session, candidate_id, body.category, body.canonical_name, body.note
    )
    session.commit()
    return DataResponse(data=CandidatePayload.model_validate(row))


@router.post(
    "/{candidate_id}/reject",
    response_model=DataResponse[CandidatePayload],
    summary="Record that this is not a skill",
)
def reject(
    _: CurrentUser, session: SessionDep, candidate_id: uuid.UUID, body: RejectRequest
) -> DataResponse[CandidatePayload]:
    row = candidates_uc.reject(session, candidate_id, body.note)
    session.commit()
    return DataResponse(data=CandidatePayload.model_validate(row))
