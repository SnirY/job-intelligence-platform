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

from jip_api.domain.common import TimestampMixin, UserOwnedMixin, new_uuid_column
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
