"""Background work the user can watch and, when it fails, retry.

``docs/10-api-contracts.md`` defines the async pattern: an expensive POST
answers 202 with a ``processing_job_id`` the frontend polls. That id has to
outlive the queue entry — RQ forgets a finished job after its result TTL, and
``GOAL.md`` requires that a failure leave the underlying resource recoverable.
So the job is a row, and the queue id is only a cross-reference.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base


class ProcessingJobKind(enum.StrEnum):
    """What a job is doing.

    Matching adds its own when Phase 6 arrives; naming it here in advance would
    be inventing a state nothing can reach.
    """

    RESUME_IMPORT = "RESUME_IMPORT"
    JOB_ANALYSIS = "JOB_ANALYSIS"


class ProcessingJobStatus(enum.StrEnum):
    """From ``docs/03-domain-model.md`` and ``docs/10-api-contracts.md``."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """Whether polling can stop."""
        return self in {
            ProcessingJobStatus.COMPLETED,
            ProcessingJobStatus.FAILED,
            ProcessingJobStatus.CANCELLED,
        }


class ProcessingStep(enum.StrEnum):
    """Where inside the job the work currently is.

    ``docs/10-api-contracts.md`` lists MATCHING as well; it arrives with Phase
    6, which is the first thing that can reach it. FETCHING stays absent for a
    different reason: a URL import records its progress on the job row itself
    rather than through a ``ProcessingJob``, so nothing would ever set it.
    """

    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    PARSING = "PARSING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"


class ProcessingJob(TimestampMixin, UserOwnedMixin, Base):
    """One unit of background work, observable and retriable."""

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = new_uuid_column()

    kind: Mapped[ProcessingJobKind] = mapped_column(
        StrEnumType(ProcessingJobKind, 40), nullable=False
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        StrEnumType(ProcessingJobStatus, 20), nullable=False, index=True
    )
    step: Mapped[ProcessingStep] = mapped_column(StrEnumType(ProcessingStep, 20), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    """What the job is working on, as a loose reference.

    Deliberately not a foreign key: jobs will point at several different tables
    as later phases add their own work, and ``docs/11-engineering-standards.md``
    asks only that a task be *associated with an entity*. The API resolves the
    reference through the owning use case, which enforces ownership anyway.
    """

    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Queue-side identifier, for correlating logs. Never used for status."""

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")

    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """Classified failure, from the taxonomy in ``docs/10-api-contracts.md``."""

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Safe to show the user. Provider detail and stack traces stay in the log."""

    is_retriable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    """Whether retrying could plausibly succeed.

    Recorded when the failure is classified rather than derived later: whether
    a retry can help is a property of *why* the job failed, and re-deriving it
    from a message is how a PDF that contains no text at all ends up being
    parsed five more times.
    """

    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
    )

    @property
    def can_be_retried(self) -> bool:
        """Whether trying again could plausibly work.

        The rule lived only inside `prepare_retry` until 2026-08-24, which meant
        the only way to learn whether a failure was worth another attempt was to
        attempt it and read the 409. Three fields have to agree, and every caller
        that wanted to know had to know all three.
        """
        return (
            self.status is ProcessingJobStatus.FAILED
            and self.is_retriable
            and self.attempts < self.max_attempts
        )

    @property
    def is_dead(self) -> bool:
        """Failed, and no retry will change that.

        The dead-letter question, answered in one place. Either the failure was
        classified as permanent — a PDF with no text layer stays a PDF with no
        text layer — or the attempts ran out.

        Kept as a property rather than a column because it is derived from three
        stored facts and a stored copy could disagree with them. What matters is
        that the derivation exists once.
        """
        return self.status is ProcessingJobStatus.FAILED and not self.can_be_retried

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProcessingJob id={self.id} kind={self.kind} status={self.status}>"
