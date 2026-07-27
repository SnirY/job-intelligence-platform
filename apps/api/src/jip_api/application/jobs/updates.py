"""Editing and archiving a job.

The one rule that matters here: an update never touches the preserved original.
``original_description`` and the ``JobImport`` rows are written at import time
and are not reachable from any function in this module.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from jip_api.application.jobs.creation import content_hash
from jip_api.application.jobs.queries import get_job
from jip_api.domain.jobs.models import Job, JobProcessingStatus, normalize_title

logger = logging.getLogger(__name__)

_UNSET = object()


@dataclass(slots=True)
class JobUpdate:
    """Partial update. Unset fields are left alone; ``None`` clears them.

    The three-state distinction is the point: a PATCH that omits a field must
    not blank it, or editing the title from one screen would wipe the notes
    written on another.
    """

    title: Any = field(default=_UNSET)
    company: Any = field(default=_UNSET)
    location: Any = field(default=_UNSET)
    work_mode: Any = field(default=_UNSET)
    employment_type: Any = field(default=_UNSET)
    seniority: Any = field(default=_UNSET)
    role_family: Any = field(default=_UNSET)
    description: Any = field(default=_UNSET)
    notes: Any = field(default=_UNSET)
    salary_text: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("title", self.title),
                ("company", self.company),
                ("location", self.location),
                ("work_mode", self.work_mode),
                ("employment_type", self.employment_type),
                ("seniority", self.seniority),
                ("role_family", self.role_family),
                ("description", self.description),
                ("notes", self.notes),
                ("salary_text", self.salary_text),
            )
            if value is not _UNSET
        }


def update_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID, update: JobUpdate) -> Job:
    """Apply a partial update.

    Two derived fields are kept in step by hand rather than by a trigger, so
    the derivation lives next to the rule that explains it: the normalized
    title, and the content hash duplicate detection compares against.
    """
    job = get_job(session, user_id, job_id)
    changes = update.changes()

    for name, value in changes.items():
        setattr(job, name, value)

    if "title" in changes and job.title:
        job.normalized_title = normalize_title(job.title)

    if "description" in changes:
        job.content_hash = content_hash(job.description)
        # A job that failed to fetch and has now been filled in by hand is no
        # longer failed — that is the manual fallback completing.
        if job.description and job.status is JobProcessingStatus.FAILED:
            job.status = JobProcessingStatus.RAW
            job.fetch_error = None

    session.flush()
    return job


def supply_description(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID, description: str
) -> Job:
    """Fill in a description by hand after a URL import failed.

    The documented fallback: the job and its URL survived the failure, and this
    is how the user finishes the import without starting over.

    ``original_description`` is set if it is still empty — for a failed fetch
    there was never an original to preserve, and what the user pastes now *is*
    the source. If one already exists it is left alone.
    """
    job = get_job(session, user_id, job_id)
    text = description.strip()

    job.description = text
    if job.original_description is None:
        job.original_description = text
    job.content_hash = content_hash(text)
    job.status = JobProcessingStatus.RAW
    job.fetch_error = None

    session.flush()
    logger.info("Job description supplied manually", extra={"job_id": str(job.id)})
    return job


def archive_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Archive a job.

    Not a delete. ``docs/11-engineering-standards.md`` forbids silently dropping
    user history, and Phase 10's insights read the jobs a user decided against
    as much as the ones they pursued.

    Idempotent: archiving twice keeps the first timestamp, which is the one
    that says when the decision was actually made.
    """
    job = get_job(session, user_id, job_id)
    if job.archived_at is None:
        job.archived_at = dt.datetime.now(tz=dt.UTC)
        session.flush()
    return job


def unarchive_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Bring a job back into the active list."""
    job = get_job(session, user_id, job_id)
    job.archived_at = None
    session.flush()
    return job


def delete_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Remove a job and its import records permanently.

    Offered alongside archiving because a job added by mistake is not history
    worth keeping, and a list that can only grow stops being usable. Archiving
    is the default the UI presents; this is the deliberate one.
    """
    job = get_job(session, user_id, job_id)
    session.delete(job)
    session.flush()
    logger.info("Deleted job", extra={"job_id": str(job_id)})
