"""Editing and archiving a job.

The one rule that matters here: an update never touches the preserved original.
``original_description`` and the ``JobImport`` rows are written at import time
and are not reachable from any function in this module.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from jip_api.application.jobs.creation import content_hash
from jip_api.application.jobs.queries import get_job
from jip_api.application.ownership import owned
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


@dataclass(frozen=True, slots=True)
class BulkArchiveResult:
    """What happened to each id the caller sent.

    Both lists rather than a count, because the screen has to name what it could
    not do. "27 of 29 archived" with no way to see which two is a sentence that
    makes someone re-select thirty rows to find out.
    """

    archived: list[uuid.UUID]
    missing: list[uuid.UUID]
    """Not found, or owned by someone else. Deliberately one outcome: telling a
    caller which of another user's ids exist is the leak `owned()` prevents."""


def archive_jobs(
    session: Session, user_id: uuid.UUID, job_ids: Sequence[uuid.UUID]
) -> BulkArchiveResult:
    """Archive many jobs, and report on each.

    **Not atomic, on purpose.** Rolling back twenty-seven archives the user asked
    for, because two ids turned out to be unreachable, destroys work to punish a
    mismatch — the inverse of what `GOAL.md` asks of a failure. Archiving is
    reversible and idempotent, so the partial outcome is both safe and the one
    the user wanted.

    One query rather than one per id: the ownership filter is the same for all of
    them, and a loop would re-ask the same question twenty-nine times.

    Duplicate ids collapse. Order of the result follows the ids as given, so a
    screen can line the outcome up against the rows the reader selected.
    """
    wanted = list(dict.fromkeys(job_ids))
    if not wanted:
        return BulkArchiveResult(archived=[], missing=[])

    found = {
        job.id: job for job in session.scalars(owned(Job, user_id).where(Job.id.in_(wanted))).all()
    }

    moment = dt.datetime.now(tz=dt.UTC)
    for job in found.values():
        # Idempotent, as the single-job path is: the first timestamp is the one
        # that says when the decision was actually made.
        if job.archived_at is None:
            job.archived_at = moment

    session.flush()

    result = BulkArchiveResult(
        archived=[job_id for job_id in wanted if job_id in found],
        missing=[job_id for job_id in wanted if job_id not in found],
    )
    logger.info(
        "Jobs archived in bulk",
        extra={"archived": len(result.archived), "missing": len(result.missing)},
    )
    return result


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
