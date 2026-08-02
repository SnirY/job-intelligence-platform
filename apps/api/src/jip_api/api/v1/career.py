"""Career profile endpoints.

Routes follow ``docs/10-api-contracts.md``. The profile is addressed as
``/career/profile`` with no id in the path: there is exactly one per user, and
the user is resolved from the token, so there is nothing for a caller to
specify — and therefore nothing to tamper with.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.career.preferences import (
    PreferencesUpdate,
    get_or_create_preferences,
    update_preferences,
)
from jip_api.application.career.profile import (
    ProfileUpdate,
    get_or_create_profile,
    update_profile,
)
from jip_api.application.career.target_roles import (
    TargetRoleInput,
    TargetRoleUpdate,
    create_target_role,
    delete_target_role,
    list_target_roles,
    update_target_role,
)
from jip_api.core.responses import DataResponse
from jip_api.domain.career.history import EmploymentType
from jip_api.domain.career.models import Seniority
from jip_api.domain.jobs.analysis import RoleFamily
from jip_api.domain.jobs.models import WorkMode
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


# --- target roles -------------------------------------------------------------


class TargetRolePayload(BaseModel):
    """A target role as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    role_family: str | None
    desired_seniority: Seniority | None
    priority: int
    is_active: bool
    notes: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TargetRoleCreateRequest(BaseModel):
    """Body of ``POST /career/target-roles``."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    role_family: str | None = Field(default=None, max_length=100)
    desired_seniority: Seniority | None = None
    priority: int = Field(default=1, ge=0, le=1000)
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    def to_input(self) -> TargetRoleInput:
        return TargetRoleInput(
            title=self.title,
            role_family=_blank_to_none(self.role_family),
            desired_seniority=self.desired_seniority,
            priority=self.priority,
            is_active=self.is_active,
            notes=_blank_to_none(self.notes),
        )


class TargetRoleUpdateRequest(BaseModel):
    """Body of ``PATCH /career/target-roles/{id}``."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    role_family: str | None = Field(default=None, max_length=100)
    desired_seniority: Seniority | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    def to_update(self, provided: set[str]) -> TargetRoleUpdate:
        update = TargetRoleUpdate()
        if "title" in provided and self.title is not None:
            update.title = self.title
        if "role_family" in provided:
            update.role_family = _blank_to_none(self.role_family)
        if "desired_seniority" in provided:
            update.desired_seniority = self.desired_seniority
        if "priority" in provided and self.priority is not None:
            update.priority = self.priority
        if "is_active" in provided and self.is_active is not None:
            update.is_active = self.is_active
        if "notes" in provided:
            update.notes = _blank_to_none(self.notes)
        return update


class TargetRoleCollection(BaseModel):
    """Collection envelope payload."""

    items: list[TargetRolePayload]


@router.get(
    "/target-roles",
    response_model=DataResponse[list[TargetRolePayload]],
    summary="List target roles",
)
def read_target_roles(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> DataResponse[list[TargetRolePayload]]:
    """Return the user's target roles, most important first."""
    roles = list_target_roles(session, user.id)
    return DataResponse(data=[TargetRolePayload.model_validate(role) for role in roles])


@router.post(
    "/target-roles",
    response_model=DataResponse[TargetRolePayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add a target role",
)
def post_target_role(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    body: TargetRoleCreateRequest,
) -> DataResponse[TargetRolePayload]:
    """Create a target role for the authenticated user."""
    role = create_target_role(session, user.id, body.to_input())
    session.commit()
    return DataResponse(data=TargetRolePayload.model_validate(role))


@router.patch(
    "/target-roles/{role_id}",
    response_model=DataResponse[TargetRolePayload],
    summary="Update a target role",
)
def patch_target_role(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    role_id: uuid.UUID,
    body: TargetRoleUpdateRequest,
) -> DataResponse[TargetRolePayload]:
    """Update one of the user's target roles.

    ``role_id`` selects among the caller's own rows only. Another user's id
    resolves to 404, which is also what a nonexistent id returns.
    """
    role = update_target_role(session, user.id, role_id, body.to_update(body.model_fields_set))
    session.commit()
    return DataResponse(data=TargetRolePayload.model_validate(role))


@router.delete(
    "/target-roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a target role",
)
def remove_target_role(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    role_id: uuid.UUID,
) -> Response:
    """Delete one of the user's target roles."""
    delete_target_role(session, user.id, role_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- preferences --------------------------------------------------------------

MAX_LOCATIONS = 20


class PreferencesPayload(BaseModel):
    """Career preferences as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_modes: list[WorkMode]
    employment_types: list[EmploymentType]
    locations: list[str]
    open_to_relocation: bool | None
    salary_min: int | None
    salary_currency: str | None
    excluded_role_families: list[RoleFamily]
    created_at: dt.datetime
    updated_at: dt.datetime


class PreferencesUpdateRequest(BaseModel):
    """Partial update.

    Enum-typed lists rather than free strings, so a work mode the matcher has
    never heard of is a 422 at the edge instead of a preference that silently
    matches nothing. Locations stay free text: the posting states its location
    as prose, and a controlled vocabulary on one side of that comparison would
    promise precision that is not there.
    """

    model_config = ConfigDict(extra="forbid")

    work_modes: list[WorkMode] | None = Field(default=None, max_length=len(WorkMode))
    employment_types: list[EmploymentType] | None = Field(
        default=None, max_length=len(EmploymentType)
    )
    locations: list[str] | None = Field(default=None, max_length=MAX_LOCATIONS)
    open_to_relocation: bool | None = None
    salary_min: int | None = Field(default=None, ge=0, le=100_000_000)
    salary_currency: str | None = Field(default=None, max_length=3)
    excluded_role_families: list[RoleFamily] | None = Field(
        default=None, max_length=len(RoleFamily)
    )

    def to_update(self, provided: set[str]) -> PreferencesUpdate:
        """Build a use-case update from the fields actually present in the body."""
        update = PreferencesUpdate()
        if "work_modes" in provided:
            update.work_modes = _unique(str(mode) for mode in self.work_modes or [])
        if "employment_types" in provided:
            update.employment_types = _unique(str(kind) for kind in self.employment_types or [])
        if "locations" in provided:
            update.locations = _unique(
                place.strip() for place in self.locations or [] if place.strip()
            )
        if "open_to_relocation" in provided:
            update.open_to_relocation = self.open_to_relocation
        if "salary_min" in provided:
            update.salary_min = self.salary_min
        if "salary_currency" in provided:
            currency = _blank_to_none(self.salary_currency)
            update.salary_currency = currency.upper() if currency else None
        if "excluded_role_families" in provided:
            update.excluded_role_families = _unique(
                str(family) for family in self.excluded_role_families or []
            )
        return update


def _unique(values: Iterable[str]) -> list[str]:
    """De-duplicate while keeping the order the user chose.

    A repeated value would make "remote, remote" read as a stronger preference
    than "remote", and every consumer here treats these as sets.
    """
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


@router.get(
    "/preferences",
    response_model=DataResponse[PreferencesPayload],
    summary="Get career preferences",
)
def read_preferences(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> DataResponse[PreferencesPayload]:
    """Return preferences, creating an empty row on first access.

    An all-empty record rather than 404: a user who has never opened Settings
    has *no constraints*, which is a different answer from *no preferences
    exist* and the one every consumer needs.
    """
    preferences = get_or_create_preferences(session, user.id)
    session.commit()
    return DataResponse(data=PreferencesPayload.model_validate(preferences))


@router.patch(
    "/preferences",
    response_model=DataResponse[PreferencesPayload],
    summary="Update career preferences",
)
def patch_preferences(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    body: PreferencesUpdateRequest,
) -> DataResponse[PreferencesPayload]:
    """Apply a partial update. Omitting a field leaves it; sending an empty list
    clears it, which means "no constraint" rather than "accept nothing"."""
    preferences = update_preferences(session, user.id, body.to_update(body.model_fields_set))
    session.commit()
    return DataResponse(data=PreferencesPayload.model_validate(preferences))
