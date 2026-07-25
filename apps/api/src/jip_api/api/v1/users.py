"""Current-user endpoint.

The only Phase 1 endpoint. It exists so the frontend can confirm the whole chain
works — Clerk session, bearer token, JWKS verification, internal user — and so
the authentication path has something real to test against.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from jip_api.api.dependencies import CurrentUser
from jip_api.core.responses import DataResponse

router = APIRouter(prefix="/users", tags=["users"])


class UserPayload(BaseModel):
    """Public representation of the internal user.

    Deliberately omits ``auth_provider`` and ``external_user_id``. The client
    already knows its own provider identity, and the internal id is the only one
    the API accepts in URLs, so exposing the provider id would only invite it to
    be used as a handle — and would leak which provider is in use.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    display_name: str | None
    created_at: dt.datetime


@router.get(
    "/me",
    response_model=DataResponse[UserPayload],
    summary="Current authenticated user",
)
def read_current_user(user: CurrentUser) -> DataResponse[UserPayload]:
    """Return the authenticated user, creating the record on first sign-in."""
    return DataResponse(data=UserPayload.model_validate(user))
