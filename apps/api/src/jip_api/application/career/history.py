"""Experience, project, and education use cases."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import asc, desc, func, nullsfirst, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jip_api.application.career.records import (
    apply_changes,
    create_owned,
    delete_owned,
    get_owned,
    list_owned,
)
from jip_api.domain.career.history import (
    Certification,
    Education,
    Experience,
    ExperienceAchievement,
    Project,
    ProjectSkill,
)
from jip_api.domain.career.models import VerificationStatus
from jip_api.domain.career.skills import Skill

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


def get_experience(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> Experience:
    return get_owned(
        session, Experience, user_id, record_id, missing_message="Experience not found."
    )


# --- achievements -------------------------------------------------------------
#
# Bullet-level facts belong to their role, so they are reached through it rather
# than being user-owned in their own right. Ownership is the parent's, and the
# cascade means an achievement cannot outlive the experience it describes.


def list_achievements(session: Session, experience_id: uuid.UUID) -> list[ExperienceAchievement]:
    """Achievements of one role, in display order."""
    statement = (
        select(ExperienceAchievement)
        .where(ExperienceAchievement.experience_id == experience_id)
        .order_by(ExperienceAchievement.display_order, ExperienceAchievement.created_at)
    )
    return list(session.execute(statement).scalars())


def add_achievement(
    session: Session,
    experience: Experience,
    *,
    text: str,
    verification_status: VerificationStatus = VerificationStatus.USER_CONFIRMED,
    display_order: int | None = None,
) -> ExperienceAchievement:
    """Add one achievement to a role.

    Takes the ``Experience`` object rather than an id: the caller has already
    resolved it through an ownership-checked query, and accepting a bare id here
    would make it possible to attach a bullet to someone else's role.

    An identical text on the same role returns the existing row instead of a
    second copy — confirming the same extraction twice must not double the
    bullets under a job.
    """
    normalized = text.strip()
    existing = session.execute(
        select(ExperienceAchievement).where(
            ExperienceAchievement.experience_id == experience.id,
            func.lower(func.trim(ExperienceAchievement.text)) == normalized.lower(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    if display_order is None:
        display_order = (
            int(
                session.execute(
                    select(func.coalesce(func.max(ExperienceAchievement.display_order), -1)).where(
                        ExperienceAchievement.experience_id == experience.id
                    )
                ).scalar_one()
            )
            + 1
        )

    achievement = ExperienceAchievement(
        experience_id=experience.id,
        text=normalized,
        display_order=display_order,
        verification_status=verification_status,
    )
    session.add(achievement)
    session.flush()
    return achievement


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


# --- project technologies -----------------------------------------------------


def list_project_skills(session: Session, project_id: uuid.UUID) -> list[Skill]:
    """Canonical skills linked to a project, alphabetically."""
    statement = (
        select(Skill)
        .join(ProjectSkill, ProjectSkill.skill_id == Skill.id)
        .where(ProjectSkill.project_id == project_id)
        .order_by(Skill.canonical_name)
    )
    return list(session.execute(statement).scalars())


def link_project_skill(session: Session, project: Project, skill_id: uuid.UUID) -> None:
    """Link a project to a canonical skill.

    Idempotent by construction: the pair is the primary key, so re-linking is a
    no-op rather than an integrity error the caller has to catch. Takes the
    ``Project`` object for the same reason as ``add_achievement``.
    """
    session.execute(
        pg_insert(ProjectSkill)
        .values(project_id=project.id, skill_id=skill_id)
        .on_conflict_do_nothing(index_elements=[ProjectSkill.project_id, ProjectSkill.skill_id])
    )
    session.flush()


# --- certifications -----------------------------------------------------------


@dataclass(slots=True)
class CertificationInput:
    name: str
    issuer: str
    issued_on: Any = None
    expires_on: Any = None
    credential_id: str | None = None
    credential_url: str | None = None
    description: str | None = None


@dataclass(slots=True)
class CertificationUpdate:
    name: Any = field(default=_UNSET)
    issuer: Any = field(default=_UNSET)
    issued_on: Any = field(default=_UNSET)
    expires_on: Any = field(default=_UNSET)
    credential_id: Any = field(default=_UNSET)
    credential_url: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return _changes(
            (
                ("name", self.name),
                ("issuer", self.issuer),
                ("issued_on", self.issued_on),
                ("expires_on", self.expires_on),
                ("credential_id", self.credential_id),
                ("credential_url", self.credential_url),
                ("description", self.description),
            )
        )


def list_certifications(session: Session, user_id: uuid.UUID) -> list[Certification]:
    """Credentials, the ones that never expire first, then latest expiry first.

    `nullsfirst` is deliberate and the opposite of an accident: a null
    `expires_on` means the credential does not expire, so those are the
    strongest and belong at the top. Sorting them last would bury a permanent
    credential under lapsed ones.
    """
    return list_owned(
        session,
        Certification,
        user_id,
        nullsfirst(desc(Certification.expires_on)),
        desc(Certification.issued_on),
    )


def create_certification(
    session: Session, user_id: uuid.UUID, data: CertificationInput
) -> Certification:
    return create_owned(
        session,
        Certification(
            user_id=user_id,
            name=data.name,
            issuer=data.issuer,
            issued_on=data.issued_on,
            expires_on=data.expires_on,
            credential_id=data.credential_id,
            credential_url=data.credential_url,
            description=data.description,
            verification_status=VerificationStatus.USER_CONFIRMED,
        ),
        conflict_message="That certification conflicts with an existing one.",
    )


def update_certification(
    session: Session, user_id: uuid.UUID, record_id: uuid.UUID, update: CertificationUpdate
) -> Certification:
    record = get_owned(
        session, Certification, user_id, record_id, missing_message="Certification not found."
    )
    apply_changes(session, record, update.changes())
    return record


def delete_certification(session: Session, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
    delete_owned(
        session,
        get_owned(
            session, Certification, user_id, record_id, missing_message="Certification not found."
        ),
    )


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


# --- matching existing records ------------------------------------------------
#
# Used when approving extracted data. A resume usually describes roles the user
# has already entered by hand, and creating a second copy of one would corrupt
# the profile that every later match is measured against. Matching is on the
# fields that identify a record to a person, not on an exact payload equality
# that a different date format would defeat.


def find_experience(
    session: Session,
    user_id: uuid.UUID,
    *,
    company: str,
    title: str,
    start_date: Any = None,
) -> Experience | None:
    """An existing role with the same company, title, and start date."""
    statement = (
        select(Experience)
        .where(
            Experience.user_id == user_id,
            func.lower(func.trim(Experience.company)) == company.strip().lower(),
            func.lower(func.trim(Experience.title)) == title.strip().lower(),
        )
        .order_by(Experience.created_at)
    )
    for candidate in session.execute(statement).scalars():
        if candidate.start_date == start_date:
            return candidate
    return None


def find_project(session: Session, user_id: uuid.UUID, *, name: str) -> Project | None:
    """An existing project with the same name.

    Name alone, because ``projects`` already enforces one name per user — a
    second match is impossible, and creating one would fail the constraint.
    """
    return session.execute(
        select(Project).where(
            Project.user_id == user_id,
            func.lower(func.trim(Project.name)) == name.strip().lower(),
        )
    ).scalar_one_or_none()


def find_education(
    session: Session,
    user_id: uuid.UUID,
    *,
    institution: str,
    degree: str | None,
    start_date: Any = None,
) -> Education | None:
    """An existing education entry with the same institution, degree, and start."""
    statement = (
        select(Education)
        .where(
            Education.user_id == user_id,
            func.lower(func.trim(Education.institution)) == institution.strip().lower(),
        )
        .order_by(Education.created_at)
    )
    normalized_degree = (degree or "").strip().lower()
    for candidate in session.execute(statement).scalars():
        if (candidate.degree or "").strip().lower() != normalized_degree:
            continue
        if candidate.start_date == start_date:
            return candidate
    return None
