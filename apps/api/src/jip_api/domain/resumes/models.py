"""Resumes: selected representations of the career profile.

``docs/06-resume-engine.md`` opens with the premise the whole phase rests on:

```text
Career Profile = Source of Truth
Resume = Selected Representation
```

So nothing here stores a career fact. A :class:`ResumeItem` holds the words that
appear on the page and a pointer back to the career row they came from, and the
career row remains the only place the fact itself lives. Editing a bullet
changes how something is said on one resume; it never changes what the profile
knows.

Four tables:

- :class:`Resume` is the logical family — "my backend resume" — and owns
  nothing but a name and a purpose.
- :class:`ResumeVersion` is a point in time, with lineage back to the version it
  was derived from. ``docs/11-engineering-standards.md`` forbids mutating a used
  version, and :attr:`ResumeVersion.content_is_frozen` is where that is decided.
- :class:`ResumeSection` and :class:`ResumeItem` are the structured content.
  ``docs/06`` requires structure rather than a PDF blob, because tailoring
  selects and reorders individual items and cannot do that to a rendered page.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base


class ResumeFamily(enum.StrEnum):
    """The hierarchy from ``docs/06-resume-engine.md``.

    ```text
    Master Resume -> Base Resume -> Job-Specific Resume
    ```

    MASTER is a real row rather than an alias for the career profile. The
    profile is the source of truth, but it is not a *resume* — it has no
    ordering, no selection, and no sections. Making MASTER a row that selects
    everything keeps lineage uniform: every base resume has a parent, and the
    chain from a job-specific version back to its origin never has a hole in it.
    """

    MASTER = "MASTER"
    BASE = "BASE"
    JOB_SPECIFIC = "JOB_SPECIFIC"


class ResumeVersionStatus(enum.StrEnum):
    """From ``docs/03-domain-model.md``.

    The order matters, because USED is the point of no return: once a version
    has been sent to an employer, what it said is a historical fact and editing
    it would make an application record describe a document that never existed.
    """

    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    USED = "USED"
    ARCHIVED = "ARCHIVED"

    @property
    def content_is_frozen(self) -> bool:
        """Whether this version's sections and items may still be edited.

        ``docs/10-api-contracts.md`` says used versions *must* be immutable, and
        ``docs/11-engineering-standards.md`` lists them under "do not mutate
        past". Read as content immutability rather than row immutability: the
        status machine itself is a row write, so a literal reading would make
        USED unreachable and ARCHIVED unreachable after it.

        ARCHIVED is frozen too. Archiving is how a version is retired, and a
        retired version that could still be edited would be a worse record than
        no record.
        """
        return self in {ResumeVersionStatus.USED, ResumeVersionStatus.ARCHIVED}


class ResumeSectionKind(enum.StrEnum):
    """The sections ``docs/06-resume-engine.md`` names.

    A closed set, because rendering and content selection both branch on it —
    a summary is ranked differently from a skill list, and a template lays them
    out differently. Free text would make both of those guesswork.
    """

    HEADER = "HEADER"
    SUMMARY = "SUMMARY"
    SKILLS = "SKILLS"
    EXPERIENCE = "EXPERIENCE"
    PROJECTS = "PROJECTS"
    EDUCATION = "EDUCATION"
    CERTIFICATIONS = "CERTIFICATIONS"
    OTHER = "OTHER"


class ResumeItemSource(enum.StrEnum):
    """Which career table an item was selected from.

    The same five the matcher may cite, plus MANUAL for a line the user wrote
    that corresponds to no single row — a summary sentence, a header field.

    MANUAL is not a loophole. It means "no single source row", not "unverified":
    an item's words are still the user's own, and nothing automatic may put a
    claim here that the profile does not support.
    """

    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    ACHIEVEMENT = "ACHIEVEMENT"
    PROJECT = "PROJECT"
    EDUCATION = "EDUCATION"
    MANUAL = "MANUAL"


class Resume(TimestampMixin, UserOwnedMixin, Base):
    """A logical resume family.

    Holds no content itself. The content lives in versions, because
    ``docs/06-resume-engine.md`` requires every job-specific resume to preserve
    its parent, and a family that also held the current text would give the
    same resume two sources of truth.
    """

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = new_uuid_column()

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    """What the user calls it: "Backend", "AI / Computer Vision"."""

    family: Mapped[ResumeFamily] = mapped_column(StrEnumType(ResumeFamily, 20), nullable=False)

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The job a JOB_SPECIFIC resume was tailored for.

    SET NULL rather than CASCADE: deleting a job must not delete the resume
    written for it. The user may well have sent that resume, and
    ``docs/11-engineering-standards.md`` puts used versions under "do not
    mutate past".
    """

    parent_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The family this one was derived from — base from master, job-specific
    from base. Null for MASTER, and for anything whose parent was deleted."""

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        # A job-specific resume without a job is not job-specific, and a master
        # or base resume pointing at one job contradicts its own family.
        CheckConstraint(
            "(family = 'JOB_SPECIFIC') = (job_id IS NOT NULL)",
            name="job_id_matches_family",
        ),
        Index("ix_resumes_user_family", "user_id", "family"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Resume {self.family} {self.title!r}>"


class ResumeVersion(TimestampMixin, UserOwnedMixin, Base):
    """One point in a resume's history.

    Versions append. Editing an APPROVED version's content is allowed and stays
    on the same row; sending it is what makes it permanent. Tailoring for a new
    job creates a new version with ``parent_version_id`` set, so the lineage
    ``docs/06-resume-engine.md`` asks for is a chain of rows rather than a
    reconstruction from timestamps.
    """

    __tablename__ = "resume_versions"

    id: Mapped[uuid.UUID] = new_uuid_column()

    resume_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)

    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The version this was derived from, across families.

    Not the same as "the previous version of this resume", which is
    ``version - 1``. A job-specific v1 derived from a base v3 records that
    here, which is the question "where did this document come from" — the one
    lineage is for.
    """

    status: Mapped[ResumeVersionStatus] = mapped_column(
        StrEnumType(ResumeVersionStatus, 20),
        nullable=False,
        server_default=ResumeVersionStatus.DRAFT.value,
    )

    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """A human note — "before the rewrite", "sent to Verdant"."""

    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When this version was sent. Set when it reaches USED, and the reason the
    content freezes: an application record must describe a document that
    actually existed in that form."""

    __table_args__ = (
        UniqueConstraint("resume_id", "version", name="uq_resume_versions_resume_version"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_resume_versions_resume_version", "resume_id", "version"),
    )

    @property
    def is_editable(self) -> bool:
        """Whether this version's content may still change."""
        return not self.status.content_is_frozen

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeVersion resume={self.resume_id} v{self.version} {self.status}>"


class ResumeSection(TimestampMixin, UserOwnedMixin, Base):
    """One section of one version.

    Belongs to a version rather than to a resume, because reordering sections
    is itself a tailoring decision — ``docs/06-resume-engine.md`` lists "what to
    reorder" among the things a strategy must answer — and a version that
    shared its sections with the next one could not record that it had made a
    different choice.
    """

    __tablename__ = "resume_sections"

    id: Mapped[uuid.UUID] = new_uuid_column()

    version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[ResumeSectionKind] = mapped_column(
        StrEnumType(ResumeSectionKind, 20), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """What the section is called on the page. Null uses the template's own
    wording, so a user who has not renamed anything is not storing "Experience"
    once per version."""

    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (Index("ix_resume_sections_version_order", "version_id", "display_order"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeSection {self.kind} order={self.display_order}>"


class ResumeItem(TimestampMixin, UserOwnedMixin, Base):
    """One line, bullet, or entry.

    ``docs/03-domain-model.md``: "Should reference source entities where
    possible." That reference is what makes truth validation tractable — a
    claim can be checked against the row it came from rather than against the
    whole profile — and it is the same polymorphic shape as
    ``JobMatchEvidence.entity_id``, for the same reason: it points at one of
    five career tables depending on ``source_type``.
    """

    __tablename__ = "resume_items"

    id: Mapped[uuid.UUID] = new_uuid_column()

    section_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_type: Mapped[ResumeItemSource] = mapped_column(
        StrEnumType(ResumeItemSource, 20),
        nullable=False,
        server_default=ResumeItemSource.MANUAL.value,
    )
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    """The career row behind this item. Null for MANUAL.

    A loose reference rather than a foreign key, because it points at five
    different tables. The trade-off is deliberate and matches
    ``JobMatchEvidence``: a real foreign key would need five nullable columns
    and five constraints to say the same thing.
    """

    text: Mapped[str] = mapped_column(Text, nullable=False)
    """What appears on the page.

    Separate from the source row's own text on purpose. A bullet may be
    shortened or reworded for one resume without touching the achievement it
    came from — that is the whole point of a resume being a *representation* —
    and the source reference is what lets validation check the two against each
    other.
    """

    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    """The line above the bullets: "Senior Engineer, Verdant — 2019-present".
    Null for an item that is itself a bullet."""

    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),
        # MANUAL is the only source that may have no row behind it. Anything
        # claiming a career source must say which one, or the reference cannot
        # be followed and truth validation has nothing to check against.
        CheckConstraint(
            "(source_type = 'MANUAL') OR (source_entity_id IS NOT NULL)",
            name="sourced_items_have_an_entity",
        ),
        Index("ix_resume_items_section_order", "section_id", "display_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeItem {self.source_type} {self.text[:40]!r}>"
