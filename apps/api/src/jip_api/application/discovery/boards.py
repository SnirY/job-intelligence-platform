"""Which boards a user watches.

Small, and the only thing worth saying about it is the validation. A board token
is interpolated into a URL path by the provider modules, so it is checked here —
at the point a user could introduce one — as well as in `BoardRef`, which checks
it again at the point of use. Two checks for one rule is deliberate: this one
gives the user a 422 they can act on, and that one is the guarantee.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jip_api.core.errors import ConflictError, NotFoundError, UnprocessableEntityError
from jip_api.domain.discovery.models import WatchedBoard
from jip_sources import PROVIDERS, BoardRef, InvalidBoard


def known_providers() -> list[str]:
    return sorted(PROVIDERS)


def for_user(user_id: uuid.UUID) -> Select[tuple[WatchedBoard]]:
    return (
        select(WatchedBoard)
        .where(WatchedBoard.user_id == user_id)
        .order_by(WatchedBoard.created_at.asc())
    )


def get_board(session: Session, user_id: uuid.UUID, board_id: uuid.UUID) -> WatchedBoard:
    board = session.scalars(
        select(WatchedBoard).where(WatchedBoard.id == board_id, WatchedBoard.user_id == user_id)
    ).one_or_none()
    if board is None:
        raise NotFoundError("That board is not on your list.")
    return board


def add_board(
    session: Session,
    user_id: uuid.UUID,
    *,
    provider: str,
    token: str,
    label: str | None = None,
) -> WatchedBoard:
    """Watch one company's board.

    The provider must be one that exists. Accepting an unknown name would store
    a row that every future scan reports as a failure, which is a worse answer
    than refusing it now.
    """
    if provider not in PROVIDERS:
        raise UnprocessableEntityError(
            f"There is no job source called {provider!r}.",
            details={"known": known_providers()},
        )

    try:
        BoardRef(provider, token, label=label)
    except InvalidBoard as error:
        raise UnprocessableEntityError(str(error)) from error

    board = WatchedBoard(user_id=user_id, provider=provider, token=token, label=label)
    session.add(board)

    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise ConflictError("You are already watching that board.") from error

    return board


def set_paused(
    session: Session,
    user_id: uuid.UUID,
    board_id: uuid.UUID,
    *,
    paused: bool,
    now: dt.datetime | None = None,
) -> WatchedBoard:
    """Take a board out of the scan, or put it back.

    Pausing rather than removing is what keeps the postings already found
    through it. Removing is a separate, explicit act.
    """
    board = get_board(session, user_id, board_id)
    board.paused_at = (now or dt.datetime.now(tz=dt.UTC)) if paused else None
    session.flush()
    return board


def remove_board(session: Session, user_id: uuid.UUID, board_id: uuid.UUID) -> None:
    """Stop watching a board.

    The postings discovered through it stay. They were offered, some may have
    been promoted or dismissed, and deleting that history because the source was
    removed would rewrite what happened.
    """
    board = get_board(session, user_id, board_id)
    session.delete(board)
    session.flush()
