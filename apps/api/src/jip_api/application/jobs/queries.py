"""Reading jobs: one, or a filtered page of them.

``docs/10-api-contracts.md`` sets the pagination shape (``page``/``page_size``,
default 20, maximum 100) and ``docs/08-ui-ux.md`` lists the filters worth
having.

The filters that depend on application status are still absent, because that
still does not exist here. The ones that depend on match scores no longer have
that excuse: the list now carries a score per row, so a score range and a
"no blockers" preset became possible on the day this landed rather than
remaining permanently deferred behind a comment that had stopped being true.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import ScalarSelect

from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.matching.queries import assess_staleness_many
from jip_api.application.ownership import owned
from jip_api.domain.jobs.analysis import JobAnalysis
from jip_api.domain.jobs.models import Job, JobProcessingStatus
from jip_api.domain.matching.models import JobMatch
from jip_api.domain.matching.rules import ALIGNMENT_BANDS

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class JobSort(enum.StrEnum):
    """Orderings the list offers."""

    NEWEST = "NEWEST"
    OLDEST = "OLDEST"
    TITLE = "TITLE"
    COMPANY = "COMPANY"

    BEST_ALIGNED = "BEST_ALIGNED"
    """Highest alignment first, unscored jobs last.

    Offered, never the default. ``docs/05-ai-and-matching.md`` forbids reading
    the score as a chance of being hired, and a list that arrives already
    ordered by our number asserts a ranking of the user's opportunities before
    they asked for one. As something they switch to, it is a tool; as the
    default, it is a claim.
    """


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

    min_score: int | None = None
    max_score: int | None = None
    """An alignment band, as a closed range.

    Deliberately excludes unscored jobs rather than treating a missing score as
    zero: asking for "30 to 49" is a question about jobs that were measured, and
    a job nobody matched has no place in the answer. The screen reaches those
    through their own figure.
    """


@dataclass(slots=True)
class JobListItem:
    """A job as the list needs it: the row, and how it scored.

    The score is carried beside the job rather than on it because it does not
    belong to the job — it belongs to a versioned comparison between that job
    and a profile that both keep changing. ``None`` means no match has been
    computed, which is a different statement from a low score and has to stay
    tellable apart all the way to the screen.
    """

    job: Job
    score: int | None = None
    alignment_label: str | None = None
    is_stale: bool = False

    # What the coverage strip renders. `status_counts` is stored on the match
    # precisely so a summary can be drawn without loading every item, which is
    # the difference between one query for a page and one query per row.
    #
    # Empty and zero rather than null, because they only ever travel with a
    # score: a row with no match has no counts to be missing, and the dash is
    # already carrying that statement.
    status_counts: dict[str, int] = field(default_factory=dict)
    total_requirements: int = 0


@dataclass(slots=True)
class JobPage:
    """One page of results, plus what the caller needs to page through them."""

    items: list[JobListItem] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return -(-self.total // self.page_size)  # ceiling division


def list_jobs(session: Session, user_id: uuid.UUID, filters: JobFilters) -> JobPage:
    """Return a filtered, sorted page of the user's jobs, with their scores.

    The count runs against the same filters as the page. Counting an unfiltered
    set would give a pager that promises results a filtered query cannot show.

    Scores are fetched for the page rather than for the account. The dashboard
    reads every match a user has because it ranks across all of them; a list
    page needs twenty, and loading the rest to discard them would make the query
    grow with the archive rather than with the page.
    """
    page = max(1, filters.page)
    page_size = min(max(1, filters.page_size), MAX_PAGE_SIZE)

    base = _apply_filters(owned(Job, user_id), filters, user_id)

    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    statement = (
        _apply_sort(base, filters.sort, user_id).limit(page_size).offset((page - 1) * page_size)
    )
    jobs = list(session.execute(statement).scalars())

    return JobPage(
        items=_with_scores(session, user_id, jobs),
        total=int(total),
        page=page,
        page_size=page_size,
    )


def _with_scores(session: Session, user_id: uuid.UUID, jobs: list[Job]) -> list[JobListItem]:
    """Pair each job on the page with its latest match, if it has one."""
    if not jobs:
        return []

    job_ids = [job.id for job in jobs]

    # Recalculation appends versions, so the newest wins. Ordering by version
    # and overwriting is the same shape the dashboard uses.
    latest: dict[uuid.UUID, JobMatch] = {}
    for row in session.scalars(
        owned(JobMatch, user_id).where(JobMatch.job_id.in_(job_ids)).order_by(JobMatch.version)
    ):
        latest[row.job_id] = row

    analysis_versions: dict[uuid.UUID, int | None] = {}
    for job_id, version in session.execute(
        select(JobAnalysis.job_id, func.max(JobAnalysis.version))
        .where(JobAnalysis.job_id.in_(job_ids))
        .group_by(JobAnalysis.job_id)
    ):
        analysis_versions[job_id] = version

    staleness = assess_staleness_many(
        session, user_id, latest, current_analysis_versions=analysis_versions
    )

    items: list[JobListItem] = []
    for job in jobs:
        match = latest.get(job.id)
        if match is None:
            items.append(JobListItem(job=job))
            continue

        items.append(
            JobListItem(
                job=job,
                score=match.overall_score,
                alignment_label=match.alignment_label,
                is_stale=staleness[job.id].is_stale,
                status_counts={str(k): int(v) for k, v in match.status_counts.items()},
                total_requirements=match.total_requirements,
            )
        )

    return items


@dataclass(frozen=True, slots=True)
class AlignmentBucket:
    """One band of the distribution, with the words that name it."""

    floor: int
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class AlignmentDistribution:
    """The shape of a filtered set, so a reader can reach a subset without
    walking pages of rows.

    ``unscored`` is its own figure rather than a sixth band. A job nobody has
    matched has not scored badly, and folding it into the lowest band would make
    "Little alignment" a claim about jobs no one measured — the same error
    DEV-027 was, arriving through a histogram.
    """

    buckets: list[AlignmentBucket]
    unscored: int

    @property
    def total(self) -> int:
        return sum(bucket.count for bucket in self.buckets) + self.unscored


def alignment_distribution(
    session: Session, user_id: uuid.UUID, filters: JobFilters
) -> AlignmentDistribution:
    """How the filtered jobs spread across the alignment bands.

    Across the whole filtered set rather than the page. The point of the figure
    is to reach eighteen jobs without paging through ten screens, and a
    distribution of the twenty rows already visible would answer a question
    nobody asked.

    Bands come from ``ALIGNMENT_BANDS`` rather than being restated here. They are
    the words the product uses for a score everywhere else, and a histogram
    bucketed on its own thresholds would eventually disagree with the label on
    the row beside it.

    Filtered through the same ``_apply_filters`` as the list, so the two cannot
    describe different sets.
    """
    base = _apply_filters(owned(Job, user_id), filters, user_id).subquery()
    score = _latest_score(user_id, job_column=base.c.id)

    rows = session.execute(select(base.c.id, score.label("score"))).all()

    floors = [floor for floor, _ in ALIGNMENT_BANDS]
    counts = dict.fromkeys(floors, 0)
    unscored = 0

    for _, value in rows:
        if value is None:
            unscored += 1
            continue
        # `ALIGNMENT_BANDS` is ordered high to low, so the first floor the score
        # clears is its band — the same walk `alignment_label` does.
        counts[next(floor for floor in floors if value >= floor)] += 1

    return AlignmentDistribution(
        buckets=[
            AlignmentBucket(floor=floor, label=label, count=counts[floor])
            for floor, label in ALIGNMENT_BANDS
        ],
        unscored=unscored,
    )


def _apply_filters(
    statement: Select[tuple[Job]], filters: JobFilters, user_id: uuid.UUID
) -> Select[tuple[Job]]:
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

    if filters.min_score is not None or filters.max_score is not None:
        # `IS NOT NULL` is implied by either comparison in SQL, but stating it
        # says the intent out loud: a band is a question about measured jobs.
        score = _latest_score(user_id)
        statement = statement.where(score.is_not(None))
        if filters.min_score is not None:
            statement = statement.where(score >= filters.min_score)
        if filters.max_score is not None:
            statement = statement.where(score <= filters.max_score)

    return statement


def _apply_sort(
    statement: Select[tuple[Job]], sort: JobSort, user_id: uuid.UUID
) -> Select[tuple[Job]]:
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
        case JobSort.BEST_ALIGNED:
            score = _latest_score(user_id)
            # Unscored last, and the `is_(None)` term rather than a bare DESC
            # because PostgreSQL sorts nulls first under DESC — which would open
            # the list with every job that has never been measured.
            #
            # They sort last but they are not ranked last: the screen has to
            # separate them and say so. An unmeasured job placed at the bottom
            # of a ranking, unlabelled, reads as the worst one, and that is
            # DEV-027 arriving through the sort order instead of through a
            # badge.
            return statement.order_by(
                score.is_(None), score.desc(), Job.created_at.desc(), Job.id.desc()
            )


def _latest_score(user_id: uuid.UUID, job_column: Any = None) -> ScalarSelect[int | None]:
    """The newest match's score for whichever job is being ordered.

    Correlated rather than joined, because a join to `job_matches` multiplies
    the rows by the number of recalculations and the page would then need a
    DISTINCT that fights its own ORDER BY.

    Scoped by user as well as by job. The correlation alone would be safe today,
    since the outer query is already scoped and a match points at one job, but
    `owned()` exists precisely so that reasoning does not have to be redone at
    each call site.
    """
    target = Job.id if job_column is None else job_column
    statement = (
        select(JobMatch.overall_score)
        .where(JobMatch.job_id == target, JobMatch.user_id == user_id)
        .order_by(JobMatch.version.desc())
        .limit(1)
    )
    # Correlating on `Job` is only right when the outer query selects it; the
    # distribution correlates against its own filtered subquery instead.
    if job_column is None:
        statement = statement.correlate(Job)
    return statement.scalar_subquery()


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
