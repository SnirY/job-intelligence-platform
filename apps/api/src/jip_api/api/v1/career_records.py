"""Skills, experience, projects, and education endpoints.

Routes follow ``docs/10-api-contracts.md``. Every one resolves the user from the
token and scopes on it; an id in the path selects among the caller's own rows
only, and another user's id answers 404 exactly as a missing one does.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.career import history as history_uc
from jip_api.application.career import skills as skills_uc
from jip_api.core.responses import DataResponse
from jip_api.domain.career.history import EmploymentType, ProjectStatus, ProjectType
from jip_api.domain.career.skills import Proficiency, SkillCategory
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/career", tags=["career"])

SessionDep = Annotated[Session, Depends(get_session)]


def _blank_to_none(value: str | None) -> str | None:
    """A form submits "" for an emptied field; that must not become stored data."""
    if value is None:
        return None
    return value.strip() or None


class _DateRangeMixin(BaseModel):
    """Rejects an end date before the start date.

    The database enforces this too. Checking here as well turns a 500-shaped
    constraint violation into a 422 that names the field.
    """

    @model_validator(mode="after")
    def check_date_order(self) -> Any:
        start = getattr(self, "start_date", None)
        end = getattr(self, "end_date", None)
        if start and end and end < start:
            raise ValueError("end_date must not be earlier than start_date")
        if getattr(self, "is_current", False) and end:
            raise ValueError("a current entry must not have an end date")
        return self


# --- skills -------------------------------------------------------------------


class UserSkillPayload(BaseModel):
    """A claimed skill, joined with its canonical entry."""

    id: uuid.UUID
    skill_id: uuid.UUID
    name: str
    category: SkillCategory
    proficiency: Proficiency | None
    years_of_experience: int | None
    last_used_year: int | None
    verification_status: str
    source: str
    notes: str | None


class UserSkillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    category: SkillCategory = SkillCategory.OTHER
    proficiency: Proficiency | None = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    last_used_year: int | None = Field(default=None, ge=1950, le=2200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class UserSkillUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proficiency: Proficiency | None = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    last_used_year: int | None = Field(default=None, ge=1950, le=2200)
    notes: str | None = Field(default=None, max_length=2000)

    def to_update(self, provided: set[str]) -> skills_uc.UserSkillUpdate:
        update = skills_uc.UserSkillUpdate()
        if "proficiency" in provided:
            update.proficiency = self.proficiency
        if "years_of_experience" in provided:
            update.years_of_experience = self.years_of_experience
        if "last_used_year" in provided:
            update.last_used_year = self.last_used_year
        if "notes" in provided:
            update.notes = _blank_to_none(self.notes)
        return update


@router.get("/skills", response_model=DataResponse[list[UserSkillPayload]], summary="List skills")
def read_skills(user: CurrentUser, session: SessionDep) -> DataResponse[list[UserSkillPayload]]:
    rows = skills_uc.list_user_skills(session, user.id)
    return DataResponse(
        data=[
            UserSkillPayload(
                id=user_skill.id,
                skill_id=skill.id,
                name=skill.canonical_name,
                category=SkillCategory(skill.category),
                proficiency=user_skill.proficiency,
                years_of_experience=user_skill.years_of_experience,
                last_used_year=user_skill.last_used_year,
                verification_status=user_skill.verification_status,
                source=user_skill.source,
                notes=user_skill.notes,
            )
            for user_skill, skill in rows
        ]
    )


@router.post(
    "/skills",
    response_model=DataResponse[UserSkillPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add a skill",
)
def post_skill(
    user: CurrentUser, session: SessionDep, body: UserSkillCreateRequest
) -> DataResponse[UserSkillPayload]:
    """Claim a skill, resolving the name to the shared canonical catalogue."""
    user_skill, skill = skills_uc.add_user_skill(
        session,
        user.id,
        skills_uc.UserSkillInput(
            name=body.name,
            category=body.category,
            proficiency=body.proficiency,
            years_of_experience=body.years_of_experience,
            last_used_year=body.last_used_year,
            notes=_blank_to_none(body.notes),
        ),
    )
    session.commit()
    return DataResponse(
        data=UserSkillPayload(
            id=user_skill.id,
            skill_id=skill.id,
            name=skill.canonical_name,
            category=SkillCategory(skill.category),
            proficiency=user_skill.proficiency,
            years_of_experience=user_skill.years_of_experience,
            last_used_year=user_skill.last_used_year,
            verification_status=user_skill.verification_status,
            source=user_skill.source,
            notes=user_skill.notes,
        )
    )


@router.patch(
    "/skills/{skill_id}", response_model=DataResponse[dict[str, Any]], summary="Update a skill"
)
def patch_skill(
    user: CurrentUser, session: SessionDep, skill_id: uuid.UUID, body: UserSkillUpdateRequest
) -> DataResponse[dict[str, Any]]:
    updated = skills_uc.update_user_skill(
        session, user.id, skill_id, body.to_update(body.model_fields_set)
    )
    session.commit()
    return DataResponse(
        data={
            "id": str(updated.id),
            "proficiency": updated.proficiency,
            "years_of_experience": updated.years_of_experience,
            "last_used_year": updated.last_used_year,
            "notes": updated.notes,
        }
    )


@router.delete(
    "/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a skill"
)
def remove_skill(user: CurrentUser, session: SessionDep, skill_id: uuid.UUID) -> Response:
    skills_uc.remove_user_skill(session, user.id, skill_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- experiences --------------------------------------------------------------


class ExperiencePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company: str
    title: str
    employment_type: EmploymentType | None
    location: str | None
    start_date: dt.date | None
    end_date: dt.date | None
    is_current: bool
    description: str | None
    verification_status: str


class ExperienceCreateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    employment_type: EmploymentType | None = None
    location: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    is_current: bool = False
    description: str | None = Field(default=None, max_length=5000)


class ExperienceUpdateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    employment_type: EmploymentType | None = None
    location: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    is_current: bool | None = None
    description: str | None = Field(default=None, max_length=5000)

    def to_update(self, provided: set[str]) -> history_uc.ExperienceUpdate:
        update = history_uc.ExperienceUpdate()
        for name in ("company", "title", "employment_type", "start_date", "end_date"):
            if name in provided:
                setattr(update, name, getattr(self, name))
        if "location" in provided:
            update.location = _blank_to_none(self.location)
        if "description" in provided:
            update.description = _blank_to_none(self.description)
        if "is_current" in provided and self.is_current is not None:
            update.is_current = self.is_current
        return update


@router.get(
    "/experiences", response_model=DataResponse[list[ExperiencePayload]], summary="List experiences"
)
def read_experiences(
    user: CurrentUser, session: SessionDep
) -> DataResponse[list[ExperiencePayload]]:
    records = history_uc.list_experiences(session, user.id)
    return DataResponse(data=[ExperiencePayload.model_validate(r) for r in records])


@router.post(
    "/experiences",
    response_model=DataResponse[ExperiencePayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add an experience",
)
def post_experience(
    user: CurrentUser, session: SessionDep, body: ExperienceCreateRequest
) -> DataResponse[ExperiencePayload]:
    record = history_uc.create_experience(
        session,
        user.id,
        history_uc.ExperienceInput(
            company=body.company.strip(),
            title=body.title.strip(),
            employment_type=body.employment_type,
            location=_blank_to_none(body.location),
            start_date=body.start_date,
            end_date=body.end_date,
            is_current=body.is_current,
            description=_blank_to_none(body.description),
        ),
    )
    session.commit()
    return DataResponse(data=ExperiencePayload.model_validate(record))


@router.patch(
    "/experiences/{record_id}",
    response_model=DataResponse[ExperiencePayload],
    summary="Update an experience",
)
def patch_experience(
    user: CurrentUser, session: SessionDep, record_id: uuid.UUID, body: ExperienceUpdateRequest
) -> DataResponse[ExperiencePayload]:
    record = history_uc.update_experience(
        session, user.id, record_id, body.to_update(body.model_fields_set)
    )
    session.commit()
    return DataResponse(data=ExperiencePayload.model_validate(record))


@router.delete(
    "/experiences/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an experience",
)
def remove_experience(user: CurrentUser, session: SessionDep, record_id: uuid.UUID) -> Response:
    history_uc.delete_experience(session, user.id, record_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- projects -----------------------------------------------------------------


class ProjectPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    project_type: ProjectType | None
    status: ProjectStatus | None
    summary: str | None
    description: str | None
    start_date: dt.date | None
    end_date: dt.date | None
    repository_url: str | None
    demo_url: str | None
    documentation_url: str | None
    verification_status: str


class ProjectCreateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    # AnyHttpUrl rather than str: these render as anchors, so allowing
    # javascript: or data: would make a profile field into stored XSS.
    repository_url: AnyHttpUrl | None = None
    demo_url: AnyHttpUrl | None = None
    documentation_url: AnyHttpUrl | None = None


class ProjectUpdateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    repository_url: AnyHttpUrl | None = None
    demo_url: AnyHttpUrl | None = None
    documentation_url: AnyHttpUrl | None = None

    def to_update(self, provided: set[str]) -> history_uc.ProjectUpdate:
        update = history_uc.ProjectUpdate()
        for name in ("name", "project_type", "status", "start_date", "end_date"):
            if name in provided:
                setattr(update, name, getattr(self, name))
        for name in ("summary", "description"):
            if name in provided:
                setattr(update, name, _blank_to_none(getattr(self, name)))
        for name in ("repository_url", "demo_url", "documentation_url"):
            if name in provided:
                value = getattr(self, name)
                setattr(update, name, str(value) if value else None)
        return update


@router.get("/projects", response_model=DataResponse[list[ProjectPayload]], summary="List projects")
def read_projects(user: CurrentUser, session: SessionDep) -> DataResponse[list[ProjectPayload]]:
    records = history_uc.list_projects(session, user.id)
    return DataResponse(data=[ProjectPayload.model_validate(r) for r in records])


@router.get(
    "/projects/{record_id}", response_model=DataResponse[ProjectPayload], summary="Get a project"
)
def read_project(
    user: CurrentUser, session: SessionDep, record_id: uuid.UUID
) -> DataResponse[ProjectPayload]:
    return DataResponse(
        data=ProjectPayload.model_validate(history_uc.get_project(session, user.id, record_id))
    )


@router.post(
    "/projects",
    response_model=DataResponse[ProjectPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add a project",
)
def post_project(
    user: CurrentUser, session: SessionDep, body: ProjectCreateRequest
) -> DataResponse[ProjectPayload]:
    record = history_uc.create_project(
        session,
        user.id,
        history_uc.ProjectInput(
            name=body.name.strip(),
            project_type=body.project_type,
            status=body.status,
            summary=_blank_to_none(body.summary),
            description=_blank_to_none(body.description),
            start_date=body.start_date,
            end_date=body.end_date,
            repository_url=str(body.repository_url) if body.repository_url else None,
            demo_url=str(body.demo_url) if body.demo_url else None,
            documentation_url=str(body.documentation_url) if body.documentation_url else None,
        ),
    )
    session.commit()
    return DataResponse(data=ProjectPayload.model_validate(record))


@router.patch(
    "/projects/{record_id}", response_model=DataResponse[ProjectPayload], summary="Update a project"
)
def patch_project(
    user: CurrentUser, session: SessionDep, record_id: uuid.UUID, body: ProjectUpdateRequest
) -> DataResponse[ProjectPayload]:
    record = history_uc.update_project(
        session, user.id, record_id, body.to_update(body.model_fields_set)
    )
    session.commit()
    return DataResponse(data=ProjectPayload.model_validate(record))


@router.delete(
    "/projects/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a project"
)
def remove_project(user: CurrentUser, session: SessionDep, record_id: uuid.UUID) -> Response:
    history_uc.delete_project(session, user.id, record_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- education ----------------------------------------------------------------


class EducationPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    institution: str
    degree: str | None
    field_of_study: str | None
    location: str | None
    start_date: dt.date | None
    end_date: dt.date | None
    is_current: bool
    grade: str | None
    description: str | None
    verification_status: str


class EducationCreateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    institution: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    is_current: bool = False
    grade: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)


class EducationUpdateRequest(_DateRangeMixin):
    model_config = ConfigDict(extra="forbid")

    institution: str | None = Field(default=None, min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    is_current: bool | None = None
    grade: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5000)

    def to_update(self, provided: set[str]) -> history_uc.EducationUpdate:
        update = history_uc.EducationUpdate()
        for name in ("institution", "start_date", "end_date"):
            if name in provided:
                setattr(update, name, getattr(self, name))
        for name in ("degree", "field_of_study", "location", "grade", "description"):
            if name in provided:
                setattr(update, name, _blank_to_none(getattr(self, name)))
        if "is_current" in provided and self.is_current is not None:
            update.is_current = self.is_current
        return update


@router.get(
    "/education", response_model=DataResponse[list[EducationPayload]], summary="List education"
)
def read_education(user: CurrentUser, session: SessionDep) -> DataResponse[list[EducationPayload]]:
    records = history_uc.list_education(session, user.id)
    return DataResponse(data=[EducationPayload.model_validate(r) for r in records])


@router.post(
    "/education",
    response_model=DataResponse[EducationPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add an education entry",
)
def post_education(
    user: CurrentUser, session: SessionDep, body: EducationCreateRequest
) -> DataResponse[EducationPayload]:
    record = history_uc.create_education(
        session,
        user.id,
        history_uc.EducationInput(
            institution=body.institution.strip(),
            degree=_blank_to_none(body.degree),
            field_of_study=_blank_to_none(body.field_of_study),
            location=_blank_to_none(body.location),
            start_date=body.start_date,
            end_date=body.end_date,
            is_current=body.is_current,
            grade=_blank_to_none(body.grade),
            description=_blank_to_none(body.description),
        ),
    )
    session.commit()
    return DataResponse(data=EducationPayload.model_validate(record))


@router.patch(
    "/education/{record_id}",
    response_model=DataResponse[EducationPayload],
    summary="Update an education entry",
)
def patch_education(
    user: CurrentUser, session: SessionDep, record_id: uuid.UUID, body: EducationUpdateRequest
) -> DataResponse[EducationPayload]:
    record = history_uc.update_education(
        session, user.id, record_id, body.to_update(body.model_fields_set)
    )
    session.commit()
    return DataResponse(data=EducationPayload.model_validate(record))


@router.delete(
    "/education/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an education entry",
)
def remove_education(user: CurrentUser, session: SessionDep, record_id: uuid.UUID) -> Response:
    history_uc.delete_education(session, user.id, record_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
