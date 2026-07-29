"""Tailoring: strategy, suggestions, and the truth check between them.

``docs/09-mvp-roadmap.md`` and ``docs/11-engineering-standards.md`` both forbid
the shortcut this package exists to avoid:

> Resume tailoring is incomplete if one model call rewrites the whole document.

So the work is staged, and each stage is a table. A strategy says what to do; a
suggestion proposes one concrete change to one item; a claim records whether
that change is supported by evidence. The user then accepts or rejects it. No
model output reaches a resume without passing through all three.

The three vocabularies here are orthogonal and must stay that way:

- :class:`SuggestionRisk` — what *kind* of change this is.
- :class:`ClaimStatus` — whether the claim is *supported by evidence*.
- :class:`SuggestionStatus` — the *user's decision*.

A low-risk suggestion can still be UNSUPPORTED, and accepting a suggestion does
not make it true.
"""

from __future__ import annotations

import datetime as dt
import enum
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


class SuggestionType(enum.StrEnum):
    """From ``docs/03-domain-model.md``."""

    REWRITE = "REWRITE"
    REORDER = "REORDER"
    ADD_EXISTING_ITEM = "ADD_EXISTING_ITEM"
    REMOVE = "REMOVE"
    SHORTEN = "SHORTEN"
    EMPHASIZE = "EMPHASIZE"


class SuggestionStatus(enum.StrEnum):
    """The user's decision. From ``docs/03-domain-model.md``."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"


class SuggestionRisk(enum.StrEnum):
    """How much a change could distort the truth. From ``docs/06``.

    Low is grammar, shortening, reordering, equivalent terminology. High is a
    new technology, responsibility, scale, or achievement — the four ways a
    rewrite turns into a lie. ``docs/06`` requires medium and high to be
    reviewed, and this is what the UI reads to enforce that.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def requires_review(self) -> bool:
        return self is not SuggestionRisk.LOW


class ClaimStatus(enum.StrEnum):
    """Whether a claim is supported. From ``docs/05-ai-and-matching.md``.

    Distinct from risk on purpose. Risk asks "what sort of edit is this";
    this asks "is what it now says true of the person". A grammar fix is low
    risk and can still be BLOCKED if it changes a number.
    """

    SAFE = "SAFE"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"

    @property
    def may_apply_automatically(self) -> bool:
        """Only SAFE. Everything else needs a person to look at it."""
        return self is ClaimStatus.SAFE


class ResumeStrategy(TimestampMixin, UserOwnedMixin, Base):
    """What to do about one job, before anything is rewritten.

    ``docs/06-resume-engine.md`` requires a strategy to answer six questions,
    and they are six columns rather than one blob because the UI shows them
    separately and Phase 10 will count them.
    """

    __tablename__ = "resume_strategies"

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """The match this strategy read.

    A foreign key in one direction only: a strategy points at a match and never
    writes to one. The matching engine stays deterministic, and this is a
    consumer of it.
    """

    version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The tailored version this strategy produced, once one exists."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    emphasize: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    reduce: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    reorder_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_projects: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )

    missing_evidence: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Evidence the profile has but the resume does not show — a *resume* gap
    in ``docs/06``'s terms. Fixable by selection."""

    career_gaps: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Evidence the user genuinely lacks — a *career* gap. Not fixable by any
    amount of rewriting, and ``docs/06`` insists the two be distinguished."""

    selection: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    """What deterministic selection chose, recorded beside what the model said
    about it. Kept so a strategy can be re-read without re-running selection."""

    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )

    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_resume_strategies_job_version", "job_id", "version"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeStrategy job={self.job_id} v{self.version}>"


class ResumeSuggestion(TimestampMixin, UserOwnedMixin, Base):
    """One proposed change to one item.

    Per-item rather than per-document, which is the whole point of the gate:
    every change is separately reviewable, separately validated, and separately
    accepted or rejected.
    """

    __tablename__ = "resume_suggestions"

    id: Mapped[uuid.UUID] = new_uuid_column()

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """The item this changes. Null for ADD_EXISTING_ITEM, which proposes
    something that is not on the page yet."""

    suggestion_type: Mapped[SuggestionType] = mapped_column(
        StrEnumType(SuggestionType, 20), nullable=False
    )
    status: Mapped[SuggestionStatus] = mapped_column(
        StrEnumType(SuggestionStatus, 20),
        nullable=False,
        server_default=SuggestionStatus.PENDING.value,
    )
    risk: Mapped[SuggestionRisk] = mapped_column(
        StrEnumType(SuggestionRisk, 10), nullable=False, server_default=SuggestionRisk.LOW.value
    )

    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What the user settled on, when they edited rather than accepted. Kept
    separate from ``suggested_text`` so the record still shows what was
    proposed versus what was taken."""

    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("length(trim(suggested_text)) > 0", name="suggested_text_not_blank"),
        Index("ix_resume_suggestions_strategy_order", "strategy_id", "display_order"),
    )

    @property
    def applied_text(self) -> str:
        """What would go on the page if this were applied."""
        return self.final_text or self.suggested_text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeSuggestion {self.suggestion_type} {self.status} risk={self.risk}>"


class ResumeClaim(TimestampMixin, UserOwnedMixin, Base):
    """One factual assertion inside a suggestion, and whether it holds.

    ``docs/05-ai-and-matching.md`` requires every generated statement to be
    decomposed into claims and checked against verified evidence. This is the
    result of that check, stored rather than computed on read, because the user
    sees it and later needs to know what was true at the time they decided.
    """

    __tablename__ = "resume_claims"

    id: Mapped[uuid.UUID] = new_uuid_column()

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_suggestions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    """The claim itself — a number, a technology, a scope."""

    status: Mapped[ClaimStatus] = mapped_column(StrEnumType(ClaimStatus, 30), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    """The career row that supports it, when one does."""

    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")

    __table_args__ = (
        CheckConstraint("length(trim(text)) > 0", name="text_not_blank"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
        Index("ix_resume_claims_suggestion", "suggestion_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ResumeClaim {self.status} {self.text[:40]!r}>"
