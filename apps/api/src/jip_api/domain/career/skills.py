"""Canonical skills and the user's own skills.

Two entities, deliberately. ``Skill`` is a **global catalogue shared by every
user**; ``UserSkill`` is what a particular person claims. Without the shared
catalogue, "React" and "React.js" are different skills and Phase 6 matching
cannot compare a job requirement to a person's evidence
(``docs/05-ai-and-matching.md``: raw skill -> alias lookup -> canonical skill).

``Skill`` and ``SkillAlias`` are **not user-owned**. They carry no ``user_id``,
and ``owned()`` raises for them by design.
"""

from __future__ import annotations

import enum
import re
import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import (
    StrEnumType,
    TimestampMixin,
    UserOwnedMixin,
    new_uuid_column,
)
from jip_api.infrastructure.db.base import Base

_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")


def normalize_skill_name(raw: str) -> str:
    """Reduce a skill name to its matching key.

    Lowercases and strips separators so "React.js", "react js", and "React-JS"
    collapse to one key. ``+`` and ``#`` survive because dropping them would
    merge C, C++, and C# into the same skill.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip().replace(" ", "-")


class SkillCategory(enum.StrEnum):
    """Broad grouping, used for presentation and for weighting in matching."""

    LANGUAGE = "LANGUAGE"
    FRAMEWORK = "FRAMEWORK"
    DATABASE = "DATABASE"
    TOOL = "TOOL"
    PLATFORM = "PLATFORM"
    PRACTICE = "PRACTICE"
    DOMAIN = "DOMAIN"
    SOFT_SKILL = "SOFT_SKILL"
    OTHER = "OTHER"


class CandidateStatus(enum.StrEnum):
    """Where a proposed catalogue entry is in its review."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    """Reviewed and declined. Kept rather than deleted, because the queue is
    rebuilt from the postings each time and a deleted row simply comes back —
    "General-purpose programming language" would be re-proposed forever."""


class SkillCandidate(TimestampMixin, Base):
    """A technology a posting named that the catalogue could not resolve.

    DEV-062, candidate 2. `requirement_skills.py` refuses to let job postings
    write to the catalogue, for a good reason it states at length: the name came
    from a model reading someone else's prose, nobody reviews it, and there are
    as many requirements as there are postings. Letting that path create skills
    fills a table shared by every user with "Rust (advantageous)" and "RUST".

    That module also names what was missing — *"exactly what a later
    reviewed-candidate mechanism would read from"*. This is that mechanism. The
    posting still cannot write to the catalogue; it can only queue a proposal,
    and a person decides.

    **Global, like `Skill` itself.** No `user_id`, and `owned()` raises for it
    by design: the catalogue it feeds is shared, so one user accepting "Playwright"
    makes it resolvable for everyone. That is the point rather than a leak — no
    profile data crosses, only the name a public posting used.
    """

    __tablename__ = "skill_candidates"

    id: Mapped[uuid.UUID] = new_uuid_column()

    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    """The matching key, so the same technology spelled two ways queues once."""

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    """As a posting wrote it, for the reviewer to recognise."""

    occurrences: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    """How many requirements name it. Recomputed on each refresh, and the
    reason the queue is ordered rather than alphabetical: a term six postings
    used is worth a decision before one that appeared once."""

    status: Mapped[CandidateStatus] = mapped_column(
        StrEnumType(CandidateStatus, 20), nullable=False
    )
    """`StrEnumType`, not a bare `String`, so the annotation is true.

    The other enum columns in this module are declared `String(20)` and read
    back as `str`, which makes `value is CandidateStatus.PENDING` false for a
    row that is pending — identity against a member of a `StrEnum` fails even
    when equality holds. That cost a debugging cycle here before this column was
    changed. The existing columns are left alone: correcting them changes what
    `category` and `source` return at runtime, which is a wider change than this
    one and belongs on its own.
    """

    resolved_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """What a human decided this means, once ACCEPTED.

    `SET NULL` rather than CASCADE: deleting a canonical skill should not erase
    the record that somebody reviewed this name, only the conclusion they
    reached.
    """

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why it was rejected, or why the mapping is what it is. Free text, because
    the useful reasons are unforeseeable — "this is a protocol, not a skill" and
    "the posting meant the other Transformers" are both worth keeping."""

    __table_args__ = (
        CheckConstraint(
            "(status = 'ACCEPTED' AND resolved_skill_id IS NOT NULL) OR status <> 'ACCEPTED'",
            name="accepted_names_a_skill",
        ),
    )
    """An accepted candidate that resolves to nothing is the state this whole
    mechanism exists to prevent: a name marked reviewed that still matches
    nothing, and will never be looked at again."""


class Proficiency(enum.StrEnum):
    """How well the user judges they know a skill."""

    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class SkillSource(enum.StrEnum):
    """Where a claimed skill came from.

    Recorded so a later phase can tell what a human typed from what a parser
    proposed, without inferring it from timestamps.
    """

    MANUAL = "MANUAL"
    RESUME_IMPORT = "RESUME_IMPORT"
    AI_INFERRED = "AI_INFERRED"


class Skill(TimestampMixin, Base):
    """A canonical skill, shared across all users. Never user-owned."""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = new_uuid_column()

    canonical_name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    category: Mapped[SkillCategory] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("length(trim(canonical_name)) > 0", name="canonical_name_not_blank"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Skill {self.canonical_name!r}>"


class SkillAlias(TimestampMixin, Base):
    """A variant spelling that resolves to a canonical skill. Never user-owned."""

    __tablename__ = "skill_aliases"

    id: Mapped[uuid.UUID] = new_uuid_column()
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SkillAlias {self.alias!r}>"


class EvidenceSource(enum.StrEnum):
    """Where a claim about a skill comes from.

    The six ``docs/03-domain-model.md`` names for ``SkillEvidence``. Two of them
    are structural and derived rather than stored — a skill linked to a role or
    a project already has a row in ``experience_skills`` or ``project_skills``,
    and duplicating that here would give the same fact two places to disagree.
    They are in the enum because a caller reading evidence should see one list,
    not two.
    """

    MANUAL = "MANUAL"
    """The user said so, in their own words. The one source with nothing behind
    it but the sentence they wrote, and the reason this table exists: before it,
    a skill could only be demonstrated by a role or a project, so anything
    learned outside employment could be claimed and never evidenced."""

    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"
    """Waiting on DEV-052. Certifications have no entity yet, so nothing can
    write this value; it is here so the enum matches the specification rather
    than the current state of the schema."""

    RESUME = "RESUME"
    EXPERIENCE = "EXPERIENCE"
    PROJECT = "PROJECT"


class SkillEvidence(TimestampMixin, UserOwnedMixin, Base):
    """Why the user says they have a skill.

    DEV-054. ``docs/03-domain-model.md`` lists this in the MVP schema and it was
    never built: evidence existed only as a dataclass assembled in memory during
    a match, from the two join tables, and discarded afterwards. Four of the six
    sources it names had nowhere to live, and **manual evidence** — the one the
    specification is most explicit about — had no substitute at all.

    Not a replacement for ``experience_skills`` and ``project_skills``. Those
    stay where they are; a skill used in a role is a property of the role. This
    holds what those cannot express, and the profile snapshot unions the two.

    Naming: the matcher has an unrelated dataclass also called ``SkillEvidence``
    — the in-memory view of a held skill, which this table now feeds. Both keep
    the name they earned. They live in different layers and the collision is
    visible at any import that needs both.
    """

    __tablename__ = "skill_evidence"

    id: Mapped[uuid.UUID] = new_uuid_column()
    user_skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Cascades: evidence for a skill nobody claims any more is not evidence of
    anything."""

    source: Mapped[EvidenceSource] = mapped_column(String(20), nullable=False)

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    """The row this points at, for the sources that have one.

    Deliberately not a foreign key. It addresses five different tables
    depending on ``source``, and the alternative — five nullable columns with a
    check constraint keeping four of them empty — describes the same thing
    less clearly. ``ResumeItem.source_entity_id`` already made this trade.

    Null for MANUAL, which points at nothing but its own note.
    """

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The user's own words. Required for MANUAL and optional elsewhere, where
    it annotates a link rather than being the whole of it."""

    __table_args__ = (
        CheckConstraint(
            "(source = 'MANUAL' AND entity_id IS NULL AND note IS NOT NULL "
            "AND length(trim(note)) > 0) OR (source <> 'MANUAL' AND entity_id IS NOT NULL)",
            name="evidence_has_a_source",
        ),
        # Manual evidence with an empty note is a claim with nothing behind it,
        # which is the thing this table exists to prevent. Enforced in the
        # database rather than only in the service, because the rule is about
        # what the row *means* and not about who wrote it.
        UniqueConstraint(
            "user_skill_id", "source", "entity_id", name="uq_skill_evidence_skill_source_entity"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SkillEvidence skill={self.user_skill_id} source={self.source}>"


class UserSkill(TimestampMixin, UserOwnedMixin, Base):
    """A skill the user claims, pointing at a canonical skill."""

    __tablename__ = "user_skills"

    id: Mapped[uuid.UUID] = new_uuid_column()
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    proficiency: Mapped[Proficiency | None] = mapped_column(String(20), nullable=True)

    years_of_experience: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_used_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """Recency matters as much as depth: a skill last used eight years ago is a
    weaker signal than the same proficiency used last month."""

    confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """0-100. How sure the *system* is, distinct from how good the user says
    they are. Left null for manual entries, where there is nothing to infer."""

    source: Mapped[SkillSource] = mapped_column(String(20), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # One claim per skill per user. Without it, "Python" added twice from
        # two sources double-counts in every future match calculation.
        UniqueConstraint("user_id", "skill_id", name="uq_user_skills_user_skill"),
        CheckConstraint(
            "years_of_experience IS NULL OR "
            "(years_of_experience >= 0 AND years_of_experience <= 80)",
            name="years_range",
        ),
        CheckConstraint(
            "last_used_year IS NULL OR (last_used_year >= 1950 AND last_used_year <= 2200)",
            name="last_used_year_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 100)", name="confidence_range"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UserSkill user={self.user_id} skill={self.skill_id}>"
