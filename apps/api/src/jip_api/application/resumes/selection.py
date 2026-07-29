"""Choosing what goes on a tailored resume, deterministically.

``docs/06-resume-engine.md`` states the objective:

> Maximize relevant, truthful evidence within limited resume space.

and gives the criteria — requirement coverage, skill relevance, role relevance,
evidence strength, uniqueness, value per line. This module is those criteria as
arithmetic. No model call: ``JobMatchEvidence`` already points at the exact
career rows behind every verdict, so "which of my achievements matter for this
job" is a query.

Two rules constrain everything here:

- **Only strongly verified facts are selected automatically.** The gate is the
  existing ``STRONG_VERIFICATION`` from the matcher, imported rather than
  restated, so there is one definition of "verified enough" in the codebase.
- **Nothing is invented.** Selection reorders and omits; it never writes a
  sentence. The words that reach the page are the user's own until slice 4
  proposes a rewrite, and even then the user approves it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.matching.evidence import (
    STRONG_VERIFICATION,
    ProfileSnapshot,
    load_profile_snapshot,
)
from jip_api.domain.matching.models import (
    JobMatch,
    JobMatchEvidence,
    JobMatchItem,
    MatchStatus,
)
from jip_api.domain.resumes.models import ResumeItemSource, ResumeSectionKind

logger = logging.getLogger(__name__)

MAX_EXPERIENCE_BULLETS = 4
MAX_PROJECTS = 3
MAX_SKILLS = 14
"""MVP shape from ``docs/06-resume-engine.md``: one page preferred, two allowed.

Caps rather than a layout engine. ``docs/06`` says not to solve overflow by
shrinking text, and the honest way to respect that here is to select less —
so the ranking decides what survives rather than the renderer deciding what to
squeeze.
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One career fact that could go on the page, with why it earned its place."""

    source_type: ResumeItemSource
    entity_id: uuid.UUID
    text: str
    heading: str | None
    score: int
    reasons: tuple[str, ...]
    verification_status: str

    @property
    def is_strongly_verified(self) -> bool:
        return self.verification_status in STRONG_VERIFICATION


@dataclass(slots=True)
class SelectionResult:
    """What selection chose, and what it deliberately left out."""

    skills: list[Candidate] = field(default_factory=list)
    experience: list[Candidate] = field(default_factory=list)
    projects: list[Candidate] = field(default_factory=list)
    education: list[Candidate] = field(default_factory=list)
    excluded_unverified: list[Candidate] = field(default_factory=list)
    """Relevant, but not confirmed by the user.

    Kept and surfaced rather than dropped silently. ``docs/06-resume-engine.md``
    distinguishes a *career* gap from a *resume* gap, and this list is the
    second kind: the evidence exists, it is simply not usable automatically
    until the user confirms it. Telling them is more useful than hiding it.
    """

    @property
    def all_selected(self) -> list[Candidate]:
        return [*self.skills, *self.experience, *self.projects, *self.education]


def select_for_match(
    session: Session,
    user_id: uuid.UUID,
    match: JobMatch,
    *,
    snapshot: ProfileSnapshot | None = None,
) -> SelectionResult:
    """Rank the user's career facts by how much this job's match relies on them.

    Reads the match rather than recomputing anything. Nothing here writes to
    ``job_matches``, ``job_match_items``, or ``job_match_evidence`` — the
    matching engine stays deterministic and this is a consumer of it.
    """
    profile = snapshot if snapshot is not None else load_profile_snapshot(session, user_id)

    items = list(
        session.execute(select(JobMatchItem).where(JobMatchItem.match_id == match.id)).scalars()
    )
    evidence_by_item = _evidence_by_item(session, [item.id for item in items])

    # entity id -> the best case that can be made for it, accumulated across
    # every requirement it helped satisfy. A skill that answers three
    # requirements is stronger evidence than one that answers a single
    # preference, which is what "requirement coverage" means in docs/06.
    weights: dict[uuid.UUID, int] = {}
    reasons: dict[uuid.UUID, list[str]] = {}

    for item in items:
        contribution = _contribution(item)
        if contribution <= 0:
            continue
        for ref in evidence_by_item.get(item.id, []):
            weights[ref.entity_id] = weights.get(ref.entity_id, 0) + contribution
            bucket = reasons.setdefault(ref.entity_id, [])
            if len(bucket) < 3:
                bucket.append(item.explanation)

    result = SelectionResult()
    _add_skills(result, profile, weights, reasons)
    _add_experience(result, profile, weights, reasons)
    _add_projects(result, profile, weights, reasons)
    _add_education(result, profile, weights, reasons)

    logger.info(
        "Selected resume content",
        # Never the text itself: docs/11-engineering-standards.md forbids
        # logging resume content.
        extra={
            "match_id": str(match.id),
            "selected": len(result.all_selected),
            "withheld_unverified": len(result.excluded_unverified),
        },
    )
    return result


def _contribution(item: JobMatchItem) -> int:
    """How much a requirement's verdict argues for the evidence behind it.

    Weighted by the requirement's own importance, so evidence that satisfies a
    core requirement outranks evidence that satisfies a preference — "value per
    line", in the document's terms. A transferable match counts, but less: it
    is real evidence for a related thing rather than the thing itself.
    """
    if item.status is MatchStatus.STRONG_MATCH:
        base = 100
    elif item.status is MatchStatus.MATCH:
        base = 80
    elif item.status is MatchStatus.PARTIAL_MATCH:
        base = 50
    elif item.status is MatchStatus.TRANSFERABLE_MATCH:
        base = 35
    else:
        return 0

    return int(base * float(item.weight))


def _evidence_by_item(
    session: Session, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[JobMatchEvidence]]:
    if not item_ids:
        return {}
    grouped: dict[uuid.UUID, list[JobMatchEvidence]] = {}
    for row in session.execute(
        select(JobMatchEvidence).where(JobMatchEvidence.match_item_id.in_(item_ids))
    ).scalars():
        grouped.setdefault(row.match_item_id, []).append(row)
    return grouped


def _place(result: SelectionResult, candidate: Candidate, bucket: list[Candidate]) -> None:
    """Put a candidate on the page, or explain why it cannot go there.

    The one gate that matters: ``docs/06-resume-engine.md`` allows only
    verified or explicitly confirmed facts into automatic resume claims. An
    unverified fact is not discarded — it is set aside and reported, because
    the user can confirm it and then it becomes usable.
    """
    if candidate.is_strongly_verified:
        bucket.append(candidate)
    else:
        result.excluded_unverified.append(candidate)


def _add_skills(
    result: SelectionResult,
    profile: ProfileSnapshot,
    weights: dict[uuid.UUID, int],
    reasons: dict[uuid.UUID, list[str]],
) -> None:
    """Skills the job actually asked for, strongest first.

    ``docs/06``: only verified skills, ordered by relevance and evidence
    strength. Demonstration is part of strength — a skill used in a real role
    outranks the same skill sitting alone on a list.
    """
    candidates: list[Candidate] = []
    for skill in profile.skills:
        weight = weights.get(skill.user_skill_id, 0)
        if weight <= 0:
            continue
        candidates.append(
            Candidate(
                source_type=ResumeItemSource.SKILL,
                entity_id=skill.user_skill_id,
                text=skill.canonical_name,
                heading=None,
                score=weight + skill.demonstration_count * 25,
                reasons=tuple(reasons.get(skill.user_skill_id, [])),
                verification_status=skill.verification_status,
            )
        )

    for candidate in _ranked(candidates)[:MAX_SKILLS]:
        _place(result, candidate, result.skills)


def _add_experience(
    result: SelectionResult,
    profile: ProfileSnapshot,
    weights: dict[uuid.UUID, int],
    reasons: dict[uuid.UUID, list[str]],
) -> None:
    """Roles, and the achievements within them that this job cares about.

    Achievements are ranked individually rather than a role being taken whole.
    ``docs/06-resume-engine.md`` treats an achievement as a reusable statement
    precisely so tailoring can pick the two that matter for this posting and
    leave the three that do not.
    """
    for experience in profile.experiences:
        heading = f"{experience.title}, {experience.company}"

        relevant: list[Candidate] = []
        for achievement_id, text, verification in experience.achievements:
            weight = weights.get(achievement_id, 0)
            if weight <= 0:
                continue
            relevant.append(
                Candidate(
                    source_type=ResumeItemSource.ACHIEVEMENT,
                    entity_id=achievement_id,
                    text=text,
                    heading=heading,
                    score=weight,
                    reasons=tuple(reasons.get(achievement_id, [])),
                    verification_status=verification,
                )
            )

        role_weight = weights.get(experience.id, 0)
        if not relevant and role_weight <= 0:
            continue

        if relevant:
            for candidate in _ranked(relevant)[:MAX_EXPERIENCE_BULLETS]:
                _place(result, candidate, result.experience)
        elif experience.description:
            # The role is relevant but none of its bullets are, so the role's
            # own description carries it rather than the role vanishing.
            _place(
                result,
                Candidate(
                    source_type=ResumeItemSource.EXPERIENCE,
                    entity_id=experience.id,
                    text=experience.description,
                    heading=heading,
                    score=role_weight,
                    reasons=tuple(reasons.get(experience.id, [])),
                    verification_status=experience.verification_status,
                ),
                result.experience,
            )


def _add_projects(
    result: SelectionResult,
    profile: ProfileSnapshot,
    weights: dict[uuid.UUID, int],
    reasons: dict[uuid.UUID, list[str]],
) -> None:
    """Projects the job's requirements actually leaned on.

    ``docs/06-resume-engine.md`` is explicit that experience does not always
    outrank projects for junior users, so projects are ranked on the same scale
    as everything else rather than being appended after it. Depth breaks ties —
    a described project with a repository is better evidence than a name.
    """
    candidates: list[Candidate] = []
    for project in profile.projects:
        weight = weights.get(project.id, 0)
        if weight <= 0:
            continue
        candidates.append(
            Candidate(
                source_type=ResumeItemSource.PROJECT,
                entity_id=project.id,
                text=project.summary or project.description or project.name,
                heading=project.name,
                score=weight + project.depth_signal,
                reasons=tuple(reasons.get(project.id, [])),
                verification_status=project.verification_status,
            )
        )

    for candidate in _ranked(candidates)[:MAX_PROJECTS]:
        _place(result, candidate, result.projects)


def _add_education(
    result: SelectionResult,
    profile: ProfileSnapshot,
    weights: dict[uuid.UUID, int],
    reasons: dict[uuid.UUID, list[str]],
) -> None:
    """Education, kept whether or not the posting asked.

    The one section not gated on relevance: a resume without education reads as
    an omission, and the cost of a line is small. Ordered by relevance anyway,
    so a degree the job named comes first.
    """
    candidates: list[Candidate] = []
    for education in profile.education:
        label = " — ".join(
            part
            for part in (education.degree or education.institution, education.field_of_study)
            if part
        )
        candidates.append(
            Candidate(
                source_type=ResumeItemSource.EDUCATION,
                entity_id=education.id,
                text=label or education.institution,
                heading=education.institution,
                score=weights.get(education.id, 0),
                reasons=tuple(reasons.get(education.id, [])),
                # Education is typed in by the user; there is no inference path
                # that could make it anything else.
                verification_status="USER_CONFIRMED",
            )
        )

    for candidate in _ranked(candidates):
        _place(result, candidate, result.education)


def _ranked(candidates: list[Candidate]) -> list[Candidate]:
    """Highest score first, ties broken by text.

    The tiebreak is what makes selection reproducible: two facts of equal
    relevance must not swap places between runs, or the same profile and the
    same job would produce two different resumes.
    """
    return sorted(candidates, key=lambda c: (-c.score, c.text, str(c.entity_id)))


def to_sections(result: SelectionResult) -> list[tuple[ResumeSectionKind, list[Candidate]]]:
    """Lay the selection out in the order a resume reads.

    Skills first because a recruiter scans for them; experience next because it
    carries the most weight; projects and education after. Empty sections are
    dropped rather than rendered as headings with nothing under them.
    """
    layout = [
        (ResumeSectionKind.SKILLS, result.skills),
        (ResumeSectionKind.EXPERIENCE, result.experience),
        (ResumeSectionKind.PROJECTS, result.projects),
        (ResumeSectionKind.EDUCATION, result.education),
    ]
    return [(kind, items) for kind, items in layout if items]
