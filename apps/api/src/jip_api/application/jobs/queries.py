"""Reading jobs: one, or a filtered page of them.

``docs/10-api-contracts.md`` sets the pagination shape (``page``/``page_size``,
default 20, maximum 100) and ``docs/08-ui-ux.md`` lists the filters worth
having. The ones that depend on match scores or application status are absent —
neither exists yet, and a filter that silently matches nothing is worse than no
filter.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.domain.jobs.models import Job, JobProcessingStatus

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class JobSort(enum.StrEnum):
    """Orderings the list offers."""

    NEWEST = "NEWEST"
    OLDEST = "OLDEST"
    TITLE = "TITLE"
    COMPANY = "COMPANY"


class ArchivedFilter(enum.StrEnum):
    """Which side of the archive to show.

    Explicit rather than a boolean, because "everything" is a real answer the
    user wants and a nullable boolean expressing three states is a puzzle at
    every call site.
    """

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    ALL = "ALL"


@dataclass(slots=True)
class JobFilters:
    """What the caller asked for."""

    search: str | None = None
    company: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    status: JobProcessingStatus | None = None
    archived: ArchivedFilter = ArchivedFilter.ACTIVE
    sort: JobSort = JobSort.NEWEST
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(slots=True)
class JobPage:
    """One page of results, plus what the caller needs to page through them."""

    items: list[Job] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return -(-self.total // self.page_size)  # ceiling division


def list_jobs(session: Session, user_id: uuid.UUID, filters: JobFilters) -> JobPage:
    """Return a filtered, sorted page of the user's jobs.

    The count runs against the same filters as the page. Counting an unfiltered
    set would give a pager that promises results a filtered query cannot show.
    """
    page = max(1, filters.page)
    page_size = min(max(1, filters.page_size), MAX_PAGE_SIZE)

    base = _apply_filters(owned(Job, user_id), filters)

    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    statement = _apply_sort(base, filters.sort).limit(page_size).offset((page - 1) * page_size)
    items = list(session.execute(statement).scalars())

    return JobPage(items=items, total=int(total), page=page, page_size=page_size)


def _apply_filters(statement: Select[tuple[Job]], filters: JobFilters) -> Select[tuple[Job]]:
    if filters.archived is ArchivedFilter.ACTIVE:
        statement = statement.where(Job.archived_at.is_(None))
    elif filters.archived is ArchivedFilter.ARCHIVED:
        statement = statement.where(Job.archived_at.is_not(None))

    if filters.search:
        # ILIKE across the fields a person would search by. Not full-text
        # search: PostgreSQL's would need a tsvector column and a migration to
        # maintain it, which is worth doing when the list is long enough to
        # need ranking rather than filtering.
        pattern = f"%{_escape_like(filters.search.strip())}%"
        statement = statement.where(
            or_(
                Job.title.ilike(pattern, escape="\\"),
                Job.company.ilike(pattern, escape="\\"),
                Job.location.ilike(pattern, escape="\\"),
                Job.description.ilike(pattern, escape="\\"),
            )
        )

    if filters.company:
        pattern = f"%{_escape_like(filters.company)}%"
        statement = statement.where(Job.company.ilike(pattern, escape="\\"))
    if filters.work_mode:
        statement = statement.where(Job.work_mode == filters.work_mode)
    if filters.employment_type:
        statement = statement.where(Job.employment_type == filters.employment_type)
    if filters.seniority:
        statement = statement.where(Job.seniority == filters.seniority)
    if filters.status is not None:
        statement = statement.where(Job.status == filters.status)

    return statement


def _apply_sort(statement: Select[tuple[Job]], sort: JobSort) -> Select[tuple[Job]]:
    """Order the results.

    Every ordering ends with a tie-break on `id`. Without one, two jobs added
    in the same transaction have no defined order, and a row can appear on two
    pages or on neither.
    """
    match sort:
        case JobSort.NEWEST:
            return statement.order_by(Job.created_at.desc(), Job.id.desc())
        case JobSort.OLDEST:
            return statement.order_by(Job.created_at.asc(), Job.id.asc())
        case JobSort.TITLE:
            return statement.order_by(Job.normalized_title.asc(), Job.id.asc())
        case JobSort.COMPANY:
            # Jobs with no company sort last rather than leading the list.
            return statement.order_by(
                Job.company.is_(None), Job.company.asc(), Job.normalized_title.asc(), Job.id.asc()
            )


def get_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Return one of the user's jobs, or raise.

    Scoped by user *and* id. Filtering on the id alone would match another
    user's row, and the error is identical whether the job is missing or simply
    not theirs.
    """
    job = session.execute(owned(Job, user_id).where(Job.id == job_id)).scalar_one_or_none()
    if job is None:
        raise ResourceNotFoundError("Job not found.")
    return job


def known_companies(session: Session, user_id: uuid.UUID) -> list[str]:
    """Distinct company names, for the filter dropdown.

    Built from the user's own jobs so the filter offers only values that can
    actually return something.
    """
    statement = (
        owned(Job, user_id)
        .where(Job.company.is_not(None))
        .with_only_columns(Job.company)
        .distinct()
        .order_by(Job.company)
    )
    return [row for row in session.execute(statement).scalars() if row]


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards in user input.

    Without this, a search for "100%" matches everything — and `_` silently
    matches any character, which reads as a broken search rather than a clever
    one.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
