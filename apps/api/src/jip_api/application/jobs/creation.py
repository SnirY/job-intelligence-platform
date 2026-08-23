"""Adding a job.

Three ways in, from ``docs/10-api-contracts.md``: a pasted description, a URL,
or typed by hand. They differ in where the text comes from and in nothing else,
so they converge on one record as early as possible.

Two rules shape this module:

- **The original is written once.** ``original_description`` and the
  ``JobImport`` row are set at creation and never updated. Editing a job
  changes ``description``.
- **A possible duplicate is reported, not dropped.** The user is the only one
  who knows whether two similar postings are the same job.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.errors import ApplicationError
from jip_api.application.ownership import owned
from jip_api.domain.jobs.models import (
    Job,
    JobImport,
    JobImportMethod,
    JobProcessingStatus,
    normalize_title,
)
from jip_api.domain.jobs.urls import normalize_url

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


class DuplicateJobError(ApplicationError):
    """This job looks like one already saved.

    Carries the existing job so the API can answer with the id and the reason,
    as ``docs/10-api-contracts.md`` requires — a bare 409 would leave the user
    unable to find the job they supposedly already have.
    """

    def __init__(self, message: str, *, existing: Job, reason: str) -> None:
        super().__init__(message)
        self.existing = existing
        self.reason = reason


@dataclass(slots=True)
class JobInput:
    """What the caller supplies to add a job.

    One shape for all three methods. A URL import arrives with no description
    and fills one in later; a manual job may never have one.
    """

    title: str
    import_method: JobImportMethod
    company: str | None = None
    location: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    role_family: str | None = None
    description: str | None = None
    source_url: str | None = None
    notes: str | None = None
    salary_text: str | None = None
    posted_at: dt.datetime | None = None
    """When the employer published, where the source says so.

    Only a board states this. A pasted or hand-entered job leaves it null, and
    null keeps meaning nothing said rather than published today.
    """


def content_hash(description: str | None) -> str | None:
    """Hash of the description, ignoring formatting.

    Whitespace is collapsed and case folded first, so the same posting copied
    from two sites — one with hard-wrapped lines, one without — hashes the
    same. Short text is not hashed: two jobs whose descriptions are both "TBC"
    are not duplicates.
    """
    if not description:
        return None
    normalized = _WHITESPACE.sub(" ", description).strip().casefold()
    if len(normalized) < 200:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def find_duplicate(
    session: Session,
    user_id: uuid.UUID,
    *,
    normalized_url: str | None,
    description_hash: str | None,
    exclude_id: uuid.UUID | None = None,
) -> tuple[Job, str] | None:
    """Return an existing job that looks like the same posting, and why.

    Two signals, checked in order of confidence:

    1. **The same normalized URL.** As close to certain as this gets.
    2. **The same description hash.** Catches the same posting reached through
       two different links — an aggregator and the company's own site.

    Deliberately no fuzzy title-and-company matching. Two genuinely different
    openings at one company routinely share a title, and a false duplicate is
    worse than a missed one: it puts a 409 in front of a job the user is
    trying to add.
    """
    if normalized_url:
        statement = owned(Job, user_id).where(Job.normalized_source_url == normalized_url)
        if exclude_id is not None:
            statement = statement.where(Job.id != exclude_id)
        existing = session.execute(statement.limit(1)).scalar_one_or_none()
        if existing is not None:
            return existing, "SAME_URL"

    if description_hash:
        statement = owned(Job, user_id).where(Job.content_hash == description_hash)
        if exclude_id is not None:
            statement = statement.where(Job.id != exclude_id)
        existing = session.execute(statement.limit(1)).scalar_one_or_none()
        if existing is not None:
            return existing, "SAME_CONTENT"

    return None


def create_job(
    session: Session,
    user_id: uuid.UUID,
    data: JobInput,
    *,
    allow_duplicate: bool = False,
) -> Job:
    """Create a job and its import record.

    ``allow_duplicate`` is the explicit create-anyway path: the API raises on
    the first attempt and the user re-submits with it set. It is never the
    default, because silently creating a second copy is what makes a job list
    stop being trustworthy.
    """
    normalized_url = normalize_url(data.source_url) if data.source_url else None
    description = data.description.strip() if data.description else None
    digest = content_hash(description)

    if not allow_duplicate:
        duplicate = find_duplicate(
            session, user_id, normalized_url=normalized_url, description_hash=digest
        )
        if duplicate is not None:
            existing, reason = duplicate
            raise DuplicateJobError(
                "You have already saved this job.", existing=existing, reason=reason
            )

    status = (
        JobProcessingStatus.FETCHING
        if data.import_method is JobImportMethod.URL and not description
        else JobProcessingStatus.RAW
    )

    job = Job(
        user_id=user_id,
        title=data.title.strip(),
        normalized_title=normalize_title(data.title),
        company=_clean(data.company),
        location=_clean(data.location),
        work_mode=data.work_mode,
        employment_type=data.employment_type,
        seniority=data.seniority,
        role_family=_clean(data.role_family),
        description=description,
        # Written once. Every later edit touches `description` only, which is
        # what makes "the original is preserved" a property of the schema
        # rather than a rule someone has to remember.
        original_description=description,
        source_url=data.source_url.strip() if data.source_url else None,
        normalized_source_url=normalized_url,
        import_method=data.import_method,
        status=status,
        content_hash=digest,
        notes=_clean(data.notes),
        salary_text=_clean(data.salary_text),
        posted_at=data.posted_at,
    )
    session.add(job)
    session.flush()

    record_import(
        session,
        job,
        import_method=data.import_method,
        raw_content=description,
        source_url=job.source_url,
    )

    logger.info(
        "Created job",
        extra={"job_id": str(job.id), "method": str(data.import_method), "status": str(status)},
    )
    return job


def record_import(
    session: Session,
    job: Job,
    *,
    import_method: JobImportMethod,
    raw_content: str | None = None,
    extracted_text: str | None = None,
    source_url: str | None = None,
    final_url: str | None = None,
    redirect_chain: list[str] | None = None,
    content_type: str | None = None,
    http_status: int | None = None,
    content_bytes: int | None = None,
    error: str | None = None,
    error_code: str | None = None,
) -> JobImport:
    """Append an import record.

    Append-only by design: a retry adds a row rather than editing one, so the
    history of what was tried and what came back stays readable.
    """
    record = JobImport(
        user_id=job.user_id,
        job_id=job.id,
        import_method=import_method,
        source_url=source_url,
        raw_content=raw_content,
        extracted_text=extracted_text,
        content_type=content_type,
        http_status=http_status,
        content_bytes=content_bytes,
        final_url=final_url,
        redirect_chain=list(redirect_chain or []),
        error=error,
        error_code=error_code,
        imported_at=dt.datetime.now(tz=dt.UTC),
    )
    session.add(record)
    session.flush()
    return record


def latest_import(session: Session, job_id: uuid.UUID) -> JobImport | None:
    """The most recent import record for a job."""
    statement = (
        select(JobImport)
        .where(JobImport.job_id == job_id)
        .order_by(JobImport.created_at.desc())
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def list_imports(session: Session, job_id: uuid.UUID) -> list[JobImport]:
    """Every import attempt for a job, oldest first."""
    statement = select(JobImport).where(JobImport.job_id == job_id).order_by(JobImport.created_at)
    return list(session.execute(statement).scalars())


def apply_fetched_content(
    session: Session,
    job: Job,
    *,
    text: str,
    suggested_title: str | None = None,
) -> Job:
    """Fill in a job whose URL import succeeded.

    ``suggested_title`` comes from the page's ``<title>`` and is used only when
    the user did not supply one — external metadata is a suggestion, never a
    fact (``docs/11-engineering-standards.md``).

    ``original_description`` is set here rather than at creation because for a
    URL import there was nothing to preserve until now. It is still written
    exactly once.
    """
    job.description = text
    if job.original_description is None:
        job.original_description = text
    job.content_hash = content_hash(text)
    job.status = JobProcessingStatus.RAW
    job.fetch_error = None

    if suggested_title and _is_placeholder_title(job.title):
        job.title = suggested_title.strip()[:300]
        job.normalized_title = normalize_title(job.title)

    session.flush()
    return job


def mark_fetch_failed(session: Session, job: Job, *, message: str) -> Job:
    """Record that a URL import failed.

    The job survives with its URL intact so the user can paste the description
    instead — ``GOAL.md`` requires a failure to leave the resource recoverable,
    and re-typing the link would be losing their work.
    """
    job.status = JobProcessingStatus.FAILED
    job.fetch_error = message
    session.flush()
    return job


def _is_placeholder_title(title: str) -> bool:
    """Whether the title is one we generated rather than one the user chose."""
    return title.strip().casefold() in {"untitled job", "importing…", "importing..."}


def _clean(value: str | None) -> str | None:
    """Blank becomes absent. A form submits "" for an untouched field, and that
    must not be stored as data."""
    if value is None:
        return None
    return value.strip() or None
