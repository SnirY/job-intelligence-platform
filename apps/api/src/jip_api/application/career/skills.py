"""Skill use cases.

The interesting part is resolution: a user types "React.js" and must end up
pointing at the same canonical skill as someone who typed "react". Everything
downstream — matching, gap analysis, resume skill sections — depends on that
collapsing correctly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jip_api.application.errors import DuplicateResourceError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.domain.career.models import VerificationStatus
from jip_api.domain.career.skills import (
    Proficiency,
    Skill,
    SkillAlias,
    SkillCategory,
    SkillSource,
    UserSkill,
    normalize_skill_name,
)

logger = logging.getLogger(__name__)

_UNSET = object()


@dataclass(slots=True)
class UserSkillInput:
    """What the caller supplies to claim a skill."""

    name: str
    category: SkillCategory = SkillCategory.OTHER
    proficiency: Proficiency | None = None
    years_of_experience: int | None = None
    last_used_year: int | None = None
    notes: str | None = None
    source: SkillSource = SkillSource.MANUAL


@dataclass(slots=True)
class UserSkillUpdate:
    """Partial update. Unset fields are left alone; ``None`` clears them."""

    proficiency: Any = field(default=_UNSET)
    years_of_experience: Any = field(default=_UNSET)
    last_used_year: Any = field(default=_UNSET)
    notes: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("proficiency", self.proficiency),
                ("years_of_experience", self.years_of_experience),
                ("last_used_year", self.last_used_year),
                ("notes", self.notes),
            )
            if value is not _UNSET
        }


def resolve_skill(session: Session, name: str, category: SkillCategory) -> Skill:
    """Find or create the canonical skill for ``name``.

    Order matters: an alias is checked before creating anything, so "React.js"
    resolves to the existing React rather than minting a near-duplicate that
    would then be a different skill for matching purposes.

    The catalogue is global. It is queried with ``select()`` rather than
    ``owned()`` on purpose — scoping it by user would return nothing and
    silently create a private duplicate per person.
    """
    normalized = normalize_skill_name(name)
    if not normalized:
        raise ValueError("skill name is empty after normalization")

    existing = session.execute(
        select(Skill).where(Skill.normalized_name == normalized)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    aliased = session.execute(
        select(Skill)
        .join(SkillAlias, SkillAlias.skill_id == Skill.id)
        .where(SkillAlias.normalized_alias == normalized)
    ).scalar_one_or_none()
    if aliased is not None:
        return aliased

    statement = (
        pg_insert(Skill)
        .values(canonical_name=name.strip(), normalized_name=normalized, category=category)
        .on_conflict_do_nothing(index_elements=[Skill.normalized_name])
        .returning(Skill)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        logger.info("Created canonical skill", extra={"normalized_name": normalized})
        return created

    # Lost a race with a concurrent create; the winner's row is the canonical one.
    return session.execute(select(Skill).where(Skill.normalized_name == normalized)).scalar_one()


def list_user_skills(session: Session, user_id: uuid.UUID) -> list[tuple[UserSkill, Skill]]:
    """Return the user's skills with their canonical skill, alphabetically."""
    statement = (
        owned(UserSkill, user_id)
        .join(Skill, Skill.id == UserSkill.skill_id)
        .add_columns(Skill)
        .order_by(Skill.canonical_name)
    )
    return [(row[0], row[1]) for row in session.execute(statement)]


def get_user_skill(session: Session, user_id: uuid.UUID, skill_id: uuid.UUID) -> UserSkill:
    """Return one of the user's skills, or raise."""
    user_skill = session.execute(
        owned(UserSkill, user_id).where(UserSkill.id == skill_id)
    ).scalar_one_or_none()
    if user_skill is None:
        raise ResourceNotFoundError("Skill not found.")
    return user_skill


def add_user_skill(
    session: Session, user_id: uuid.UUID, data: UserSkillInput
) -> tuple[UserSkill, Skill]:
    """Claim a skill, resolving it to the canonical catalogue first.

    Returns the canonical skill alongside the claim so the caller does not
    have to resolve the same name a second time.
    """
    skill = resolve_skill(session, data.name, data.category)

    user_skill = UserSkill(
        user_id=user_id,
        skill_id=skill.id,
        proficiency=data.proficiency,
        years_of_experience=data.years_of_experience,
        last_used_year=data.last_used_year,
        notes=data.notes,
        source=data.source,
        # Typed by a person, so confirmed by definition. An AI-proposed skill
        # arrives through a different path and never lands as confirmed
        # (docs/05-ai-and-matching.md: AI must not control verified facts).
        verification_status=(
            VerificationStatus.USER_CONFIRMED
            if data.source is SkillSource.MANUAL
            else VerificationStatus.AI_INFERRED
        ),
    )
    session.add(user_skill)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateResourceError(f"{skill.canonical_name} is already in your skills.") from exc

    return user_skill, skill


def update_user_skill(
    session: Session, user_id: uuid.UUID, skill_id: uuid.UUID, update: UserSkillUpdate
) -> UserSkill:
    """Apply a partial update to one of the user's skills."""
    user_skill = get_user_skill(session, user_id, skill_id)
    for name, value in update.changes().items():
        setattr(user_skill, name, value)
    session.flush()
    return user_skill


def remove_user_skill(session: Session, user_id: uuid.UUID, skill_id: uuid.UUID) -> None:
    """Remove a skill claim.

    Deletes the claim, never the canonical skill: that row is shared, and
    removing it would take the skill away from every other user. The foreign key
    is RESTRICT so a stray delete fails loudly rather than cascading.
    """
    session.delete(get_user_skill(session, user_id, skill_id))
    session.flush()
