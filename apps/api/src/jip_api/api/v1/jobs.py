"""Job workspace endpoints.

The four routes in ``docs/10-api-contracts.md`` — create, list, get, source —
plus the lifecycle the workspace needs to be usable: update, archive,
unarchive, delete, and the manual-description fallback for a failed URL import.

Creation takes one endpoint with an ``import_method``, as the contract
specifies, rather than three near-identical routes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser, DispatcherDep
from jip_api.application.jobs import analysis_uc
from jip_api.application.jobs import creation as creation_uc
from jip_api.application.jobs import importing as importing_uc
from jip_api.application.jobs import legitimacy as legitimacy_uc
from jip_api.application.jobs import queries as queries_uc
from jip_api.application.jobs import updates as updates_uc
from jip_api.application.processing import reaper
from jip_api.core.errors import UnprocessableEntityError
from jip_api.core.responses import CollectionResponse, DataResponse, PaginationMeta
from jip_api.domain.career.history import EmploymentType
from jip_api.domain.career.models import Seniority
from jip_api.domain.jobs.analysis import (
    AnalyzedSeniority,
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
    RoleFamily,
)
from jip_api.domain.jobs.legitimacy import ConcernConfidence, PostingConcernType
from jip_api.domain.jobs.models import (
    Job,
    JobImportMethod,
    JobProcessingStatus,
    WorkMode,
)
from jip_api.domain.processing.models import ProcessingJobStatus, ProcessingStep
from jip_api.infrastructure.db.session import get_session
from jip_api.infrastructure.fetching.safety import UnsafeUrlError, validate_url
from jip_api.infrastructure.tasks.dispatcher import TaskDispatcher
from jip_config import get_settings

router = APIRouter(prefix="/jobs", tags=["jobs"])

MAX_BULK_ARCHIVE = queries_uc.MAX_PAGE_SIZE
"""A selection cannot exceed what one page can show.

Tied to the page size rather than picked, because the only way to select rows is
to see them. A larger bound would only be reachable by a caller building the
list by hand, which is not a case worth carrying an unbounded `IN` clause for.
"""

SessionDep = Annotated[Session, Depends(get_session)]

PLACEHOLDER_TITLE = "Untitled job"
"""Used when a URL import supplies no title.

A URL import has no title until the page has been fetched, and the title column
is required — a job with no name at all would be unreachable in the list.
Replaced by the page's own title when one is found.
"""


# --- payloads -----------------------------------------------------------------


class JobPayload(BaseModel):
    """A job as the workspace shows it.

    Everything here is either what the user typed or what the source said.
    Requirements and summaries exist as of Phase 5, but they are interpretation
    and live on the analysis — keeping them off this payload is what stops a
    reading being served in the same shape as a fact. Match scores and
    recommendations do not exist at all.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company: str | None
    location: str | None
    work_mode: WorkMode | None
    employment_type: str | None
    seniority: str | None
    role_family: str | None
    description: str | None
    source_url: str | None
    import_method: JobImportMethod
    status: JobProcessingStatus
    notes: str | None
    salary_text: str | None
    fetch_error: str | None
    archived_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class JobSummaryPayload(BaseModel):
    """A job as the list shows it.

    Without the description: a list of fifty jobs would otherwise ship a
    megabyte of text nothing on screen displays.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company: str | None
    location: str | None
    work_mode: WorkMode | None
    employment_type: str | None
    seniority: str | None
    status: JobProcessingStatus
    import_method: JobImportMethod
    source_url: str | None
    archived_at: dt.datetime | None
    created_at: dt.datetime
    has_description: bool

    # How the job scored, which the list could not say until now. `docs/05`
    # requires the number to travel with the word "alignment" wherever it is
    # shown, so the label ships with it rather than being reconstructed by
    # whichever screen happens to render the figure.
    #
    # Null means no match has been computed. That is a statement about our data
    # and not about the candidate, so it must reach the screen as a dash rather
    # than a zero — see the note on `overall_score` in the matching models.
    score: int | None = None
    alignment_label: str | None = None
    is_stale: bool = False

    # Enough to draw a coverage summary per row without asking for the items.
    # Keys are `MatchStatus` values; absent keys mean zero, so a caller must not
    # read the length of this as the number of requirement categories.
    status_counts: dict[str, int] = Field(default_factory=dict)
    total_requirements: int = 0


class JobImportPayload(BaseModel):
    """One import attempt, exactly as it happened."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    import_method: JobImportMethod
    source_url: str | None
    final_url: str | None
    redirect_chain: list[str]
    content_type: str | None
    http_status: int | None
    content_bytes: int | None
    error: str | None
    error_code: str | None
    imported_at: dt.datetime | None


class JobSourcePayload(BaseModel):
    """`GET /jobs/{id}/source` — the preserved original.

    Separate from the job payload because it is large and rarely needed, and
    because the distinction matters: this is what arrived, not what the job
    currently says.
    """

    job_id: uuid.UUID
    import_method: JobImportMethod
    source_url: str | None
    original_description: str | None
    raw_content: str | None
    extracted_text: str | None
    imports: list[JobImportPayload]


class JobCreateRequest(BaseModel):
    """`POST /jobs`.

    One endpoint with an ``import_method``, per ``docs/10-api-contracts.md``.
    """

    model_config = ConfigDict(extra="forbid")

    import_method: JobImportMethod
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    seniority: Seniority | None = None
    role_family: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=200_000)
    # AnyHttpUrl rather than str: it renders as a link, and it is handed to a
    # fetcher. The scheme is re-checked there too — this is the cheap first
    # gate, not the security control.
    source_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    salary_text: str | None = Field(default=None, max_length=200)

    allow_duplicate: bool = False
    """The explicit create-anyway path.

    A possible duplicate answers 409 with the existing job; the user re-submits
    with this set. Never the default — silently creating a second copy is what
    makes a job list stop being trustworthy.
    """

    @model_validator(mode="after")
    def check_method_requirements(self) -> Any:
        """Each import method needs something different to be meaningful.

        A URL import supplies a link and nothing else — the title arrives with
        the page. The other two need a title, and pasting needs the text that
        is the entire point of pasting.
        """
        if self.import_method is JobImportMethod.URL:
            if self.source_url is None:
                raise ValueError("source_url is required when importing from a URL")
            return self

        if not (self.title or "").strip():
            raise ValueError("title is required unless the job is imported from a URL")

        pasted = self.import_method is JobImportMethod.PASTED_DESCRIPTION
        if pasted and not (self.description or "").strip():
            raise ValueError("description is required when pasting a job description")

        return self

    @field_validator("title", "company", "location", "role_family", "notes", "salary_text")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class JobUpdateRequest(BaseModel):
    """`PATCH /jobs/{id}`. Omitted keys are left alone; null clears."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    seniority: Seniority | None = None
    role_family: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=200_000)
    notes: str | None = Field(default=None, max_length=10_000)
    salary_text: str | None = Field(default=None, max_length=200)

    def to_update(self, provided: set[str]) -> updates_uc.JobUpdate:
        update = updates_uc.JobUpdate()
        for name in ("work_mode", "employment_type", "seniority", "description"):
            if name in provided:
                setattr(update, name, getattr(self, name))
        for name in ("title", "company", "location", "role_family", "notes", "salary_text"):
            if name in provided:
                value = getattr(self, name)
                setattr(update, name, value.strip() or None if value else None)
        return update


class DescriptionRequest(BaseModel):
    """The manual fallback after a failed URL import."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=200_000)


class DuplicateDetails(BaseModel):
    """What a 409 carries, so the user can find the job they already have."""

    existing_job_id: uuid.UUID
    existing_title: str
    reason: Literal["SAME_URL", "SAME_CONTENT"]


class RequirementPayload(BaseModel):
    """One thing the posting asks for.

    ``source_text`` travels with every requirement, always. It is the whole
    point of the phase: the user can check our reading against the posting's
    own words without leaving the page.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_type: RequirementType
    importance: RequirementImportance
    explicitness: RequirementExplicitness
    source_text: str
    normalized_text: str
    confidence: int
    source_order: int
    skill_id: uuid.UUID | None
    skill_name: str | None
    years_min: int | None


class ResponsibilityPayload(BaseModel):
    """One thing the role does."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    source_text: str | None
    confidence: int
    source_order: int


class AnalysisPayload(BaseModel):
    """A versioned interpretation of a job.

    Judgements carry their reasoning and confidence in the same object, so a
    client cannot render a seniority without having the grounds for it to hand.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    version: int
    summary: str | None
    role_family: RoleFamily | None
    secondary_role_family: RoleFamily | None
    role_family_confidence: int | None
    role_family_reasoning: str | None
    seniority: AnalyzedSeniority
    seniority_confidence: int | None
    seniority_reasoning: str | None
    domain: str | None
    years_experience_min: int | None
    years_experience_max: int | None
    model: str
    parse_prompt_version: str
    analysis_prompt_version: str | None
    warnings: list[str]
    analyzed_at: dt.datetime | None
    created_at: dt.datetime


class ProcessingStatePayload(BaseModel):
    """The state of the most recent analysis attempt.

    Separate from the analysis itself because it exists before one does, and
    survives one that failed. It is what the frontend polls.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProcessingJobStatus
    step: ProcessingStep
    attempts: int
    error_code: str | None
    error_message: str | None
    is_retriable: bool


class JobAnalysisResponse(BaseModel):
    """Everything the Job Detail intelligence panel needs, in one call.

    One request rather than three: the analysis, its requirements, and its
    responsibilities are always rendered together, and splitting them would
    make a job with no analysis yet cost three round trips to discover that.
    """

    job_id: uuid.UUID
    job_status: JobProcessingStatus
    analysis: AnalysisPayload | None
    requirements: list[RequirementPayload]
    responsibilities: list[ResponsibilityPayload]
    processing: ProcessingStatePayload | None
    is_stale: bool
    """Whether the description has been edited since this analysis read it."""

    available_versions: list[int]
    can_analyze: bool
    """Whether asking for an analysis right now would be accepted. Keeps the
    button's enabled state and the endpoint's 409 rule in one place."""


class StartedAnalysisPayload(BaseModel):
    """The 202 body for a queued analysis."""

    job_id: uuid.UUID
    processing_job_id: uuid.UUID
    status: ProcessingJobStatus


# --- routes -------------------------------------------------------------------


@router.post(
    "",
    response_model=DataResponse[JobPayload],
    status_code=status.HTTP_201_CREATED,
    summary="Add a job",
)
def post_job(
    user: CurrentUser,
    session: SessionDep,
    dispatcher: DispatcherDep,
    body: JobCreateRequest,
) -> DataResponse[JobPayload]:
    """Create a job from a pasted description, a URL, or typed fields.

    A URL import returns immediately with the job in ``FETCHING`` and queues the
    fetch: a remote request can take seconds and must not hold the response
    open.

    A URL we will *never* fetch is refused here instead, before anything is
    written — see ``_refuse_permanently_blocked``.
    """
    _refuse_permanently_blocked(body)

    try:
        job = creation_uc.create_job(
            session,
            user.id,
            creation_uc.JobInput(
                title=body.title or PLACEHOLDER_TITLE,
                import_method=body.import_method,
                company=body.company,
                location=body.location,
                work_mode=body.work_mode,
                employment_type=body.employment_type,
                seniority=body.seniority,
                role_family=body.role_family,
                description=body.description,
                source_url=str(body.source_url) if body.source_url else None,
                notes=body.notes,
                salary_text=body.salary_text,
            ),
            allow_duplicate=body.allow_duplicate,
        )
    except creation_uc.DuplicateJobError as exc:
        # Raised as an APIError so the details reach the client: a bare 409
        # would leave the user unable to find the job they supposedly have.
        raise _duplicate_error(exc) from exc

    session.commit()

    if job.status is JobProcessingStatus.FETCHING:
        _dispatch_fetch(session, dispatcher, job)

    return DataResponse(data=JobPayload.model_validate(job))


class AlignmentBucketPayload(BaseModel):
    """One band, with the words the rest of the product uses for it."""

    model_config = ConfigDict(from_attributes=True)

    floor: int
    label: str
    count: int


class AlignmentDistributionPayload(BaseModel):
    """The shape of the filtered set.

    `unscored` stands apart from the bands rather than joining the lowest one. A
    job nobody matched has not scored badly, and counting it as "Little
    alignment" would make the histogram assert something about jobs no one
    measured.
    """

    model_config = ConfigDict(from_attributes=True)

    buckets: list[AlignmentBucketPayload]
    unscored: int
    total: int


@router.get(
    "/distribution",
    response_model=DataResponse[AlignmentDistributionPayload],
    summary="How the filtered jobs spread across the alignment bands",
)
def read_distribution(
    user: CurrentUser,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=200)] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    work_mode: WorkMode | None = None,
    employment_type: EmploymentType | None = None,
    seniority: Seniority | None = None,
    job_status: Annotated[JobProcessingStatus | None, Query(alias="status")] = None,
    archived: queries_uc.ArchivedFilter = queries_uc.ArchivedFilter.ACTIVE,
) -> DataResponse[AlignmentDistributionPayload]:
    """Across the whole filtered set, not the page.

    Takes the list's filters and none of its paging, because the figure exists
    to reach a subset without walking the pages — a distribution of the twenty
    rows already on screen would answer a question nobody asked.
    """
    result = queries_uc.alignment_distribution(
        session,
        user.id,
        queries_uc.JobFilters(
            search=search,
            company=company,
            work_mode=work_mode,
            employment_type=employment_type,
            seniority=seniority,
            status=job_status,
            archived=archived,
        ),
    )

    return DataResponse(
        data=AlignmentDistributionPayload(
            buckets=[AlignmentBucketPayload.model_validate(b) for b in result.buckets],
            unscored=result.unscored,
            total=result.total,
        )
    )


@router.get(
    "",
    response_model=CollectionResponse[JobSummaryPayload],
    summary="List jobs",
)
def read_jobs(
    user: CurrentUser,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=200)] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    work_mode: WorkMode | None = None,
    employment_type: EmploymentType | None = None,
    seniority: Seniority | None = None,
    job_status: Annotated[JobProcessingStatus | None, Query(alias="status")] = None,
    archived: queries_uc.ArchivedFilter = queries_uc.ArchivedFilter.ACTIVE,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    sort: queries_uc.JobSort = queries_uc.JobSort.NEWEST,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=queries_uc.MAX_PAGE_SIZE)] = (
        queries_uc.DEFAULT_PAGE_SIZE
    ),
) -> CollectionResponse[JobSummaryPayload]:
    """A filtered, sorted page of the user's jobs."""
    result = queries_uc.list_jobs(
        session,
        user.id,
        queries_uc.JobFilters(
            search=search,
            company=company,
            work_mode=work_mode,
            employment_type=employment_type,
            seniority=seniority,
            status=job_status,
            archived=archived,
            min_score=min_score,
            max_score=max_score,
            sort=sort,
            page=page,
            page_size=page_size,
        ),
    )

    return CollectionResponse(
        data=[
            # The job's own columns come from the ORM object; the three match
            # fields live beside it rather than on it, so they are layered on
            # after validation.
            JobSummaryPayload.model_validate(item.job).model_copy(
                update={
                    "score": item.score,
                    "alignment_label": item.alignment_label,
                    "is_stale": item.is_stale,
                    "status_counts": item.status_counts,
                    "total_requirements": item.total_requirements,
                }
            )
            for item in result.items
        ],
        meta=PaginationMeta(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            total_pages=result.total_pages,
        ),
    )


@router.get(
    "/companies",
    response_model=DataResponse[list[str]],
    summary="Companies in the user's jobs",
)
def read_companies(user: CurrentUser, session: SessionDep) -> DataResponse[list[str]]:
    """Values for the company filter.

    Built from the user's own jobs, so the filter offers only options that can
    return something.
    """
    return DataResponse(data=queries_uc.known_companies(session, user.id))


@router.get("/{job_id}", response_model=DataResponse[JobPayload], summary="Get a job")
def read_job(user: CurrentUser, session: SessionDep, job_id: uuid.UUID) -> DataResponse[JobPayload]:
    """One job, with a stranded import failed on the way past.

    DEV-042. A URL import has no processing job, so the sweep behind
    ``GET /processing-jobs/{id}`` cannot see it — this is the only route that
    can. The screen polls here while a fetch is running, which is exactly when
    somebody is waiting to find out.
    """
    job = queries_uc.get_job(session, user.id, job_id)

    if reaper.reap_stalled_fetch(
        session,
        job,
        timeout_seconds=get_settings().processing_running_timeout_seconds,
    ):
        session.commit()

    return DataResponse(data=JobPayload.model_validate(job))


@router.get(
    "/{job_id}/source",
    response_model=DataResponse[JobSourcePayload],
    summary="Get the preserved original source",
)
def read_job_source(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[JobSourcePayload]:
    """What arrived, as it arrived.

    Distinct from the job's current description, which the user may have
    edited. A posting is usually taken down within weeks and this is the only
    record of what was actually advertised.
    """
    job = queries_uc.get_job(session, user.id, job_id)
    imports = creation_uc.list_imports(session, job.id)
    newest = imports[-1] if imports else None

    return DataResponse(
        data=JobSourcePayload(
            job_id=job.id,
            import_method=JobImportMethod(job.import_method),
            source_url=job.source_url,
            original_description=job.original_description,
            raw_content=newest.raw_content if newest else None,
            extracted_text=newest.extracted_text if newest else None,
            imports=[JobImportPayload.model_validate(record) for record in imports],
        )
    )


@router.patch("/{job_id}", response_model=DataResponse[JobPayload], summary="Update a job")
def patch_job(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID, body: JobUpdateRequest
) -> DataResponse[JobPayload]:
    """Edit the working copy. The preserved original is not reachable here."""
    job = updates_uc.update_job(session, user.id, job_id, body.to_update(body.model_fields_set))
    session.commit()
    return DataResponse(data=JobPayload.model_validate(job))


@router.post(
    "/{job_id}/description",
    response_model=DataResponse[JobPayload],
    summary="Supply a description by hand",
)
def post_description(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID, body: DescriptionRequest
) -> DataResponse[JobPayload]:
    """The fallback when a URL import could not read the page.

    The job and its link survived the failure; this finishes the import without
    the user starting over.
    """
    job = updates_uc.supply_description(session, user.id, job_id, body.description)
    session.commit()
    return DataResponse(data=JobPayload.model_validate(job))


class BulkArchiveRequest(BaseModel):
    """The rows a reader selected."""

    job_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_BULK_ARCHIVE)]


class BulkArchivePayload(BaseModel):
    """What happened to each id, rather than whether it all worked.

    Two lists, because a screen has to be able to name what it could not do.
    "27 of 29 archived" with no way to see which two makes someone reselect
    thirty rows to find out.
    """

    archived: list[uuid.UUID]
    missing: list[uuid.UUID]


@router.post(
    "/archive",
    response_model=DataResponse[BulkArchivePayload],
    summary="Archive several jobs",
)
def post_bulk_archive(
    user: CurrentUser, session: SessionDep, body: BulkArchiveRequest
) -> DataResponse[BulkArchivePayload]:
    """Archive a selection, and report on every id in it.

    Declared before `/{job_id}/archive` for readability only — the two paths
    have different segment counts and cannot collide.

    Partial success is the success case. An id that is missing or belongs to
    someone else does not undo the ones that worked: archiving is reversible and
    the user asked for the rest. The response is what the screen says.
    """
    result = updates_uc.archive_jobs(session, user.id, body.job_ids)
    session.commit()
    return DataResponse(data=BulkArchivePayload(archived=result.archived, missing=result.missing))


@router.post("/{job_id}/archive", response_model=DataResponse[JobPayload], summary="Archive a job")
def post_archive(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[JobPayload]:
    job = updates_uc.archive_job(session, user.id, job_id)
    session.commit()
    return DataResponse(data=JobPayload.model_validate(job))


@router.post(
    "/{job_id}/unarchive", response_model=DataResponse[JobPayload], summary="Unarchive a job"
)
def post_unarchive(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[JobPayload]:
    job = updates_uc.unarchive_job(session, user.id, job_id)
    session.commit()
    return DataResponse(data=JobPayload.model_validate(job))


@router.post(
    "/{job_id}/retry-import",
    response_model=DataResponse[JobPayload],
    summary="Try the URL import again",
)
def post_retry_import(
    user: CurrentUser, session: SessionDep, dispatcher: DispatcherDep, job_id: uuid.UUID
) -> DataResponse[JobPayload]:
    """Queue the fetch again for a job whose import failed.

    Offered for any job that still has a URL: unlike a document with no text
    layer, a page that timed out or returned a 503 may well work on a second
    attempt.
    """
    job = queries_uc.get_job(session, user.id, job_id)
    if not job.source_url:
        raise _no_url_error()

    job.status = JobProcessingStatus.FETCHING
    job.fetch_error = None
    session.commit()

    _dispatch_fetch(session, dispatcher, job)
    return DataResponse(data=JobPayload.model_validate(job))


@router.delete(
    "/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a job permanently"
)
def remove_job(user: CurrentUser, session: SessionDep, job_id: uuid.UUID) -> Response:
    """Permanent. Archiving is what the UI offers by default."""
    updates_uc.delete_job(session, user.id, job_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the posting itself -------------------------------------------------------


class PostingConcernPayload(BaseModel):
    """One thing noticed about the posting, and what in it caused that."""

    type: PostingConcernType
    confidence: ConcernConfidence
    summary: str
    evidence: str | None
    """The posting's own words. Null where the rule measured rather than read —
    there is no phrase to quote for "this posting is very short"."""


class PostingConcernsPayload(BaseModel):
    """`GET /jobs/{id}/concerns` — what we noticed about the listing itself.

    **Its own endpoint rather than a field on `JobPayload`, and that is the
    point.** That payload carries what the user typed or what the source said;
    this is a reading, and `docs/05-ai-and-matching.md` requires the two to stay
    apart. Serving a reading in the same shape as a fact is how the two stop
    being distinguishable.

    There is deliberately no score and no overall verdict. A number can be
    averaged, weighted and eventually folded into the match; a list of named
    concerns cannot be, without someone writing the code that does it.
    """

    job_id: uuid.UUID
    rules_version: str
    concerns: list[PostingConcernPayload]


@router.get(
    "/{job_id}/concerns",
    response_model=DataResponse[PostingConcernsPayload],
    summary="What we noticed about the posting itself",
)
def read_concerns(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[PostingConcernsPayload]:
    """Concerns about the listing, never about the fit.

    An empty list means **no rule fired**. It is not a statement that the
    posting is trustworthy, and a screen may not render it as one.
    """
    job = queries_uc.get_job(session, user.id, job_id)
    reading = legitimacy_uc.for_job(session, job)

    return DataResponse(
        data=PostingConcernsPayload(
            job_id=job.id,
            rules_version=legitimacy_uc.RULES_VERSION,
            concerns=[
                PostingConcernPayload(
                    type=concern.type,
                    confidence=concern.confidence,
                    summary=concern.summary,
                    evidence=concern.evidence,
                )
                for concern in reading.concerns
            ],
        )
    )


# --- analysis -----------------------------------------------------------------


@router.get(
    "/{job_id}/analysis",
    response_model=DataResponse[JobAnalysisResponse],
    summary="Get a job's analysis",
)
def read_analysis(
    user: CurrentUser,
    session: SessionDep,
    job_id: uuid.UUID,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> DataResponse[JobAnalysisResponse]:
    """The newest analysis, or a specific version.

    Answers 200 with a null analysis for a job that has never been analysed,
    rather than 404. The job exists and this is the truthful state of it — a
    404 would say the *job* was missing, which is a different problem with a
    different fix.
    """
    job = queries_uc.get_job(session, user.id, job_id)

    # Before anything reads `job.status`: reaping a stalled attempt rewrites it,
    # and evaluating the two in argument order left the response carrying the
    # status from a moment earlier — a job reported as still PARSING beside a
    # processing record that had just been failed.
    processing = _processing_state(session, user.id, job_id)

    analysis = (
        analysis_uc.get_analysis_version(session, user.id, job_id, version)
        if version is not None
        else analysis_uc.latest_analysis(session, user.id, job_id)
    )

    requirements = analysis_uc.requirements_for(session, analysis.id) if analysis else []
    responsibilities = analysis_uc.responsibilities_for(session, analysis.id) if analysis else []

    return DataResponse(
        data=JobAnalysisResponse(
            job_id=job.id,
            job_status=JobProcessingStatus(job.status),
            analysis=AnalysisPayload.model_validate(analysis) if analysis else None,
            requirements=[RequirementPayload.model_validate(row) for row in requirements],
            responsibilities=[
                ResponsibilityPayload.model_validate(row) for row in responsibilities
            ],
            processing=processing,
            is_stale=analysis_uc.is_stale(job, analysis),
            available_versions=analysis_uc.analysis_versions(session, user.id, job_id),
            can_analyze=_can_analyze(job),
        )
    )


@router.post(
    "/{job_id}/analysis",
    response_model=DataResponse[StartedAnalysisPayload],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Analyse a job",
)
def post_analysis(
    user: CurrentUser,
    session: SessionDep,
    dispatcher: DispatcherDep,
    job_id: uuid.UUID,
) -> DataResponse[StartedAnalysisPayload]:
    """Queue an analysis, or a reanalysis.

    The same endpoint for both: a reanalysis is not a different operation, it
    is the same one run again, and the result is a new version rather than a
    replacement. 202 with a ``processing_job_id`` to poll, per
    ``docs/10-api-contracts.md``.
    """
    job = queries_uc.get_job(session, user.id, job_id)

    try:
        started = analysis_uc.start_analysis(session, dispatcher, user_id=user.id, job=job)
    except analysis_uc.JobNotAnalyzableError as exc:
        raise _conflict(str(exc)) from exc

    return DataResponse(
        data=StartedAnalysisPayload(
            job_id=job.id,
            processing_job_id=started.processing_job.id,
            status=ProcessingJobStatus(started.processing_job.status),
        )
    )


@router.get(
    "/{job_id}/requirements",
    response_model=CollectionResponse[RequirementPayload],
    summary="Get a job's requirements",
)
def read_requirements(
    user: CurrentUser,
    session: SessionDep,
    job_id: uuid.UUID,
    importance: RequirementImportance | None = None,
    requirement_type: RequirementType | None = None,
) -> CollectionResponse[RequirementPayload]:
    """The newest analysis's requirements, optionally filtered.

    A separate endpoint from the analysis because Phase 6 wants exactly this
    and nothing else, and because a job with 120 requirements should not have
    to ship its whole analysis to get at them.
    """
    queries_uc.get_job(session, user.id, job_id)
    analysis = analysis_uc.latest_analysis(session, user.id, job_id)

    rows = analysis_uc.requirements_for(session, analysis.id) if analysis else []
    if importance is not None:
        rows = [row for row in rows if row.importance is importance]
    if requirement_type is not None:
        rows = [row for row in rows if row.requirement_type is requirement_type]

    return CollectionResponse(
        data=[RequirementPayload.model_validate(row) for row in rows],
        meta=PaginationMeta(
            page=1,
            page_size=len(rows),
            total=len(rows),
            total_pages=1 if rows else 0,
        ),
    )


# --- helpers ------------------------------------------------------------------


def _refuse_permanently_blocked(body: JobCreateRequest) -> None:
    """Refuse an address we will never fetch, before a job exists for it.

    DEV-041. The SSRF rules are deliberately not configurable, so a blocked
    address is blocked for good — and yet the flow used to save a job, queue a
    fetch, fail it, and leave the user on a screen offering *"paste the
    description"* and *"Try the link again"*. Neither can help: there is no
    description, because the user typed an address, and the retry cannot ever
    succeed. Three of those rows are what found this.

    That is DEV-021's rule — never offer a retry for a permanent failure —
    applied to the one path it had been missed on.

    Only ``BLOCKED_URL`` is refused here. A name that did not resolve is a fact
    about this moment, not about the address, and belongs in the queued fetch
    where a retry is honest. Distinguishing them is what `UnsafeUrlError.code`
    is for.

    The cost is one DNS lookup on the request path. That is milliseconds, and
    the reason fetching is queued at all is the page fetch rather than the name
    resolution.
    """
    if body.import_method is not JobImportMethod.URL or body.source_url is None:
        return

    try:
        validate_url(str(body.source_url))
    except UnsafeUrlError as exc:
        if not exc.is_permanent:
            # Transient. Let it through to the queue, which knows how to record
            # a failure the user can genuinely retry.
            return
        raise UnprocessableEntityError(
            str(exc),
            code="BLOCKED_URL",
            details={"source_url": str(body.source_url)},
        ) from exc


def _dispatch_fetch(session: Session, dispatcher: TaskDispatcher, job: Job) -> None:
    """Queue the fetch, recording a queue outage on the job.

    A failure here must not lose the job: it already exists with its URL, and
    the user can retry or paste instead.
    """
    try:
        dispatcher.enqueue(importing_uc.FETCH_JOB_TASK, str(job.id))
    except Exception as exc:  # a queue outage must land on the job, not lose it
        creation_uc.mark_fetch_failed(
            session,
            job,
            message="Importing could not be started. Your job was saved — try again.",
        )
        creation_uc.record_import(
            session,
            job,
            import_method=JobImportMethod.URL,
            source_url=job.source_url,
            error=f"{type(exc).__name__}: {exc}",
            error_code="DISPATCH_FAILED",
        )
        session.commit()


def _duplicate_error(exc: creation_uc.DuplicateJobError) -> Exception:
    from jip_api.core.errors import ConflictError

    return ConflictError(
        str(exc),
        details=DuplicateDetails(
            existing_job_id=exc.existing.id,
            existing_title=exc.existing.title,
            reason=exc.reason,  # type: ignore[arg-type]
        ).model_dump(mode="json"),
    )


def _no_url_error() -> Exception:
    from jip_api.core.errors import ConflictError

    return ConflictError("This job was not imported from a link.")


def _conflict(message: str) -> Exception:
    from jip_api.core.errors import ConflictError

    return ConflictError(message)


def _can_analyze(job: Job) -> bool:
    """Whether ``POST /analysis`` would be accepted for this job right now.

    Mirrors the refusals in
    :func:`jip_api.application.jobs.analysis_uc.start_analysis`, so the button
    the frontend renders and the rule the endpoint enforces agree. Kept as one
    expression rather than duplicated across both.
    """
    return bool((job.description or "").strip()) and not job.status.is_analysis_in_flight


def _processing_state(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> ProcessingStatePayload | None:
    """The latest analysis attempt, with a stalled one failed on the way past.

    Reaping here as well as in ``GET /processing-jobs/{id}`` because this is
    what the analysis screen actually polls. DEV-013 put the recovery behind
    the processing-jobs route on the reasoning that the frontend polls it —
    true of resume import, never true of job analysis, which watches this
    endpoint instead. ``reaper._release_entity`` has had a JOB_ANALYSIS branch
    since that issue closed and nothing could reach it.

    Found by stopping the worker mid-analysis during checklist item 2.5.4: the
    attempt sat RUNNING for an hour, the job stayed PARSING, and because
    ``start_analysis`` refuses to start one while another is in flight, the job
    was permanently unanalysable with no way back short of SQL.
    """
    record = analysis_uc.latest_processing_job(session, user_id, job_id)
    if record is None:
        return None

    settings = get_settings()
    if reaper.reap_if_stalled(
        session,
        record,
        pending_timeout_seconds=settings.processing_pending_timeout_seconds,
        running_timeout_seconds=settings.processing_running_timeout_seconds,
    ):
        session.commit()

    return ProcessingStatePayload.model_validate(record)
