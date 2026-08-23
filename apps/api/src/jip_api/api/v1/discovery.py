"""`/api/v1/discovery` — boards to watch, and the postings they returned.

The shape of this router is the feature's whole argument. There is a route that
queues a scan, a route that lists what a scan found, and two routes that record
a **person's** decision about one row. There is no route that turns a scan
result into a job, because nothing but a person may do that.

Phase 12, Slice 1. See `docs/development/tasks/phase-12-job-discovery.md`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep
from jip_api.application.discovery import boards as boards_uc
from jip_api.application.discovery import review as review_uc
from jip_api.application.discovery import scanning as scanning_uc
from jip_api.application.jobs import creation as creation_uc
from jip_api.core.responses import CollectionResponse, DataResponse, PaginationMeta
from jip_api.domain.discovery.models import DiscoveredPosting
from jip_api.infrastructure.db.session import get_session
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher

router = APIRouter(prefix="/discovery", tags=["discovery"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


# --- payloads -----------------------------------------------------------------


class BoardPayload(BaseModel):
    """One watched board, and how its last scan went."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    token: str
    label: str | None
    paused_at: dt.datetime | None
    last_scanned_at: dt.datetime | None
    last_error: str | None
    """Why the last scan of *this* board failed. Per board rather than per run,
    so a company that has stopped being readable can be named."""

    created_at: dt.datetime


class BoardCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    label: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=200)] = None


class DiscoveredPostingPayload(BaseModel):
    """A posting a board returned, and nothing concluded from it.

    No score, no requirements, no seniority, no role family. Those come from the
    analysis pipeline, which a posting reaches only after a person promotes it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    board: str
    title: str
    url: str
    company: str | None
    location: str | None
    posted_at: dt.datetime | None
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    has_description: bool
    """Whether there is posting text. The text itself is not shipped in a list
    of twenty-five rows that would otherwise carry half a megabyte."""


class ScanQueued(BaseModel):
    """A scan was asked for. It has not run yet."""

    boards: int
    """How many boards it will read. Zero is a real answer and the screen says
    so rather than implying work is happening."""


class PromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_duplicate: bool = False
    """The explicit create-anyway path, exactly as `POST /jobs` has it. A board
    listing something the user pasted last week is a normal case here."""


def _posting_payload(row: DiscoveredPosting) -> DiscoveredPostingPayload:
    """One place that decides what a discovered posting looks like on the wire.

    `has_description` rather than the description itself: twenty-five rows of
    posting text is half a megabyte the list does not render.
    """
    return DiscoveredPostingPayload(
        id=row.id,
        provider=row.provider,
        board=row.board,
        title=row.title,
        url=row.url,
        company=row.company,
        location=row.location,
        posted_at=row.posted_at,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        has_description=bool(row.description_text or row.description_html),
    )


# --- boards -------------------------------------------------------------------


@router.get("/boards", response_model=DataResponse[list[BoardPayload]], summary="Boards you watch")
def read_boards(user: CurrentUser, session: SessionDep) -> DataResponse[list[BoardPayload]]:
    rows = list(session.scalars(boards_uc.for_user(user.id)))
    return DataResponse(data=[BoardPayload.model_validate(row) for row in rows])


@router.get("/providers", response_model=DataResponse[list[str]], summary="Job sources that exist")
def read_providers(user: CurrentUser) -> DataResponse[list[str]]:
    """Authenticated but not user-scoped: the list of providers is the same for
    everyone, and it is what the add-a-board form offers."""
    return DataResponse(data=boards_uc.known_providers())


@router.post(
    "/boards",
    response_model=DataResponse[BoardPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Watch a board",
)
def post_board(
    user: CurrentUser, session: SessionDep, body: BoardCreateRequest
) -> DataResponse[BoardPayload]:
    board = boards_uc.add_board(
        session, user.id, provider=body.provider, token=body.token, label=body.label
    )
    session.commit()
    return DataResponse(data=BoardPayload.model_validate(board))


@router.post(
    "/boards/{board_id}/pause",
    response_model=DataResponse[BoardPayload],
    summary="Leave a board out of the next scan",
)
def post_pause(
    user: CurrentUser, session: SessionDep, board_id: uuid.UUID
) -> DataResponse[BoardPayload]:
    board = boards_uc.set_paused(session, user.id, board_id, paused=True)
    session.commit()
    return DataResponse(data=BoardPayload.model_validate(board))


@router.post(
    "/boards/{board_id}/resume",
    response_model=DataResponse[BoardPayload],
    summary="Put a board back into the scan",
)
def post_resume(
    user: CurrentUser, session: SessionDep, board_id: uuid.UUID
) -> DataResponse[BoardPayload]:
    board = boards_uc.set_paused(session, user.id, board_id, paused=False)
    session.commit()
    return DataResponse(data=BoardPayload.model_validate(board))


@router.delete(
    "/boards/{board_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop watching a board",
)
def remove_board(user: CurrentUser, session: SessionDep, board_id: uuid.UUID) -> Response:
    """The postings already discovered through it stay.

    They were offered, some may have been promoted or dismissed, and deleting
    that history because the source was removed would rewrite what happened.
    """
    boards_uc.remove_board(session, user.id, board_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- scanning -----------------------------------------------------------------


@router.post("/scan", response_model=DataResponse[ScanQueued], summary="Scan your boards now")
def post_scan(
    user: CurrentUser, session: SessionDep, dispatcher: DispatcherDep
) -> DataResponse[ScanQueued]:
    """Queue a scan of every board that is not paused.

    On request rather than on a schedule. There is no scheduler in this system
    — the worker runs with `with_scheduler=False` — and turning one on is a
    decision about operating unattended that should be made on its own merits.
    """
    active = list(session.scalars(boards_uc.for_user(user.id)))
    runnable = [board for board in active if not board.is_paused]

    if runnable:
        _dispatch_scan(dispatcher, user.id)

    return DataResponse(data=ScanQueued(boards=len(runnable)))


# --- the review list ----------------------------------------------------------


@router.get(
    "/postings",
    response_model=CollectionResponse[DiscoveredPostingPayload],
    summary="Postings awaiting your decision",
)
def read_postings(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> CollectionResponse[DiscoveredPostingPayload]:
    """Undismissed and unpromoted, newest first.

    A dismissed row and a promoted row have both been decided about, and neither
    belongs in a list whose whole purpose is what is still waiting.
    """
    statement = review_uc.pending(user.id)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = list(session.scalars(statement.offset((page - 1) * page_size).limit(page_size)))

    return CollectionResponse(
        data=[_posting_payload(row) for row in rows],
        meta=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total or 0,
            total_pages=max(1, -(-(total or 0) // page_size)),
        ),
    )


@router.post(
    "/postings/{posting_id}/dismiss",
    response_model=DataResponse[DiscoveredPostingPayload],
    summary="Say no to a posting",
)
def post_dismiss(
    user: CurrentUser, session: SessionDep, posting_id: uuid.UUID
) -> DataResponse[DiscoveredPostingPayload]:
    """Recorded rather than deleted, so the next scan does not offer it back."""
    row = review_uc.dismiss(session, user.id, posting_id)
    session.commit()
    return DataResponse(data=_posting_payload(row))


@router.post(
    "/postings/{posting_id}/promote",
    response_model=DataResponse[dict[str, str]],
    status_code=status.HTTP_201_CREATED,
    summary="Add a posting to your jobs",
)
def post_promote(
    user: CurrentUser, session: SessionDep, posting_id: uuid.UUID, body: PromoteRequest
) -> DataResponse[dict[str, str]]:
    """The only route that creates a job from a discovered posting, and it is
    the one a person has to call.

    Answers with the job's id rather than the job, because the caller navigates
    to it and the job's own endpoint is the authority on what it says.
    """
    try:
        job = review_uc.promote(session, user.id, posting_id, allow_duplicate=body.allow_duplicate)
    except creation_uc.DuplicateJobError as error:
        session.rollback()
        raise _duplicate_error(error) from error

    session.commit()
    return DataResponse(data={"job_id": str(job.id)})


# --- helpers ------------------------------------------------------------------


def _dispatch_scan(dispatcher: TaskDispatcher, user_id: uuid.UUID) -> None:
    """Queue the scan, and say so plainly if the queue would not take it.

    Nothing is written first, so there is no half-started state to correct — the
    scan either ran or it did not, and the caller is the only one who can be
    told.
    """
    try:
        dispatcher.enqueue(scanning_uc.SCAN_TASK, str(user_id))
    except Exception as exc:
        from jip_api.core.errors import ServiceUnavailableError

        raise ServiceUnavailableError("The scan could not be started. Try again shortly.") from exc


def _duplicate_error(exc: creation_uc.DuplicateJobError) -> Exception:
    from jip_api.core.errors import ConflictError

    return ConflictError(
        str(exc),
        details={
            "existing_job_id": str(exc.existing.id),
            "existing_title": exc.existing.title,
            "reason": str(exc.reason),
        },
    )
