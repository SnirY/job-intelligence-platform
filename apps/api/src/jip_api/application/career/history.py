"""Experience, project, and education use cases."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import asc, desc, nullsfirst
from sqlalchemy.orm import Session

from jip_api.application.career.records import (
    apply_changes,
    create_owned,
    delete_owned,
    get_owned,
    list_owned,
)
from jip_api.domain.career.history import Education, Experience, Project
from jip_api.domain.career.models import VerificationStatus

_UNSET = object()


def _changes(pairs: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    return {name: value for name, value in pairs if value is not _UNSET}


# --- experience ---------------------------------------------------------------


@dataclass(slots=True)
class ExperienceInput:
    company: str
    title: str
    employment_type: Any = None
    location: str | None = None
    start_date: Any = None
    end_date: Any = None
    is_current: bool = False
    description: str | None = None


@dataclass(slots=True)
class ExperienceUpdate:
    company: Any = field(default=_UNSET)
    title: Any = field(default=_UNSET)
    employment_type: Any = field(default=_UNSET)
    location: Any = field(default=_UNSET)
    start_date: Any = field(default=_UNSET)
    end_date: Any = field(default=_UNSET)
    is_current: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return _changes(
            (
                ("company", self.company),
                ("title", self.title),
                ("employment_type", self.employment_type),
                ("location", self.location),
                ("start_date", self.start_date),
                ("end_date", self.end_date),
                ("is_current", self.is_current),
                ("description", self.description),
            )
        )


def list_experiences(session: Session, user_id: uuid.UUID) -> list[Experience]:
    """Most recent first.

    Current roles sort to the top: ``end_date`` is null for them, and
    ``nullsfirst`` on a descending sort puts them where a reader expects.
    """
    return list_owned(
        session,
        Experience,
        user_id,
        nullsfirst(desc(Experience.end_date)),
        desc(Experience.start_date),
    )


def create_experience(session: Session, user_id: uuid.UUID, data: ExperienceInput) -> Experience:
    return create_owned(
        session,
        Experience(
            user_id=user_id,
            company=data.company,
            title=data.title,
            employment_type=data.employment_type,
            location=data.location,
            start_date=data.start_date,
            end_date=data.end_date,
            is_current=data.is_current,
            description=data.description,
            verification_status=VerificationStatus.USER_CONFIRMED,
        ),
        conflict_message="That experience conflicts with an existing entry.",
    )


def update_experience(
    session: Session, user_id: uuid.UUID, record_id: uuid.UUID, update: ExperienceUpdate
) -> Experience:
    record = get_owned(
        session, Experience, user_id, record_id, missing_message="Experience not found."
    )
    apply_changes(session, record, update.changes())
    return record


def delete_experience(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
    delete_owned(
        session,
        get_owned(session, Experience, user_id, record_id, missing_message="Experience not found."),
    )


# --- projects -----------------------------------------------------------------


@dataclass(slots=True)
class ProjectInput:
    name: str
    project_type: Any = None
    status: Any = None
    summary: str | None = None
    description: str | None = None
    start_date: Any = None
    end_date: Any = None
    repository_url: str | None = None
    demo_url: str | None = None
    documentation_url: str | None = None


@dataclass(slots=True)
class ProjectUpdate:
    name: Any = field(default=_UNSET)
    project_type: Any = field(default=_UNSET)
    status: Any = field(default=_UNSET)
    summary: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)
    start_date: Any = field(default=_UNSET)
    end_date: Any = field(default=_UNSET)
    repository_url: Any = field(default=_UNSET)
    demo_url: Any = field(default=_UNSET)
    documentation_url: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return _changes(
            (
                ("name", self.name),
                ("project_type", self.project_type),
                ("status", self.status),
                ("summary", self.summary),
                ("description", self.description),
                ("start_date", self.start_date),
                ("end_date", self.end_date),
                ("repository_url", self.repository_url),
                ("demo_url", self.demo_url),
                ("documentation_url", self.documentation_url),
            )
        )


def list_projects(session: Session, user_id: uuid.UUID) -> list[Project]:
    return list_owned(
        session, Project, user_id, nullsfirst(desc(Project.end_date)), asc(Project.name)
    )


def get_project(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> Project:
    return get_owned(session, Project, user_id, record_id, missing_message="Project not found.")


def create_project(session: Session, user_id: uuid.UUID, data: ProjectInput) -> Project:
    return create_owned(
        session,
        Project(
            user_id=user_id,
            name=data.name,
            project_type=data.project_type,
            status=data.status,
            summary=data.summary,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            repository_url=data.repository_url,
            demo_url=data.demo_url,
            documentation_url=data.documentation_url,
            verification_status=VerificationStatus.USER_CONFIRMED,
        ),
        conflict_message=f"A project named {data.name!r} already exists.",
    )


def update_project(
    session: Session, user_id: uuid.UUID, record_id: uuid.UUID, update: ProjectUpdate
) -> Project:
    record = get_project(session, user_id, record_id)
    apply_changes(session, record, update.changes())
    return record


def delete_project(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
    delete_owned(session, get_project(session, user_id, record_id))


# --- education ----------------------------------------------------------------


@dataclass(slots=True)
class EducationInput:
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    location: str | None = None
    start_date: Any = None
    end_date: Any = None
    is_current: bool = False
    grade: str | None = None
    description: str | None = None


@dataclass(slots=True)
class EducationUpdate:
    institution: Any = field(default=_UNSET)
    degree: Any = field(default=_UNSET)
    field_of_study: Any = field(default=_UNSET)
    location: Any = field(default=_UNSET)
    start_date: Any = field(default=_UNSET)
    end_date: Any = field(default=_UNSET)
    is_current: Any = field(default=_UNSET)
    grade: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return _changes(
            (
                ("institution", self.institution),
                ("degree", self.degree),
                ("field_of_study", self.field_of_study),
                ("location", self.location),
                ("start_date", self.start_date),
                ("end_date", self.end_date),
                ("is_current", self.is_current),
                ("grade", self.grade),
                ("description", self.description),
            )
        )


def list_education(session: Session, user_id: uuid.UUID) -> list[Education]:
    return list_owned(
        session,
        Education,
        user_id,
        nullsfirst(desc(Education.end_date)),
        desc(Education.start_date),
    )


def create_education(session: Session, user_id: uuid.UUID, data: EducationInput) -> Education:
    return create_owned(
        session,
        Education(
            user_id=user_id,
            institution=data.institution,
            degree=data.degree,
            field_of_study=data.field_of_study,
            location=data.location,
            start_date=data.start_date,
            end_date=data.end_date,
            is_current=data.is_current,
            grade=data.grade,
            description=data.description,
            verification_status=VerificationStatus.USER_CONFIRMED,
        ),
        conflict_message="That education entry conflicts with an existing one.",
    )


def update_education(
    session: Session, user_id: uuid.UUID, record_id: uuid.UUID, update: EducationUpdate
) -> Education:
    record = get_owned(
        session, Education, user_id, record_id, missing_message="Education entry not found."
    )
    apply_changes(session, record, update.changes())
    return record


def delete_education(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
    delete_owned(
        session,
        get_owned(
            session, Education, user_id, record_id, missing_message="Education entry not found."
        ),
    )
