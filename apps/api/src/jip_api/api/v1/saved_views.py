"""Saved views of the jobs list.

Four routes and no read-one: a view is tiny and the screen always wants all of
them, so listing is the only read anybody makes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.jobs import saved_views as saved_views_uc
from jip_api.core.responses import DataResponse
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/job-views", tags=["jobs"])

SessionDep = Annotated[Session, Depends(get_session)]


class SavedViewPayload(BaseModel):
    """A stored view, and whether this version can still run it."""

    id: uuid.UUID
    name: str
    filters: dict[str, object]
    created_at: dt.datetime
    updated_at: dt.datetime

    is_readable: bool
    """False when a stored filter no longer parses.

    Sent rather than fixed. Dropping the offending key server-side would return
    a *wider* list than the name promises with nothing on screen admitting it,
    which is the same failure as ranking an unscored job last: a narrower claim
    turned into a broader one by omission.
    """

    unreadable: list[str]
    """The keys responsible, so the screen can say which rather than "something"."""


# Stripped before the length is checked, so "   " is refused here as a 422
# rather than trimmed to nothing in the application layer and rejected by the
# table's check constraint as a 500. A name made of spaces is a bad request,
# and it should read as one.
ViewName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class CreateViewRequest(BaseModel):
    name: ViewName
    filters: dict[str, object] = {}


class RenameViewRequest(BaseModel):
    name: ViewName


@router.get("", response_model=DataResponse[list[SavedViewPayload]], summary="List saved views")
def list_views(user: CurrentUser, session: SessionDep) -> DataResponse[list[SavedViewPayload]]:
    return DataResponse(
        data=[_payload(read) for read in saved_views_uc.list_views(session, user.id)]
    )


@router.post(
    "",
    response_model=DataResponse[SavedViewPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Save the current filters as a view",
)
def create_view(
    user: CurrentUser, session: SessionDep, body: CreateViewRequest
) -> DataResponse[SavedViewPayload]:
    view = saved_views_uc.create_view(session, user.id, name=body.name, filters=body.filters)
    session.commit()
    return DataResponse(data=_payload(saved_views_uc.ReadView(view=view, unreadable=[])))


@router.patch(
    "/{view_id}",
    response_model=DataResponse[SavedViewPayload],
    summary="Rename a saved view",
)
def rename_view(
    user: CurrentUser, session: SessionDep, view_id: uuid.UUID, body: RenameViewRequest
) -> DataResponse[SavedViewPayload]:
    """Only the name. Re-saving the filters is a new view.

    Editing filters in place would make the name mean something different from
    the day it was chosen, silently, on a screen whose whole job is to be a
    place the user recognises.
    """
    view = saved_views_uc.rename_view(session, user.id, view_id, body.name)
    session.commit()
    return DataResponse(
        data=_payload(
            saved_views_uc.ReadView(
                view=view, unreadable=saved_views_uc.unreadable_keys(view.filters)
            )
        )
    )


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved view",
)
def delete_view(user: CurrentUser, session: SessionDep, view_id: uuid.UUID) -> Response:
    saved_views_uc.delete_view(session, user.id, view_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _payload(read: saved_views_uc.ReadView) -> SavedViewPayload:
    return SavedViewPayload(
        id=read.view.id,
        name=read.view.name,
        filters=read.view.filters,
        created_at=read.view.created_at,
        updated_at=read.view.updated_at,
        is_readable=read.is_readable,
        unreadable=read.unreadable,
    )
