"""Loading the career profile into something the matcher can query.

One pass over the database, then everything else is in memory. The alternative
— querying per requirement — would issue a hundred round trips for a posting
with a hundred requirements, and would make the matcher untestable without a
database.

The snapshot is also where the **profile fingerprint** comes from. There is no
``CareerProfile.version`` column, and adding one would mean every write path in
the career domain remembering to bump it; a hash computed from the data itself
cannot be forgotten, and it changes for exactly the edits that could change a
match.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.ownership import owned
from jip_api.domain.career.history import (
    Education,
    Experience,
    ExperienceAchievement,
    ExperienceSkill,
    Project,
    ProjectSkill,
)
from jip_api.domain.career.models import CareerProfile, VerificationStatus
from jip_api.domain.career.skills import Skill, SkillAlias, UserSkill, normalize_skill_name


class ProfileFacts(Protocol):
    """The two profile fields the matcher reads.

    Structural, for the same reason :class:`MatchableRequirement` is: the
    matcher must stay runnable without a database, and naming the ORM class
    here would make that a matter of discipline rather than of type.
    """

    @property
    def years_of_experience(self) -> int | None: ...

    @property
    def current_location(self) -> str | None: ...


STRONG_VERIFICATION = {VerificationStatus.USER_CONFIRMED, VerificationStatus.EVIDENCE_BACKED}
"""Statuses that may carry a STRONG_MATCH.

The goal is explicit that inferred or unverified profile information must never
be strong evidence. An AI-inferred skill the user has not confirmed is still
evidence — it is shown, and it can support a PARTIAL_MATCH — but it cannot be
the reason we tell someone they are a strong fit.
"""


@dataclass(frozen=True, slots=True)
class SkillEvidence:
    """One canonical skill the user claims, and how well."""

    user_skill_id: uuid.UUID
    skill_id: uuid.UUID
    canonical_name: str
    normalized_name: str
    proficiency: str | None
    years_of_experience: int | None
    last_used_year: int | None
    verification_status: str

    experience_ids: tuple[uuid.UUID, ...] = ()
    project_ids: tuple[uuid.UUID, ...] = ()
    """Where the skill is actually demonstrated. A skill backed by two roles is
    stronger evidence than the same skill sitting alone on a list, which is the
    distinction ``docs/03-domain-model.md`` built ``ProjectSkill`` and
    ``ExperienceSkill`` to preserve."""

    @property
    def is_strongly_verified(self) -> bool:
        return self.verification_status in STRONG_VERIFICATION

    @property
    def demonstration_count(self) -> int:
        return len(self.experience_ids) + len(self.project_ids)


@dataclass(frozen=True, slots=True)
class ExperienceEvidence:
    """A role the user has held."""

    id: uuid.UUID
    company: str
    title: str
    normalized_title: str
    start_date: dt.date | None
    end_date: dt.date | None
    is_current: bool
    description: str | None
    verification_status: str
    achievements: tuple[tuple[uuid.UUID, str, str], ...] = ()
    """``(id, text, verification_status)``. Cited individually, because
    ``docs/06-resume-engine.md`` treats an achievement as a reusable statement
    rather than part of a blob."""

    @property
    def months(self) -> int:
        """Duration in months, 0 when the dates do not support a calculation."""
        if self.start_date is None:
            return 0
        end = self.end_date or (dt.date.today() if self.is_current else None)
        if end is None or end < self.start_date:
            return 0
        return (end.year - self.start_date.year) * 12 + (end.month - self.start_date.month)


@dataclass(frozen=True, slots=True)
class ProjectEvidence:
    """Something the user built."""

    id: uuid.UUID
    name: str
    summary: str | None
    description: str | None
    start_date: dt.date | None
    end_date: dt.date | None
    has_repository: bool
    verification_status: str
    skill_ids: frozenset[uuid.UUID] = frozenset()

    @property
    def depth_signal(self) -> int:
        """0-100, how substantial this project looks.

        ``docs/05-ai-and-matching.md`` ranks project evidence by skill overlap,
        role relevance, capability overlap, recency, and depth. Overlap and
        recency are computed against the requirement at match time; this is the
        part that depends only on the project — a described project with a
        public repository is better evidence than a name on a list.
        """
        score = 30
        if self.description:
            score += 25
        if self.summary:
            score += 10
        if self.has_repository:
            score += 20
        if len(self.skill_ids) >= 3:
            score += 15
        return min(score, 100)


@dataclass(frozen=True, slots=True)
class EducationEvidence:
    """A qualification."""

    id: uuid.UUID
    institution: str
    degree: str | None
    field_of_study: str | None
    end_date: dt.date | None
    is_current: bool
    searchable: str
    """Institution, degree, and field lowercased into one string, so a
    requirement mentioning "computer science" can be looked for once."""


@dataclass(slots=True)
class ProfileSnapshot:
    """Everything the matcher is allowed to reason from.

    Nothing inferred, nothing derived from a job, nothing from another user.
    If a fact is not in here, the matcher cannot cite it — which is what makes
    "evidence may come only from verified career profile data" enforceable
    rather than a convention.
    """

    user_id: uuid.UUID
    profile: ProfileFacts | None
    skills: list[SkillEvidence] = field(default_factory=list)
    experiences: list[ExperienceEvidence] = field(default_factory=list)
    projects: list[ProjectEvidence] = field(default_factory=list)
    education: list[EducationEvidence] = field(default_factory=list)

    skills_by_id: dict[uuid.UUID, SkillEvidence] = field(default_factory=dict)
    skills_by_normalized: dict[str, SkillEvidence] = field(default_factory=dict)
    alias_to_skill_id: dict[str, uuid.UUID] = field(default_factory=dict)
    """Every alias of every skill the user holds. The alias half of
    ``docs/05-ai-and-matching.md``'s raw → alias → canonical chain, resolved
    once rather than per requirement."""

    @property
    def is_empty(self) -> bool:
        """Whether there is anything at all to match against.

        Drives NO_EVIDENCE rather than GAP: with nothing on file, every absence
        is a fact about our data rather than about the candidate.
        """
        return not (self.skills or self.experiences or self.projects or self.education)

    @property
    def total_months(self) -> int:
        """Total professional months across roles.

        Overlapping roles are counted once each, which slightly overstates
        someone who held two jobs at the same time. Accepted deliberately: the
        alternative is an interval-merge whose result nobody can check against
        their own CV, and years are never used as a binary threshold anyway.
        """
        return sum(experience.months for experience in self.experiences)

    @property
    def stated_years(self) -> int | None:
        """What the user says, when they have said it. Preferred over the
        computed total, because they know about the gaps and the freelancing."""
        return self.profile.years_of_experience if self.profile else None

    def held_skill_names(self) -> list[str]:
        """Canonical names, sorted. Sorted so transferability ties break the
        same way on every run."""
        return sorted(skill.canonical_name for skill in self.skills)

    def find_skill(self, *, skill_id: uuid.UUID | None, name: str | None) -> SkillEvidence | None:
        """Resolve a requirement's skill against what the user holds.

        In the documented order: the canonical id first, then the normalized
        name, then the user's aliases. The id is tried first because Phase 5
        already resolved it through the same catalogue — when it is present it
        is the authoritative answer, and falling through to string comparison
        could only disagree with it.
        """
        if skill_id is not None:
            held = self.skills_by_id.get(skill_id)
            if held is not None:
                return held

        if not name:
            return None

        key = normalize_skill_name(name)
        if not key:
            return None

        direct = self.skills_by_normalized.get(key)
        if direct is not None:
            return direct

        aliased = self.alias_to_skill_id.get(key)
        return self.skills_by_id.get(aliased) if aliased else None

    def fingerprint(self) -> str:
        """A hash over everything a match could depend on.

        Includes ids and the fields the matcher reads, so editing a
        proficiency changes it and editing a phone number does not. Sorted
        before hashing, because a set iterating in a different order must not
        look like an edit.
        """
        parts: list[str] = []

        for skill in sorted(self.skills, key=lambda s: str(s.skill_id)):
            parts.append(
                f"s:{skill.skill_id}:{skill.proficiency}:{skill.years_of_experience}"
                f":{skill.last_used_year}:{skill.verification_status}"
                f":{sorted(str(i) for i in skill.experience_ids)}"
                f":{sorted(str(i) for i in skill.project_ids)}"
            )

        for experience in sorted(self.experiences, key=lambda e: str(e.id)):
            achievements = sorted(f"{a[0]}:{a[1]}" for a in experience.achievements)
            parts.append(
                f"x:{experience.id}:{experience.title}:{experience.company}"
                f":{experience.start_date}:{experience.end_date}:{experience.is_current}"
                f":{experience.description}:{experience.verification_status}:{achievements}"
            )

        for project in sorted(self.projects, key=lambda p: str(p.id)):
            parts.append(
                f"p:{project.id}:{project.name}:{project.summary}:{project.description}"
                f":{project.has_repository}:{project.verification_status}"
                f":{sorted(str(i) for i in project.skill_ids)}"
            )

        for education in sorted(self.education, key=lambda e: str(e.id)):
            parts.append(f"e:{education.id}:{education.searchable}:{education.end_date}")

        parts.append(f"y:{self.stated_years}")
        parts.append(f"l:{self.profile.current_location if self.profile else None}")

        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def load_profile_snapshot(session: Session, user_id: uuid.UUID) -> ProfileSnapshot:
    """Read everything the matcher may use, in a handful of queries."""
    profile = session.execute(
        select(CareerProfile).where(CareerProfile.user_id == user_id)
    ).scalar_one_or_none()

    snapshot = ProfileSnapshot(user_id=user_id, profile=profile)

    _load_skills(session, user_id, snapshot)
    _load_experiences(session, user_id, snapshot)
    _load_projects(session, user_id, snapshot)
    _load_education(session, user_id, snapshot)

    return snapshot


def _load_skills(session: Session, user_id: uuid.UUID, snapshot: ProfileSnapshot) -> None:
    rows = session.execute(
        owned(UserSkill, user_id).join(Skill, Skill.id == UserSkill.skill_id).add_columns(Skill)
    ).all()

    experience_links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for experience_id, skill_id in session.execute(
        select(ExperienceSkill.experience_id, ExperienceSkill.skill_id)
        .join(Experience, Experience.id == ExperienceSkill.experience_id)
        .where(Experience.user_id == user_id)
    ):
        experience_links.setdefault(skill_id, []).append(experience_id)

    project_links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for project_id, skill_id in session.execute(
        select(ProjectSkill.project_id, ProjectSkill.skill_id)
        .join(Project, Project.id == ProjectSkill.project_id)
        .where(Project.user_id == user_id)
    ):
        project_links.setdefault(skill_id, []).append(project_id)

    for user_skill, skill in rows:
        evidence = SkillEvidence(
            user_skill_id=user_skill.id,
            skill_id=skill.id,
            canonical_name=skill.canonical_name,
            normalized_name=skill.normalized_name,
            proficiency=str(user_skill.proficiency) if user_skill.proficiency else None,
            years_of_experience=user_skill.years_of_experience,
            last_used_year=user_skill.last_used_year,
            verification_status=str(user_skill.verification_status),
            experience_ids=tuple(sorted(experience_links.get(skill.id, []), key=str)),
            project_ids=tuple(sorted(project_links.get(skill.id, []), key=str)),
        )
        snapshot.skills.append(evidence)
        snapshot.skills_by_id[skill.id] = evidence
        snapshot.skills_by_normalized[skill.normalized_name] = evidence

    if snapshot.skills_by_id:
        for normalized_alias, skill_id in session.execute(
            select(SkillAlias.normalized_alias, SkillAlias.skill_id).where(
                SkillAlias.skill_id.in_(snapshot.skills_by_id)
            )
        ):
            snapshot.alias_to_skill_id[normalized_alias] = skill_id


def _load_experiences(session: Session, user_id: uuid.UUID, snapshot: ProfileSnapshot) -> None:
    experiences = list(session.execute(owned(Experience, user_id)).scalars())
    if not experiences:
        return

    achievements: dict[uuid.UUID, list[tuple[uuid.UUID, str, str]]] = {}
    for achievement in session.execute(
        select(ExperienceAchievement)
        .where(ExperienceAchievement.experience_id.in_([e.id for e in experiences]))
        .order_by(ExperienceAchievement.display_order, ExperienceAchievement.id)
    ).scalars():
        achievements.setdefault(achievement.experience_id, []).append(
            (achievement.id, achievement.text, str(achievement.verification_status))
        )

    for experience in experiences:
        snapshot.experiences.append(
            ExperienceEvidence(
                id=experience.id,
                company=experience.company,
                title=experience.title,
                normalized_title=experience.title.casefold(),
                start_date=experience.start_date,
                end_date=experience.end_date,
                is_current=experience.is_current,
                description=experience.description,
                verification_status=str(experience.verification_status),
                achievements=tuple(achievements.get(experience.id, [])),
            )
        )


def _load_projects(session: Session, user_id: uuid.UUID, snapshot: ProfileSnapshot) -> None:
    projects = list(session.execute(owned(Project, user_id)).scalars())
    if not projects:
        return

    skills: dict[uuid.UUID, set[uuid.UUID]] = {}
    for project_id, skill_id in session.execute(
        select(ProjectSkill.project_id, ProjectSkill.skill_id).where(
            ProjectSkill.project_id.in_([p.id for p in projects])
        )
    ):
        skills.setdefault(project_id, set()).add(skill_id)

    for project in projects:
        snapshot.projects.append(
            ProjectEvidence(
                id=project.id,
                name=project.name,
                summary=project.summary,
                description=project.description,
                start_date=project.start_date,
                end_date=project.end_date,
                has_repository=bool(project.repository_url),
                verification_status=str(project.verification_status),
                skill_ids=frozenset(skills.get(project.id, set())),
            )
        )


def _load_education(session: Session, user_id: uuid.UUID, snapshot: ProfileSnapshot) -> None:
    for education in session.execute(owned(Education, user_id)).scalars():
        searchable = " ".join(
            part
            for part in (education.institution, education.degree, education.field_of_study)
            if part
        ).casefold()
        snapshot.education.append(
            EducationEvidence(
                id=education.id,
                institution=education.institution,
                degree=education.degree,
                field_of_study=education.field_of_study,
                end_date=education.end_date,
                is_current=education.is_current,
                searchable=searchable,
            )
        )
