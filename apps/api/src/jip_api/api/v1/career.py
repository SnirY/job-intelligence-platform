"""Career profile endpoints.

Routes follow ``docs/10-api-contracts.md``. The profile is addressed as
``/career/profile`` with no id in the path: there is exactly one per user, and
the user is resolved from the token, so there is nothing for a caller to
specify — and therefore nothing to tamper with.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.career.profile import (
    ProfileUpdate,
    get_or_create_profile,
    update_profile,
)
from jip_api.core.responses import DataResponse
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/career", tags=["career"])

MAX_LINKS = 10


class ProfileLink(BaseModel):
    """A labelled external link."""

    label: str = Field(min_length=1, max_length=60)
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def reject_non_web_schemes(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Only http(s).

        These render as anchors in the UI, so permitting `javascript:` or
        `data:` would turn a profile field into stored XSS. AnyHttpUrl already
        constrains the scheme; this makes the intent explicit and survives a
        later change of type.
        """
        if value.scheme not in {"http", "https"}:
            raise ValueError("URL must use http or https")
        return value


class ProfilePayload(BaseModel):
    """Career profile as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    headline: str | None
    professional_summary: str | None
    years_of_experience: int | None
    current_location: str | None
    links: list[ProfileLink]
    created_at: dt.datetime
    updated_at: dt.datetime


class ProfileUpdateRequest(BaseModel):
    """Partial update.

    Omitting a field leaves it alone; sending ``null`` clears it. Distinguishing
    those is why the model uses explicit sentinels rather than treating absent
    and null alike.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str | None = Field(default=None, max_length=200)
    professional_summary: str | None = Field(default=None, max_length=5000)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    current_location: str | None = Field(default=None, max_length=200)
    links: list[ProfileLink] | None = Field(default=None, max_length=MAX_LINKS)

    def to_update(self, provided: set[str]) -> ProfileUpdate:
        """Build a use-case update from the fields actually present in the body."""
        update = ProfileUpdate()
        if "headline" in provided:
            update.headline = _blank_to_none(self.headline)
        if "professional_summary" in provided:
            update.professional_summary = _blank_to_none(self.professional_summary)
        if "years_of_experience" in provided:
            update.years_of_experience = self.years_of_experience
        if "current_location" in provided:
            update.current_location = _blank_to_none(self.current_location)
        if "links" in provided:
            update.links = [
                {"label": link.label.strip(), "url": str(link.url)} for link in self.links or []
            ]
        return update


def _blank_to_none(value: str | None) -> str | None:
    """Treat whitespace-only input as cleared.

    A form submits "" for an emptied field. Storing that would make "never
    filled in" and "deliberately blanked" indistinguishable everywhere later.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@router.get(
    "/profile",
    response_model=DataResponse[ProfilePayload],
    summary="Get the career profile",
)
def read_profile(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> DataResponse[ProfilePayload]:
    """Return the profile, creating an empty one on first access."""
    profile = get_or_create_profile(session, user.id)
    session.commit()
    return DataResponse(data=ProfilePayload.model_validate(profile))


@router.patch(
    "/profile",
    response_model=DataResponse[ProfilePayload],
    summary="Update the career profile",
)
def patch_profile(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    body: ProfileUpdateRequest,
) -> DataResponse[ProfilePayload]:
    """Apply a partial update to the authenticated user's profile."""
    profile = update_profile(session, user.id, body.to_update(body.model_fields_set))
    session.commit()
    return DataResponse(data=ProfilePayload.model_validate(profile))
