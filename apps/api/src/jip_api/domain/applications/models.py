"""Applications: the user's relationship with an opportunity.

``docs/07-applications-and-career-intelligence.md`` states the separation this
module exists to preserve:

```text
Job = the opportunity
Application = the user's relationship with that opportunity
```

A job may exist without an application, and most will. Without that split,
dragging a card on the tracker would rewrite the job library — and the funnel's
first conversion rate, *jobs saved to applications submitted*, would always be
100%.

Two tables:

- :class:`Application` is the current state, and the only mutable one.
- :class:`ApplicationEvent` is the history, and is append-only.
  ``docs/11-engineering-standards.md`` lists application events among the things
  that must never be mutated, alongside used resume versions and historical
  matches.

Nothing here writes to ``jobs``. ``Job.status`` tracks our own pipeline —
fetching, parsing, analysing — and means something entirely different from where
the user has got to.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base


class ApplicationStatus(enum.StrEnum):
    """The lifecycle from ``docs/07-applications-and-career-intelligence.md``.

    Fourteen values in one enum rather than a stage plus an outcome. They are
    genuinely one sequence — a rejection *is* where the process got to — and
    splitting them would mean every query about "where is this" had to consult
    two columns and know which one wins.
    """

    SAVED = "SAVED"
    INTERESTED = "INTERESTED"
    ANALYZING = "ANALYZING"
    PREPARING = "PREPARING"
    READY_TO_APPLY = "READY_TO_APPLY"
    APPLIED = "APPLIED"
    HR_SCREEN = "HR_SCREEN"
    TECHNICAL_INTERVIEW = "TECHNICAL_INTERVIEW"
    FINAL_INTERVIEW = "FINAL_INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    GHOSTED = "GHOSTED"
    ARCHIVED = "ARCHIVED"

    @property
    def is_terminal(self) -> bool:
        """The process has ended, however it ended.

        ``GHOSTED`` counts: silence past a point is an outcome, and the funnel
        needs it separated from an explicit rejection because they say different
        things about what went wrong.
        """
        return self in _TERMINAL

    @property
    def is_before_applying(self) -> bool:
        """Still preparation. Nothing has been sent.

        The funnel in ``docs/07`` divides here — everything above this line is
        intent, everything below it is a real outcome — so it is worth a name
        rather than a comparison written out at each call site.
        """
        return self in _BEFORE_APPLYING

    @property
    def is_active(self) -> bool:
        """Live, and waiting on somebody."""
        return not self.is_terminal


_TERMINAL: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.GHOSTED,
        ApplicationStatus.ARCHIVED,
    }
)

_BEFORE_APPLYING: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.SAVED,
        ApplicationStatus.INTERESTED,
        ApplicationStatus.ANALYZING,
        ApplicationStatus.PREPARING,
        ApplicationStatus.READY_TO_APPLY,
    }
)


class ApplicationSource(enum.StrEnum):
    """Where the application was submitted.

    ``docs/07`` requires the source to be preserved on apply. It is a real
    signal for Phase 10 — a referral and a job board are not the same channel —
    and it cannot be reconstructed later.
    """

    COMPANY_WEBSITE = "COMPANY_WEBSITE"
    JOB_BOARD = "JOB_BOARD"
    LINKEDIN = "LINKEDIN"
    REFERRAL = "REFERRAL"
    RECRUITER = "RECRUITER"
    EMAIL = "EMAIL"
    OTHER = "OTHER"


class ApplicationEventType(enum.StrEnum):
    """What kind of thing happened.

    Kept distinct from the status it may carry: a note and a status change are
    both history, and a timeline that could only show status changes would lose
    half of what the user recorded.
    """

    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    RESUME_ATTACHED = "RESUME_ATTACHED"
    SUBMITTED = "SUBMITTED"
    NOTE_ADDED = "NOTE_ADDED"
    FEEDBACK_RECORDED = "FEEDBACK_RECORDED"


class Application(TimestampMixin, UserOwnedMixin, Base):
    """One user's pursuit of one job."""

    __tablename__ = "applications"
    __table_args__ = (
        # One application per job per user. A second one would split the history
        # of a single pursuit across two timelines, and the funnel would count
        # it twice.
        UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
        Index("ix_applications_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        StrEnumType(ApplicationStatus, 30), nullable=False
    )

    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, not CASCADE: the version that was sent is the record of what
        # the employer read. Deleting it would leave an application claiming to
        # have sent something that no longer exists.
        ForeignKey("resume_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )

    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When it was actually sent, which is not when the row was created.

    Nullable because most of the lifecycle happens before this exists, and
    because a user recording an application after the fact must be able to
    supply the real date rather than today's.
    """

    source: Mapped[ApplicationSource | None] = mapped_column(
        StrEnumType(ApplicationSource, 30), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The user's own working notes. Freely editable — unlike the events."""

    rejection_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What the employer actually said, in their words.

    Deliberately its own column rather than a note. ``docs/07`` requires known
    feedback to be stored separately from system inference, and forbids
    presenting a guessed reason as fact. Nothing in this phase writes here
    except the user.
    """

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    @property
    def has_been_sent(self) -> bool:
        """True once the application left the user's hands.

        Reads ``applied_at`` rather than the status, because a rejected
        application is past APPLIED and a withdrawn one may never have reached
        it. The date is the fact; the status is where things stand.
        """
        return self.applied_at is not None


class ApplicationEvent(TimestampMixin, UserOwnedMixin, Base):
    """One thing that happened, kept forever.

    Append-only by contract, not by database trigger — nothing in the
    application layer offers an update or a delete, and
    ``docs/11-engineering-standards.md`` names these among the rows that must
    not be mutated.

    The event carries its own copy of the statuses it moved between rather than
    pointing at whatever the application says now. A history that has to be
    replayed against current state is not a history.
    """

    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_app_time", "application_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = new_uuid_column()

    application_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[ApplicationEventType] = mapped_column(
        StrEnumType(ApplicationEventType, 30), nullable=False
    )

    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        StrEnumType(ApplicationStatus, 30), nullable=True
    )
    to_status: Mapped[ApplicationStatus | None] = mapped_column(
        StrEnumType(ApplicationStatus, 30), nullable=True
    )

    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """When the thing happened, which the user may backdate.

    Separate from ``created_at``, which is when we recorded it. Someone
    entering three weeks of history in one sitting needs the timeline to read
    correctly, and conflating the two would compress it into one afternoon.
    """

    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    """One line, written at the time, in the past tense."""

    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
