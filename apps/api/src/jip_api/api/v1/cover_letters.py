"""Cover letters — drafting one, reading it, changing it, clearing it.

Two routers, because the resource is reached two ways and both are natural. A
letter is *made for a job*, so drafting and reading hang off `/jobs/{id}`; once
it exists it is its own thing with its own id, so editing and approval hang off
`/cover-letters/{id}`. `resume_authoring` splits for the same reason.

**The claims travel with the letter rather than in a separate call.** They are
not supplementary detail — a draft with a blocked claim is a draft the user must
not send, and a payload that made the warning optional to fetch would make it
optional to see.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep
from jip_api.application.jobs import queries as queries_uc
from jip_api.application.resumes import cover_letters as cover_letters_uc
from jip_api.core.errors import NotFoundError
from jip_api.core.responses import DataResponse
from jip_api.domain.resumes.cover_letters import CoverLetter, CoverLetterStatus
from jip_api.domain.resumes.tailoring import ClaimStatus
from jip_api.infrastructure.db.session import get_session
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher

router = APIRouter(prefix="/cover-letters", tags=["cover letters"])
job_router = APIRouter(prefix="/jobs", tags=["cover letters"])

SessionDep = Annotated[Session, Depends(get_session)]


class CoverLetterClaimPayload(BaseModel):
    """One assertion from the draft, and what validation made of it."""

    model_config = ConfigDict(from_attributes=True)

    text: str
    status: ClaimStatus
    explanation: str
    confidence: int


class CoverLetterPayload(BaseModel):
    """A letter, with everything needed to decide whether to use it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    status: CoverLetterStatus
    angle: str | None
    body: str | None
    angle_warning: str | None
    """The model saying the angle asked for is not supported by the facts.

    Surfaced rather than logged: when it is set, it is usually the most useful
    thing the draft has to say."""

    error: str | None
    edited_at: dt.datetime | None
    approved_at: dt.datetime | None
    created_at: dt.datetime

    claims: list[CoverLetterClaimPayload] = Field(default_factory=list)
    """What validation concluded, always present. See the module docstring."""


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    """The argument this letter should make. Omitted means the default, which
    deliberately takes no position — an angle is the user's to choose."""


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]


def _payload(session: Session, letter: CoverLetter) -> CoverLetterPayload:
    payload = CoverLetterPayload.model_validate(letter)
    payload.claims = [
        CoverLetterClaimPayload.model_validate(claim)
        for claim in cover_letters_uc.claims_for(session, letter.id)
    ]
    return payload


def _get_letter(session: Session, user_id: uuid.UUID, letter_id: uuid.UUID) -> CoverLetter:
    letter = session.get(CoverLetter, letter_id)
    if letter is None or letter.user_id != user_id:
        # The same answer whether it is missing or simply not theirs, per
        # `docs/10-api-contracts.md`.
        raise NotFoundError("That cover letter does not exist.")
    return letter


@job_router.get(
    "/{job_id}/cover-letter",
    response_model=DataResponse[CoverLetterPayload | None],
    summary="The latest cover letter for a job",
)
def read_cover_letter(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[CoverLetterPayload | None]:
    """Null when none has been written. That is an ordinary state, not an error."""
    queries_uc.get_job(session, user.id, job_id)
    letter = cover_letters_uc.latest_for_job(session, user.id, job_id)
    return DataResponse(data=_payload(session, letter) if letter else None)


@job_router.post(
    "/{job_id}/cover-letter",
    response_model=DataResponse[CoverLetterPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Draft a cover letter for a job",
)
def post_cover_letter(
    user: CurrentUser,
    session: SessionDep,
    dispatcher: DispatcherDep,
    job_id: uuid.UUID,
    body: DraftRequest,
) -> DataResponse[CoverLetterPayload]:
    """Queue a draft.

    Answers immediately with the row in DRAFTING, which is what the caller polls.
    A model call takes seconds and must not hold an HTTP request open — the same
    reason job analysis is background work.
    """
    job = queries_uc.get_job(session, user.id, job_id)
    letter = cover_letters_uc.start_draft(session, user.id, job, angle=body.angle)
    session.commit()

    _dispatch(session, dispatcher, letter)
    return DataResponse(data=_payload(session, letter))


@router.patch(
    "/{letter_id}",
    response_model=DataResponse[CoverLetterPayload],
    summary="Change the text of a letter",
)
def patch_cover_letter(
    user: CurrentUser, session: SessionDep, letter_id: uuid.UUID, body: EditRequest
) -> DataResponse[CoverLetterPayload]:
    """What a person writes about themselves is theirs.

    The edit is not re-validated. The claims attached to this letter were
    computed against the model's words, and running a fabrication check over the
    user's own sentences would be the system second-guessing the one source it
    treats as authoritative. The status moves to EDITED so nothing reads those
    claims as describing the current text.
    """
    letter = _get_letter(session, user.id, letter_id)
    cover_letters_uc.edit(session, letter, body=body.body)
    session.commit()
    return DataResponse(data=_payload(session, letter))


@router.post(
    "/{letter_id}/approve",
    response_model=DataResponse[CoverLetterPayload],
    summary="Mark a letter as one you are happy with",
)
def post_approve(
    user: CurrentUser, session: SessionDep, letter_id: uuid.UUID
) -> DataResponse[CoverLetterPayload]:
    """Approval is a person's act and the only thing that makes a letter usable.

    Deliberately allowed even when a claim is blocked. The user may know the
    figure is real — `docs/06` wants the system to *ask* for a missing metric,
    not to refuse the document — and the screen shows them what they are
    approving over.
    """
    letter = _get_letter(session, user.id, letter_id)
    cover_letters_uc.approve(session, letter)
    session.commit()
    return DataResponse(data=_payload(session, letter))


def _dispatch(session: Session, dispatcher: TaskDispatcher, letter: CoverLetter) -> None:
    """Queue the draft, recording a queue outage on the letter.

    Unlike a liveness check, there *is* a row waiting in DRAFTING — leaving it
    there with nothing running would be a spinner that never resolves. So the
    outage lands on the row, the way a failed import does.
    """
    try:
        dispatcher.enqueue(cover_letters_uc.DRAFT_TASK, str(letter.id))
    except Exception:
        letter.status = CoverLetterStatus.FAILED
        letter.error = "Writing could not be started. Try again shortly."
        session.commit()
