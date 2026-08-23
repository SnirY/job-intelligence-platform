"""Jobs the user is considering, and where each one came from.

Two tables with different jobs, in the literal sense:

``Job`` is the working record — what the user sees, edits, filters, and later
matches against. ``JobImport`` is the receipt: the untouched content as it
arrived, kept because a posting is taken down within weeks and the original is
the only evidence of what was actually advertised (``GOAL.md``: preserve raw
inputs, and do not overwrite meaningful historical state).

The separation is what makes "never replace the original with a cleaned
version" a schema property rather than a convention someone has to remember.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(raw: str) -> str:
    """Reduce a job title to a comparison key.

    Not a display value. Phase 6 compares a job's title against target roles,
    and "Senior Backend Engineer" versus "senior backend engineer  " must not
    be two different things.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip()


class JobImportMethod(enum.StrEnum):
    """How the job got here. From ``docs/10-api-contracts.md``."""

    PASTED_DESCRIPTION = "PASTED_DESCRIPTION"
    URL = "URL"
    MANUAL = "MANUAL"
    DISCOVERED = "DISCOVERED"
    """Found by a board scan and promoted by a person.

    Distinct from URL even though both start from a link. URL means the user
    brought that link; DISCOVERED means a scan offered it and they said yes.
    Only the second can answer "is watching these boards worth it", which is the
    question that decides whether discovery stays.

    No migration: `StrEnumType` stores these as VARCHAR precisely so that adding
    a member does not need one.
    """


class JobProcessingStatus(enum.StrEnum):
    """Where the job is in the pipeline.

    Follows Flow 3 in ``docs/02-user-flows.md`` as far as this phase reaches.
    MATCHING and READY belong to Phase 6 and are deliberately absent: a status
    nothing can set is a promise the UI would render and the backend could
    never fulfil.

    The two failure members are distinct on purpose. FAILED means there is no
    content — the user is offered a paste box. ANALYSIS_FAILED means the
    content is fine and the interpretation of it did not work, where offering a
    paste box would be telling someone to re-enter text that is already there.
    """

    FETCHING = "FETCHING"
    """A URL import is in flight."""

    RAW = "RAW"
    """Has content and is usable. Not yet analysed."""

    PARSING = "PARSING"
    """Reading the posting into requirements and responsibilities."""

    ANALYZING = "ANALYZING"
    """Interpreting the parse: role family and seniority."""

    ANALYZED = "ANALYZED"
    """Has a completed analysis. Phase 6 matches from here."""

    FAILED = "FAILED"
    """The fetch could not produce usable content.

    The job still exists, and the user can paste the description instead —
    ``GOAL.md`` requires a failure to leave the resource recoverable.
    """

    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    """The description is intact; analysing it did not work.

    The job, its description, and any previous analysis are all untouched. The
    user is offered a retry, not a re-entry.
    """

    @property
    def is_analysis_in_flight(self) -> bool:
        """Whether an analysis is running right now."""
        return self in {JobProcessingStatus.PARSING, JobProcessingStatus.ANALYZING}

    @property
    def has_content(self) -> bool:
        """Whether the job has usable text.

        Everything except the two states where content is absent or unproven.
        Used to decide whether analysis can even be offered.
        """
        return self not in {JobProcessingStatus.FETCHING, JobProcessingStatus.FAILED}


class WorkMode(enum.StrEnum):
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"


class Job(TimestampMixin, UserOwnedMixin, Base):
    """A role the user is considering.

    Every descriptive field is optional except the title. A job pasted at
    midnight from a phone has a title and a wall of text; demanding a location
    and an employment type before it can be saved would mean it does not get
    saved.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = new_uuid_column()

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    """Comparison key derived from the title. Regenerated whenever it changes."""

    company: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    work_mode: Mapped[WorkMode | None] = mapped_column(StrEnumType(WorkMode, 20), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """All three are what the *user* said, in this phase.

    Phase 5 infers them from the description and writes its answer to
    ``job_analyses``, a separate versioned table, precisely so an inference can
    never overwrite something a person typed
    (``docs/03-domain-model.md``: AI interpretation must not overwrite verified
    data). Stored as plain strings validated at the API boundary rather than as
    enum columns, because the vocabulary is shared with the career domain and
    pinning it here would couple the two.
    """

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The working text: editable, and what later phases read.

    Starts as a copy of whatever arrived. The pristine version lives in
    ``original_description`` and on the import record.
    """

    original_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The description exactly as first obtained. Written once, never updated.

    ``docs/03-domain-model.md`` names this field, and the goal for this phase
    is explicit that original source data must not be replaced by a cleaned or
    normalized version. Editing a job changes ``description`` only.
    """

    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    normalized_source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    """Comparison key for duplicate detection. See ``normalize_url``."""

    import_method: Mapped[JobImportMethod] = mapped_column(
        StrEnumType(JobImportMethod, 30), nullable=False
    )
    status: Mapped[JobProcessingStatus] = mapped_column(
        StrEnumType(JobProcessingStatus, 20), nullable=False, index=True
    )

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    """SHA-256 of the normalized description.

    The second duplicate signal: the same posting reached through two different
    URLs still produces the same text.
    """

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[dt.date | None] = mapped_column(DateTime(timezone=True), nullable=True)

    salary_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """Free text on purpose. Salary appears as ranges, currencies, periods, and
    "competitive"; parsing it into numbers would mean inventing a figure for
    every posting that does not state one."""

    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Archived rather than deleted.

    ``docs/11-engineering-standards.md`` forbids silently dropping user history,
    and Phase 10's insights read jobs the user decided against.
    """

    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why a URL import failed, in words safe to show. Cleared on success."""

    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "content_hash IS NULL OR length(content_hash) = 64", name="content_hash_length"
        ),
        # Duplicate detection scans these per user, so both need the user id
        # first — an index on the value alone would scan every user's rows.
        Index("ix_jobs_user_normalized_url", "user_id", "normalized_source_url"),
        Index("ix_jobs_user_content_hash", "user_id", "content_hash"),
        # The list defaults to newest-first among unarchived jobs.
        Index("ix_jobs_user_created", "user_id", "created_at"),
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def has_description(self) -> bool:
        """Whether there is text to read.

        The list needs this without shipping the description itself: fifty
        jobs would otherwise carry a megabyte of text nothing on screen shows.
        """
        return bool(self.description)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Job id={self.id} title={self.title!r}>"


class JobImport(TimestampMixin, UserOwnedMixin, Base):
    """The untouched record of one import attempt.

    Append-only. A retry adds a row; nothing here is ever updated, which is
    what makes it usable as evidence of what the posting actually said.
    """

    __tablename__ = "job_imports"

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    import_method: Mapped[JobImportMethod] = mapped_column(
        StrEnumType(JobImportMethod, 30), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Exactly what arrived: the pasted text, or the fetched HTML.

    Kept verbatim so a better extractor in a later phase can re-read it without
    asking the user to find the posting again — which, by then, is usually
    gone.
    """

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Main content pulled out of ``raw_content``. Null for a pasted import,
    where the raw content already is the text."""

    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """What the server *claimed*. Recorded, never trusted — the body is parsed
    on its own merits (``docs/11-engineering-standards.md``: never trust
    external metadata)."""

    http_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    content_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    final_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    """Where the fetch ended after redirects. Differs from ``source_url`` when
    the posting moved, and is worth keeping for exactly that reason."""

    redirect_chain: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Every hop, in order. An audit trail for a fetch that ended somewhere
    unexpected, and the thing to read first when a block looks wrong."""

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the content was obtained, as distinct from when the row was
    written — a retry writes a new row much later than the original attempt."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobImport id={self.id} method={self.import_method}>"


def job_metadata(job: Job) -> dict[str, Any]:  # pragma: no cover - convenience
    """Descriptive fields, for logging without dumping the description."""
    return {
        "job_id": str(job.id),
        "import_method": str(job.import_method),
        "status": str(job.status),
    }
