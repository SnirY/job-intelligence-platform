"""Resume authoring endpoints.

The routes from ``docs/10-api-contracts.md`` that slice 1 needs: list and
create resumes, list and create versions, read a version, and edit one.

Mounted at ``/resumes`` and ``/resume-versions``, matching the contract's split
— a version is addressed by its own id rather than nested under its resume,
because tailoring in later slices hands a version id around without carrying
the family with it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.resumes import authoring
from jip_api.core.responses import DataResponse
from jip_api.domain.resumes.models import (
    ResumeFamily,
    ResumeItemSource,
    ResumeSectionKind,
    ResumeVersion,
    ResumeVersionStatus,
)
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/resumes", tags=["resumes"])
versions_router = APIRouter(prefix="/resume-versions", tags=["resumes"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class ResumePayload(BaseModel):
    """A resume family."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    family: ResumeFamily
    job_id: uuid.UUID | None
    parent_resume_id: uuid.UUID | None
    description: str | None
    archived_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ResumeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    family: ResumeFamily = ResumeFamily.BASE
    job_id: uuid.UUID | None = None
    parent_resume_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)


class ResumeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ItemPayload(BaseModel):
    """One line on the page."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    heading: str | None
    source_type: ResumeItemSource
    source_entity_id: uuid.UUID | None
    display_order: int


class SectionPayload(BaseModel):
    """One section, with its items."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ResumeSectionKind
    title: str | None
    display_order: int
    items: list[ItemPayload] = []


class VersionPayload(BaseModel):
    """A version, without its content."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID
    version: int
    parent_version_id: uuid.UUID | None
    status: ResumeVersionStatus
    label: str | None
    used_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class VersionDetailPayload(VersionPayload):
    """A version with its content, and whether it may still be edited.

    ``is_editable`` is served rather than derived by the client, so the rule
    lives in one place: the endpoint that refuses an edit and the button that
    offers one read the same answer.
    """

    sections: list[SectionPayload] = []
    is_editable: bool = True


class VersionCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    parent_version_id: uuid.UUID | None = None
    copy_from: uuid.UUID | None = None
    """Duplicate another version's content into the new one. How tailoring
    starts: a job-specific version begins as a copy of its base."""


class ItemRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    heading: str | None = Field(default=None, max_length=300)
    source_type: ResumeItemSource = ResumeItemSource.MANUAL
    source_entity_id: uuid.UUID | None = None
    display_order: int = 0


class SectionRequest(BaseModel):
    kind: ResumeSectionKind
    title: str | None = Field(default=None, max_length=120)
    display_order: int = 0
    items: list[ItemRequest] = Field(default_factory=list, max_length=200)


class ContentRequest(BaseModel):
    """A version's whole content.

    Whole-document rather than a diff: reordering, moving a bullet, and
    deleting one are the same operation from the user's side, and a diff would
    mean the client computing one and the server trusting it.
    """

    sections: list[SectionRequest] = Field(default_factory=list, max_length=20)


class StatusRequest(BaseModel):
    status: ResumeVersionStatus


# --- resume routes ------------------------------------------------------------


@router.get("", response_model=DataResponse[list[ResumePayload]], summary="List resumes")
def read_resumes(
    user: CurrentUser,
    session: SessionDep,
    include_archived: Annotated[bool, Query()] = False,
) -> DataResponse[list[ResumePayload]]:
    resumes = authoring.list_resumes(session, user.id, include_archived=include_archived)
    return DataResponse(data=[ResumePayload.model_validate(row) for row in resumes])


@router.post(
    "",
    response_model=DataResponse[ResumePayload],
    status_code=status.HTTP_201_CREATED,
    summary="Create a resume",
)
def post_resume(
    user: CurrentUser, session: SessionDep, body: ResumeCreateRequest
) -> DataResponse[ResumePayload]:
    resume = authoring.create_resume(
        session,
        user.id,
        authoring.ResumeInput(
            title=body.title,
            family=body.family,
            job_id=body.job_id,
            parent_resume_id=body.parent_resume_id,
            description=body.description,
        ),
    )
    session.commit()
    return DataResponse(data=ResumePayload.model_validate(resume))


@router.get("/{resume_id}", response_model=DataResponse[ResumePayload], summary="Get a resume")
def read_resume(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID
) -> DataResponse[ResumePayload]:
    return DataResponse(
        data=ResumePayload.model_validate(authoring.get_resume(session, user.id, resume_id))
    )


@router.patch("/{resume_id}", response_model=DataResponse[ResumePayload], summary="Update a resume")
def patch_resume(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID, body: ResumeUpdateRequest
) -> DataResponse[ResumePayload]:
    update = authoring.ResumeUpdate()
    provided = body.model_fields_set
    if "title" in provided:
        update.title = body.title
    if "description" in provided:
        update.description = body.description

    resume = authoring.update_resume(session, user.id, resume_id, update)
    session.commit()
    return DataResponse(data=ResumePayload.model_validate(resume))


@router.post(
    "/{resume_id}/archive",
    response_model=DataResponse[ResumePayload],
    summary="Archive a resume",
)
def post_archive(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID
) -> DataResponse[ResumePayload]:
    resume = authoring.archive_resume(session, user.id, resume_id)
    session.commit()
    return DataResponse(data=ResumePayload.model_validate(resume))


@router.post(
    "/{resume_id}/unarchive",
    response_model=DataResponse[ResumePayload],
    summary="Unarchive a resume",
)
def post_unarchive(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID
) -> DataResponse[ResumePayload]:
    resume = authoring.unarchive_resume(session, user.id, resume_id)
    session.commit()
    return DataResponse(data=ResumePayload.model_validate(resume))


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resume permanently",
)
def remove_resume(user: CurrentUser, session: SessionDep, resume_id: uuid.UUID) -> Response:
    """Permanent, and takes every version with it. Archiving is what the UI
    offers by default."""
    authoring.delete_resume(session, user.id, resume_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- version routes -----------------------------------------------------------


@router.get(
    "/{resume_id}/versions",
    response_model=DataResponse[list[VersionPayload]],
    summary="List a resume's versions",
)
def read_versions(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID
) -> DataResponse[list[VersionPayload]]:
    versions = authoring.list_versions(session, user.id, resume_id)
    return DataResponse(data=[VersionPayload.model_validate(row) for row in versions])


@router.post(
    "/{resume_id}/versions",
    response_model=DataResponse[VersionDetailPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Create a version",
)
def post_version(
    user: CurrentUser, session: SessionDep, resume_id: uuid.UUID, body: VersionCreateRequest
) -> DataResponse[VersionDetailPayload]:
    version = authoring.create_version(
        session,
        user.id,
        resume_id,
        parent_version_id=body.parent_version_id,
        label=body.label,
        copy_from=body.copy_from,
    )
    session.commit()
    return DataResponse(data=_detail(session, version))


@versions_router.get(
    "/{version_id}",
    response_model=DataResponse[VersionDetailPayload],
    summary="Get a version with its content",
)
def read_version(
    user: CurrentUser, session: SessionDep, version_id: uuid.UUID
) -> DataResponse[VersionDetailPayload]:
    version = authoring.get_version(session, user.id, version_id)
    return DataResponse(data=_detail(session, version))


@versions_router.put(
    "/{version_id}/content",
    response_model=DataResponse[VersionDetailPayload],
    summary="Replace a version's content",
)
def put_content(
    user: CurrentUser, session: SessionDep, version_id: uuid.UUID, body: ContentRequest
) -> DataResponse[VersionDetailPayload]:
    """Refuses a used or archived version.

    ``docs/11-engineering-standards.md`` puts used versions under "do not
    mutate past" — an application record must describe a document that existed
    in that form.
    """
    version = authoring.replace_content(
        session,
        user.id,
        version_id,
        [
            authoring.SectionInput(
                kind=section.kind,
                title=section.title,
                display_order=section.display_order,
                items=[
                    authoring.ItemInput(
                        text=item.text,
                        source_type=item.source_type,
                        source_entity_id=item.source_entity_id,
                        heading=item.heading,
                        display_order=item.display_order,
                    )
                    for item in section.items
                ],
            )
            for section in body.sections
        ],
    )
    session.commit()
    return DataResponse(data=_detail(session, version))


@versions_router.post(
    "/{version_id}/status",
    response_model=DataResponse[VersionPayload],
    summary="Move a version through its lifecycle",
)
def post_status(
    user: CurrentUser, session: SessionDep, version_id: uuid.UUID, body: StatusRequest
) -> DataResponse[VersionPayload]:
    version = authoring.set_version_status(session, user.id, version_id, body.status)
    session.commit()
    return DataResponse(data=VersionPayload.model_validate(version))


# --- helpers ------------------------------------------------------------------


def _detail(session: Session, version: ResumeVersion) -> VersionDetailPayload:
    """A version plus its content, in one payload."""
    payload = VersionDetailPayload.model_validate(version)
    payload.is_editable = version.is_editable
    payload.sections = [
        SectionPayload(
            id=section.id,
            kind=section.kind,
            title=section.title,
            display_order=section.display_order,
            items=[ItemPayload.model_validate(item) for item in items],
        )
        for section, items in authoring.load_content(session, version.id)
    ]
    return payload
