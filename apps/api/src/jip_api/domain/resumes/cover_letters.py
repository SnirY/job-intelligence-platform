"""Cover letters, and what validation concluded about each one.

Modelled on `resume_strategies` and `resume_claims` next door, because a letter
goes through the same gate a rewrite does: a model proposes words, deterministic
code decides whether the profile supports them, and a person clears it before it
counts as anything.

One difference matters and shapes both tables. A resume rewrite is anchored — it
has an original line, and validation compares the two. **A letter has no
original**, so every number in it is invented unless it came from the profile.
Validation is therefore run against an empty original, which is the strictest
setting `truth.py` has, and it is the correct one here.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import StrEnumType, TimestampMixin, UserOwnedMixin, new_uuid_column
from jip_api.domain.resumes.tailoring import ClaimStatus
from jip_api.infrastructure.db.base import Base


class CoverLetterStatus(enum.StrEnum):
    """Where a letter is between being drafted and being usable."""

    DRAFTING = "DRAFTING"
    """A draft is being generated. The user is watching."""

    DRAFTED = "DRAFTED"
    """A draft exists and has been validated. **Not yet approved by anyone.**"""

    EDITED = "EDITED"
    """A person has changed the text.

    Distinct from DRAFTED because it changes what the validation attached to it
    means: the claims were computed against the model's words, and a human edit
    is not re-validated. What a person writes about themselves is theirs, and
    running a fabrication check over it would be the system second-guessing the
    one source it treats as authoritative.
    """

    APPROVED = "APPROVED"
    """A person read it and said yes. Only this state is offered for use."""

    FAILED = "FAILED"
    """Drafting did not produce a letter. The reason is on `error`."""


class CoverLetter(TimestampMixin, UserOwnedMixin, Base):
    """One letter, for one job."""

    __tablename__ = "cover_letters"

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    """Deleting the job takes the letter with it. Unlike an application, a
    letter written for a role has no meaning once the role is gone."""

    status: Mapped[CoverLetterStatus] = mapped_column(
        StrEnumType(CoverLetterStatus, 20), nullable=False
    )

    angle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """The argument the letter was asked to make, in the user's words or the
    default. Stored because a letter that reads oddly is usually answering a
    question nobody can see."""

    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The letter. Null while drafting, and null if drafting failed."""

    angle_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The model saying the requested angle is not supported by the facts.

    Shown to the user rather than logged. It is the most useful thing a draft
    can say when the honest answer is that this letter cannot be written the way
    it was asked for.
    """

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why drafting failed, in words safe to show. Cleared on success."""

    prompt_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    """Which prompt produced this. Recorded for the same reason every other AI
    output records it: the text has to keep meaning what it meant."""

    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The panel reads the newest letter for one job. Scoped by user first,
        # because an index on the job alone would still be correct and would
        # scan rows belonging to other people to prove it.
        Index("ix_cover_letters_user_job", "user_id", "job_id", "created_at"),
    )

    @property
    def is_usable(self) -> bool:
        """Whether this is something the user has actually cleared."""
        return self.status is CoverLetterStatus.APPROVED


class CoverLetterClaim(TimestampMixin, UserOwnedMixin, Base):
    """One assertion found in a draft, and what validation made of it.

    The same shape as `ResumeClaim`, and stored for the same reason: a verdict
    the user cannot see the working for is a verdict they cannot argue with, and
    `docs/06` wants a blocked claim quoted back rather than silently dropped.
    """

    __tablename__ = "cover_letter_claims"

    id: Mapped[uuid.UUID] = new_uuid_column()

    cover_letter_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cover_letters.id", ondelete="CASCADE"), nullable=False
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    """The sentence, quoted from the draft."""

    status: Mapped[ClaimStatus] = mapped_column(StrEnumType(ClaimStatus, 30), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    __table_args__ = (Index("ix_cover_letter_claims_letter", "cover_letter_id"),)
