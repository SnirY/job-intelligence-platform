"""How a job's requirements compare against what the user can evidence.

Three tables, and one rule that shapes all of them: **the verdict must be
traceable back to a fact**. ``docs/05-ai-and-matching.md`` calls this
evidence-first matching, and the shape here is what makes it real rather than
aspirational — every :class:`JobMatchItem` carries its score and its reasoning,
and every claim it makes points at the exact career row behind it through
:class:`JobMatchEvidence`.

The other rule is determinism. AI does not appear anywhere in this module.
``engine_version`` on the match records which set of rules produced a number, so
changing the rules is a visible event rather than a silent re-scoring of
history.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
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


class MatchStatus(enum.StrEnum):
    """The verdict on one requirement.

    Seven of these come from ``docs/05-ai-and-matching.md``; NO_EVIDENCE is the
    eighth, and the distinction it draws is the one this phase most needed.

    GAP, NO_EVIDENCE, and UNKNOWN all mean "no match", and treating them alike
    would be wrong in three different directions:

    - GAP is a real absence. We have coverage in this area and this specific
      thing is missing. It scores zero, and on a CORE requirement it blocks.
    - NO_EVIDENCE means we have nothing on file to judge with. It is excluded
      from the score entirely rather than scored zero, because an empty profile
      is a fact about our data, not a shortcoming of the candidate.
    - UNKNOWN means the requirement cannot be resolved deterministically at
      all — work authorisation, for instance, which the profile stores nothing
      about. Never a gap, never a blocker.
    """

    STRONG_MATCH = "STRONG_MATCH"
    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    TRANSFERABLE_MATCH = "TRANSFERABLE_MATCH"
    NO_EVIDENCE = "NO_EVIDENCE"
    GAP = "GAP"
    BLOCKER = "BLOCKER"
    UNKNOWN = "UNKNOWN"

    @property
    def is_positive(self) -> bool:
        """Whether this counts as coverage of the requirement."""
        return self in {
            MatchStatus.STRONG_MATCH,
            MatchStatus.MATCH,
            MatchStatus.PARTIAL_MATCH,
            MatchStatus.TRANSFERABLE_MATCH,
        }

    @property
    def is_scored(self) -> bool:
        """Whether this item contributes to the weighted average at all.

        NO_EVIDENCE is the only status that does not. Scoring it as zero would
        turn "we have not been told" into "the candidate lacks this", which is
        the failure the goal names explicitly.
        """
        return self is not MatchStatus.NO_EVIDENCE


class MatchCategory(enum.StrEnum):
    """How an item is grouped for category scoring.

    The six from ``docs/05-ai-and-matching.md``, plus OTHER.

    PREFERRED is a category rather than a property because that is how the
    document treats it — "preferred requirements" sit alongside technical and
    experience in the category list. An item lands there on its importance, not
    its type, so a preferred technical skill is scored as a preference.

    PROJECTS is not assigned from a requirement type, because no requirement
    asks for "a project". It is derived from where the winning evidence came
    from, and answers a question the others cannot: how much of this alignment
    is carried by things the user built rather than jobs they held.
    """

    TECHNICAL = "TECHNICAL"
    EXPERIENCE = "EXPERIENCE"
    PROJECTS = "PROJECTS"
    EDUCATION = "EDUCATION"
    DOMAIN = "DOMAIN"
    PREFERRED = "PREFERRED"
    OTHER = "OTHER"


class Recommendation(enum.StrEnum):
    """What to do about this job. From ``docs/02-user-flows.md``."""

    STRONG_APPLY = "STRONG_APPLY"
    APPLY = "APPLY"
    CONSIDER = "CONSIDER"
    LOW_PRIORITY = "LOW_PRIORITY"
    PROBABLY_SKIP = "PROBABLY_SKIP"


class EvidenceType(enum.StrEnum):
    """Which part of the career profile a piece of evidence came from.

    Nothing outside this set may be cited: an inference is not evidence, and
    neither is anything the user has not put in their profile. That rule is the
    point; the length of the list is not.

    CERTIFICATION was added 2026-08-16 (DEV-052) once certifications became a
    profile collection. It satisfies the rule exactly — a credential the user
    entered about themselves — and until it existed a held certification could
    not be cited even when it answered the requirement outright.
    """

    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    ACHIEVEMENT = "ACHIEVEMENT"
    PROJECT = "PROJECT"
    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"


class JobMatch(TimestampMixin, UserOwnedMixin, Base):
    """One versioned comparison of a job against a profile.

    Carries three versions rather than one, because there are three ways the
    answer can go out of date: the posting was re-read, the profile changed, or
    the rules changed. Staleness is then a comparison rather than a guess, and
    the UI can say *which* of the three moved.
    """

    __tablename__ = "job_matches"

    id: Mapped[uuid.UUID] = new_uuid_column()

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    """1, 2, 3… per job. Recalculation appends; it never replaces."""

    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    """Which reading of the posting this matched against."""

    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    """Hash over every evidence-bearing career row at match time.

    There is no ``CareerProfile.version`` column, and adding one would mean
    every write path in the career domain remembering to bump it. A fingerprint
    computed from the data itself cannot be forgotten, and it changes for
    exactly the edits that could change a match.
    """

    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    """Which rules produced these numbers. A score without this is not
    reproducible, and ``docs/05-ai-and-matching.md`` requires the values to be
    versioned and calibrated."""

    overall_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """0-100 profile alignment, or null when nothing could be scored.

    Null rather than zero for a profile with no relevant data at all. Zero is a
    claim about the candidate; null is a claim about our information.
    """

    alignment_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """The score in words. ``docs/05-ai-and-matching.md`` is explicit that a
    number must never be presented as a chance of being hired, and a label
    carries the intended meaning where a bare percentage does not."""

    score_cap: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    score_cap_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why the score was capped, when a blocker capped it. Recorded so the user
    can see that the ceiling was a decision rather than the arithmetic."""

    recommendation: Mapped[Recommendation] = mapped_column(
        StrEnumType(Recommendation, 20), nullable=False
    )
    recommendation_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Kept separate from the score on purpose.

    ``docs/05-ai-and-matching.md`` lists blockers, core requirements, role
    alignment, seniority, and gap severity as inputs a recommendation weighs
    beyond the number, so the two are allowed to disagree — a 70% with a
    blocker is not the same advice as a 70% without one.
    """

    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    """How much to trust this match, from how much of it rested on real
    evidence rather than on absence."""

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Natural language, optionally written by AI. Never a source of numbers."""

    category_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    """Per-category score and weight. ``docs/05-ai-and-matching.md``: category
    scores should be preserved separately."""

    status_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    """How many items landed in each status. What the summary bar renders
    without loading every item."""

    has_blockers: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    scored_requirements: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_requirements: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    """Both, because the gap between them is the honest measure of how much of
    this posting we could actually assess."""

    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Including an AI failure. AI is optional enrichment, so it failing is
    something to mention, not something to fail the match over."""

    computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_matches_job_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name="overall_score_range",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
        CheckConstraint(
            "scored_requirements >= 0 AND total_requirements >= scored_requirements",
            name="requirement_counts_sane",
        ),
        Index("ix_job_matches_job_version", "job_id", "version"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobMatch job={self.job_id} v{self.version} score={self.overall_score}>"


class JobMatchItem(TimestampMixin, UserOwnedMixin, Base):
    """The verdict on one requirement.

    ``docs/10-api-contracts.md`` names what each item must carry: the exact
    requirement, a status, a score, a weight, a confidence, an explanation, and
    evidence references. All seven are columns here rather than a JSON blob,
    because Phase 10's insights query across them — "which requirements are
    most often a gap" is a question about rows.
    """

    __tablename__ = "job_match_items"

    id: Mapped[uuid.UUID] = new_uuid_column()

    match_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[MatchStatus] = mapped_column(StrEnumType(MatchStatus, 20), nullable=False)
    category: Mapped[MatchCategory] = mapped_column(StrEnumType(MatchCategory, 20), nullable=False)

    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """0-100 for this requirement alone, from the status. Deterministic."""

    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    """How much this requirement counts, from its importance.

    Numeric rather than float: the weighted average must reproduce exactly, and
    binary floating point does not round-trip through a database predictably
    enough to promise that.
    """

    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    """Why this verdict, in the user's terms. Never empty — an item nobody can
    explain is an item nobody can check."""

    is_blocker: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("match_id", "requirement_id", name="uq_job_match_items_match_requirement"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint("weight >= 0", name="weight_not_negative"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="confidence_range"),
        CheckConstraint("length(trim(explanation)) > 0", name="explanation_not_blank"),
        Index("ix_job_match_items_match_order", "match_id", "source_order"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobMatchItem {self.status} score={self.score}>"


class JobMatchEvidence(TimestampMixin, UserOwnedMixin, Base):
    """One career fact supporting a match item.

    ``docs/08-ui-ux.md`` asks that a user be able to ask "why does the system
    think I match this?" and see the exact evidence. This is that answer, and
    the reason it is a table rather than a rendered string: the row it points at
    can be opened, and a claim that cannot be opened is not evidence.

    ``entity_id`` is a loose reference rather than a foreign key, because it
    points at five different tables depending on ``evidence_type``. The label
    and detail are denormalised copies taken at match time, so a historical
    match still reads correctly after the underlying row is edited — which is
    the whole point of keeping history.
    """

    __tablename__ = "job_match_evidence"

    id: Mapped[uuid.UUID] = new_uuid_column()

    match_item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("job_match_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    evidence_type: Mapped[EvidenceType] = mapped_column(
        StrEnumType(EvidenceType, 20), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    label: Mapped[str] = mapped_column(String(300), nullable=False)
    """What to show: "Python", "Senior Engineer at Verdant", "Route planner"."""

    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The supporting sentence, where there is one — an achievement's text, a
    project's summary."""

    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    """Copied from the career row. What stops unverified data from silently
    carrying a strong match: the matcher reads this, and the user can see it."""

    relevance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    """0-100, for ordering. ``docs/05-ai-and-matching.md`` ranks project
    evidence by skill overlap, role relevance, recency, and depth; this is the
    result of that ranking, not a second opinion about the match."""

    __table_args__ = (
        CheckConstraint("relevance >= 0 AND relevance <= 100", name="relevance_range"),
        CheckConstraint("length(trim(label)) > 0", name="label_not_blank"),
        Index("ix_job_match_evidence_item_relevance", "match_item_id", "relevance"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<JobMatchEvidence {self.evidence_type} {self.label!r}>"
