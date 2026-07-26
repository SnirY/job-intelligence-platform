"""Experience, projects, and education — the evidence behind a skill claim.

``docs/06-resume-engine.md`` distinguishes an explicit skill from the evidence
that supports it. These are that evidence: matching in Phase 6 traces a
requirement to a specific role or project rather than to a bare list of words.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import TimestampMixin, UserOwnedMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base

# Reused by every table here: an end date before a start date is nonsense the
# database can refuse regardless of which caller wrote it.
_DATE_ORDER = "end_date IS NULL OR start_date IS NULL OR end_date >= start_date"


class EmploymentType(enum.StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    FREELANCE = "FREELANCE"
    INTERNSHIP = "INTERNSHIP"
    VOLUNTEER = "VOLUNTEER"


class ProjectType(enum.StrEnum):
    """From ``docs/03-domain-model.md``."""

    PERSONAL = "PERSONAL"
    ACADEMIC = "ACADEMIC"
    PROFESSIONAL = "PROFESSIONAL"
    OPEN_SOURCE = "OPEN_SOURCE"
    FREELANCE = "FREELANCE"
    RESEARCH = "RESEARCH"


class ProjectStatus(enum.StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MAINTAINED = "MAINTAINED"
    ARCHIVED = "ARCHIVED"


class Experience(TimestampMixin, UserOwnedMixin, Base):
    """A role the user has held."""

    __tablename__ = "experiences"

    id: Mapped[uuid.UUID] = new_uuid_column()

    company: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    employment_type: Mapped[EmploymentType | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    """Explicit rather than inferred from a null end date.

    A null end date is ambiguous — it can mean "still there" or "never filled
    in" — and resume rendering needs to tell those apart.
    """

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint("length(trim(company)) > 0", name="company_not_blank"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        CheckConstraint(_DATE_ORDER, name="date_order"),
        CheckConstraint("NOT (is_current AND end_date IS NOT NULL)", name="current_has_no_end"),
    )


class ExperienceAchievement(TimestampMixin, Base):
    """A single bullet-level fact from a role.

    Stored separately because ``docs/06-resume-engine.md`` treats these as
    reusable statements: resume tailoring selects individual achievements by
    relevance, which is impossible if they are one blob of text.

    Not user-owned directly — ownership comes from the parent experience, and
    the cascade means it cannot outlive it.
    """

    __tablename__ = "experience_achievements"

    id: Mapped[uuid.UUID] = new_uuid_column()
    experience_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),)


class Project(TimestampMixin, UserOwnedMixin, Base):
    """Something the user built."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = new_uuid_column()

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_type: Mapped[ProjectType | None] = mapped_column(String(20), nullable=True)
    status: Mapped[ProjectStatus | None] = mapped_column(String(20), nullable=True)

    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Two fields because they serve different jobs: the summary is the one-line
    version a resume shows, the description is the full account the matcher
    reads for evidence."""

    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    repository_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    demo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """Separate columns rather than a JSONB blob: these are searchable, and a
    repository link is evidence strength in its own right."""

    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(_DATE_ORDER, name="date_order"),
    )


class ProjectSkill(Base):
    """Links a project to a canonical skill.

    This is what makes a skill claim traceable: "React, because of these two
    projects" rather than "React, because it is on a list".
    """

    __tablename__ = "project_skills"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ExperienceSkill(Base):
    """Links a role to a canonical skill, for the same reason as ProjectSkill."""

    __tablename__ = "experience_skills"

    experience_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("experiences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Education(TimestampMixin, UserOwnedMixin, Base):
    """A qualification or course of study."""

    __tablename__ = "education"

    id: Mapped[uuid.UUID] = new_uuid_column()

    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """Free text. Grading scales differ by country, and normalising them here
    would mean inventing a conversion the user never asked for."""

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint("length(trim(institution)) > 0", name="institution_not_blank"),
        CheckConstraint(_DATE_ORDER, name="date_order"),
        CheckConstraint("NOT (is_current AND end_date IS NOT NULL)", name="current_has_no_end"),
    )
