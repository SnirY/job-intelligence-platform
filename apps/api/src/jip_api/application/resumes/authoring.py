"""Building and versioning a resume by hand.

Slice 1 of Phase 7: no AI anywhere in this module. A resume can be created,
structured, edited, versioned, and retired entirely by a person, and that is
useful on its own — the same way the hand-built career profile was in Phase 2.

The rule this module exists to enforce is immutability of the past.
``docs/11-engineering-standards.md`` lists used resume versions under "do not
mutate past", and every write below goes through :func:`editable_version`, so
the guard cannot be forgotten at a call site.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from jip_api.application.errors import ApplicationError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.domain.resumes.models import (
    Resume,
    ResumeFamily,
    ResumeItem,
    ResumeItemSource,
    ResumeSection,
    ResumeSectionKind,
    ResumeVersion,
    ResumeVersionStatus,
)

logger = logging.getLogger(__name__)

_UNSET = object()


class ResumeNotEditableError(ApplicationError):
    """The version's content is frozen because it has been used or archived."""


class ResumeFamilyError(ApplicationError):
    """The requested family does not make sense for the arguments given."""


# Which statuses may follow which. A resume moves forward through review and is
# archived from anywhere, but nothing returns from USED: sending a document is
# the event that makes what it said a historical fact.
_ALLOWED_TRANSITIONS: dict[ResumeVersionStatus, set[ResumeVersionStatus]] = {
    ResumeVersionStatus.DRAFT: {
        ResumeVersionStatus.REVIEW,
        ResumeVersionStatus.APPROVED,
        ResumeVersionStatus.ARCHIVED,
    },
    ResumeVersionStatus.REVIEW: {
        ResumeVersionStatus.DRAFT,
        ResumeVersionStatus.APPROVED,
        ResumeVersionStatus.ARCHIVED,
    },
    ResumeVersionStatus.APPROVED: {
        ResumeVersionStatus.REVIEW,
        ResumeVersionStatus.USED,
        ResumeVersionStatus.ARCHIVED,
    },
    ResumeVersionStatus.USED: {ResumeVersionStatus.ARCHIVED},
    ResumeVersionStatus.ARCHIVED: set(),
}


@dataclass(slots=True)
class ResumeInput:
    """What the caller supplies to create a resume family."""

    title: str
    family: ResumeFamily
    job_id: uuid.UUID | None = None
    parent_resume_id: uuid.UUID | None = None
    description: str | None = None


@dataclass(slots=True)
class SectionInput:
    """One section, with the items it should contain."""

    kind: ResumeSectionKind
    title: str | None = None
    display_order: int = 0
    items: list[ItemInput] = field(default_factory=list)


@dataclass(slots=True)
class ItemInput:
    """One line on the page."""

    text: str
    source_type: ResumeItemSource = ResumeItemSource.MANUAL
    source_entity_id: uuid.UUID | None = None
    heading: str | None = None
    display_order: int = 0


@dataclass(slots=True)
class ResumeUpdate:
    """Partial update. Unset fields are left alone; ``None`` clears them."""

    title: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (("title", self.title), ("description", self.description))
            if value is not _UNSET
        }


# --- resumes ------------------------------------------------------------------


def create_resume(session: Session, user_id: uuid.UUID, data: ResumeInput) -> Resume:
    """Create a resume family.

    Refuses the two combinations the schema also refuses, but with a message
    rather than an integrity error: a job-specific resume needs a job, and a
    master or base resume must not name one.
    """
    if data.family is ResumeFamily.JOB_SPECIFIC and data.job_id is None:
        raise ResumeFamilyError("A job-specific resume needs the job it is tailored for.")
    if data.family is not ResumeFamily.JOB_SPECIFIC and data.job_id is not None:
        raise ResumeFamilyError(
            "Only a job-specific resume can be tied to a job. Use a base resume instead."
        )

    resume = Resume(
        user_id=user_id,
        title=data.title.strip(),
        family=data.family,
        job_id=data.job_id,
        parent_resume_id=data.parent_resume_id,
        description=data.description,
    )
    session.add(resume)
    session.flush()
    logger.info(
        "Created resume",
        # Never the title: docs/11-engineering-standards.md forbids logging
        # resume content, and a title is often a person's name.
        extra={"resume_id": str(resume.id), "family": str(resume.family)},
    )
    return resume


def list_resumes(
    session: Session, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[Resume]:
    """The user's resumes, newest first."""
    statement = owned(Resume, user_id)
    if not include_archived:
        statement = statement.where(Resume.archived_at.is_(None))
    return list(session.execute(statement.order_by(Resume.created_at.desc())).scalars())


def get_resume(session: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    """One of the user's resumes, or raise."""
    resume = session.execute(
        owned(Resume, user_id).where(Resume.id == resume_id)
    ).scalar_one_or_none()
    if resume is None:
        raise ResourceNotFoundError("Resume not found.")
    return resume


def update_resume(
    session: Session, user_id: uuid.UUID, resume_id: uuid.UUID, update: ResumeUpdate
) -> Resume:
    """Rename a resume or change its description.

    Always allowed, even when every version is frozen: the family's name is not
    part of any document that was sent.
    """
    resume = get_resume(session, user_id, resume_id)
    for name, value in update.changes().items():
        setattr(resume, name, value.strip() if isinstance(value, str) else value)
    session.flush()
    return resume


def archive_resume(session: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = get_resume(session, user_id, resume_id)
    resume.archived_at = dt.datetime.now(tz=dt.UTC)
    session.flush()
    return resume


def unarchive_resume(session: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = get_resume(session, user_id, resume_id)
    resume.archived_at = None
    session.flush()
    return resume


def delete_resume(session: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> None:
    """Permanently remove a resume and every version of it.

    Offered because a user may create one by mistake, and archiving a mistake
    keeps it in the way. Deleting a resume whose versions were sent destroys
    the record of what was sent, so the UI offers archiving first — the same
    shape as jobs.
    """
    session.delete(get_resume(session, user_id, resume_id))
    session.flush()


# --- versions -----------------------------------------------------------------


def create_version(
    session: Session,
    user_id: uuid.UUID,
    resume_id: uuid.UUID,
    *,
    parent_version_id: uuid.UUID | None = None,
    label: str | None = None,
    copy_from: uuid.UUID | None = None,
) -> ResumeVersion:
    """Add a version to a resume.

    ``copy_from`` duplicates another version's content, which is how tailoring
    starts: a job-specific version begins as a copy of the base it derives
    from, and ``parent_version_id`` records where it came from. The copy is a
    real copy — new sections and items — so editing the tailored version cannot
    reach back into the base.
    """
    resume = get_resume(session, user_id, resume_id)

    next_version = (
        session.execute(
            select(func.coalesce(func.max(ResumeVersion.version), 0)).where(
                ResumeVersion.resume_id == resume.id
            )
        ).scalar_one()
        + 1
    )

    version = ResumeVersion(
        user_id=user_id,
        resume_id=resume.id,
        version=next_version,
        parent_version_id=parent_version_id,
        status=ResumeVersionStatus.DRAFT,
        label=label,
    )
    session.add(version)
    session.flush()

    if copy_from is not None:
        _copy_content(session, user_id, source_version_id=copy_from, target=version)

    logger.info(
        "Created resume version",
        extra={"resume_id": str(resume.id), "version": next_version},
    )
    return version


def list_versions(
    session: Session, user_id: uuid.UUID, resume_id: uuid.UUID
) -> list[ResumeVersion]:
    """Every version of a resume, newest first."""
    get_resume(session, user_id, resume_id)
    statement = (
        owned(ResumeVersion, user_id)
        .where(ResumeVersion.resume_id == resume_id)
        .order_by(ResumeVersion.version.desc())
    )
    return list(session.execute(statement).scalars())


def get_version(session: Session, user_id: uuid.UUID, version_id: uuid.UUID) -> ResumeVersion:
    """One version, or raise."""
    version = session.execute(
        owned(ResumeVersion, user_id).where(ResumeVersion.id == version_id)
    ).scalar_one_or_none()
    if version is None:
        raise ResourceNotFoundError("Resume version not found.")
    return version


def editable_version(session: Session, user_id: uuid.UUID, version_id: uuid.UUID) -> ResumeVersion:
    """A version whose content may still change, or raise.

    Every content write goes through here rather than checking the status at
    the call site, so "do not mutate past" is one rule in one place instead of
    a convention each new endpoint has to remember.
    """
    version = get_version(session, user_id, version_id)
    if not version.is_editable:
        raise ResumeNotEditableError(
            "This version has been sent or archived, so its content cannot change. "
            "Create a new version instead."
        )
    return version


def set_version_status(
    session: Session, user_id: uuid.UUID, version_id: uuid.UUID, status: ResumeVersionStatus
) -> ResumeVersion:
    """Move a version through its lifecycle.

    Refuses a transition that is not allowed rather than silently doing
    nothing, so a UI offering the wrong button gets an error instead of a
    no-op. Nothing returns from USED except archiving.
    """
    version = get_version(session, user_id, version_id)

    if status is version.status:
        return version

    if status not in _ALLOWED_TRANSITIONS[version.status]:
        raise ResumeNotEditableError(f"A {version.status} version cannot become {status}.")

    version.status = status
    if status is ResumeVersionStatus.USED and version.used_at is None:
        version.used_at = dt.datetime.now(tz=dt.UTC)

    session.flush()
    logger.info(
        "Resume version status changed",
        extra={"version_id": str(version.id), "status": str(status)},
    )
    return version


# --- content ------------------------------------------------------------------


def replace_content(
    session: Session, user_id: uuid.UUID, version_id: uuid.UUID, sections: list[SectionInput]
) -> ResumeVersion:
    """Replace a version's sections and items wholesale.

    Whole-document rather than per-item because the editor sends the document
    it has: reordering sections, moving a bullet between them, and deleting one
    are all the same operation from the user's side, and expressing them as a
    diff would mean the client computing one and the server trusting it.

    The cost is that two editors on the same version overwrite each other. That
    is acceptable for a single-user document, and versions exist precisely so a
    replaced state is recoverable.
    """
    version = editable_version(session, user_id, version_id)

    _clear_content(session, version.id)

    for order, section_input in enumerate(sections):
        section = ResumeSection(
            user_id=user_id,
            version_id=version.id,
            kind=section_input.kind,
            title=section_input.title,
            display_order=section_input.display_order or order,
        )
        session.add(section)
        session.flush()

        for item_order, item_input in enumerate(section_input.items):
            session.add(
                ResumeItem(
                    user_id=user_id,
                    section_id=section.id,
                    source_type=item_input.source_type,
                    source_entity_id=item_input.source_entity_id,
                    text=item_input.text.strip(),
                    heading=item_input.heading,
                    display_order=item_input.display_order or item_order,
                )
            )

    session.flush()
    logger.info(
        "Replaced resume version content",
        extra={"version_id": str(version.id), "sections": len(sections)},
    )
    return version


def load_content(
    session: Session, version_id: uuid.UUID
) -> list[tuple[ResumeSection, list[ResumeItem]]]:
    """A version's sections with their items, in display order.

    Not scoped by user: the caller resolved the version through an
    ownership-checked query, and the version owns its content.
    """
    sections = list(
        session.execute(
            select(ResumeSection)
            .where(ResumeSection.version_id == version_id)
            .order_by(ResumeSection.display_order, ResumeSection.id)
        ).scalars()
    )
    if not sections:
        return []

    items_by_section: dict[uuid.UUID, list[ResumeItem]] = {}
    for item in session.execute(
        select(ResumeItem)
        .where(ResumeItem.section_id.in_([section.id for section in sections]))
        .order_by(ResumeItem.display_order, ResumeItem.id)
    ).scalars():
        items_by_section.setdefault(item.section_id, []).append(item)

    return [(section, items_by_section.get(section.id, [])) for section in sections]


def _clear_content(session: Session, version_id: uuid.UUID) -> None:
    """Remove a version's sections, and its items with them.

    Items go first and explicitly. The cascade would handle them, but only on
    the database side — SQLAlchemy would otherwise keep deleted items in the
    identity map for the rest of the session, and the very next read in the
    same request would see rows that no longer exist.
    """
    section_ids = list(
        session.execute(
            select(ResumeSection.id).where(ResumeSection.version_id == version_id)
        ).scalars()
    )
    if section_ids:
        session.execute(delete(ResumeItem).where(ResumeItem.section_id.in_(section_ids)))
        session.execute(delete(ResumeSection).where(ResumeSection.id.in_(section_ids)))
    session.flush()


def _copy_content(
    session: Session, user_id: uuid.UUID, *, source_version_id: uuid.UUID, target: ResumeVersion
) -> None:
    """Duplicate one version's content into another.

    Reads through the ownership-checked accessor so a copy cannot pull content
    from a version the caller does not own.
    """
    source = get_version(session, user_id, source_version_id)

    for section, items in load_content(session, source.id):
        copied = ResumeSection(
            user_id=user_id,
            version_id=target.id,
            kind=section.kind,
            title=section.title,
            display_order=section.display_order,
        )
        session.add(copied)
        session.flush()

        for item in items:
            session.add(
                ResumeItem(
                    user_id=user_id,
                    section_id=copied.id,
                    source_type=item.source_type,
                    source_entity_id=item.source_entity_id,
                    text=item.text,
                    heading=item.heading,
                    display_order=item.display_order,
                )
            )

    session.flush()
