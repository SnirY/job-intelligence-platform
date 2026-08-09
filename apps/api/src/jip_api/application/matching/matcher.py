"""The deterministic matcher: one requirement in, one verdict out.

``docs/05-ai-and-matching.md`` gives the chain, and this module follows it in
order for every requirement:

```text
Exact Match -> Alias Match -> Evidence Retrieval -> Transferability Analysis
-> Match Classification -> Score -> Explanation
```

Semantic matching is absent from that list here, deliberately. It is the one
step that cannot be deterministic, so it lives outside this module as optional
enrichment that runs afterwards and can only *raise* a GAP to a transferable
match — never the reverse, and never into a direct match.

Nothing in this file touches the database, the clock, or a model. Given the
same snapshot and the same requirements it returns the same verdicts, which is
what the determinism test asserts.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from jip_api.application.matching.evidence import (
    ProfileSnapshot,
    SkillEvidence,
)
from jip_api.domain.jobs.analysis import (
    RequirementImportance,
    RequirementType,
)
from jip_api.domain.matching.models import EvidenceType, MatchCategory, MatchStatus
from jip_api.domain.matching.rules import can_block, category_for, score_for, weight_for
from jip_api.domain.matching.transferable import find_transfer

_WORD = re.compile(r"[a-z0-9+#.]+")

STALE_SKILL_YEARS = 6
"""How long since a skill was last used before it stops being a strong match.

``docs/03-domain-model.md``: recency matters as much as depth, and a skill last
used eight years ago is a weaker signal than the same proficiency used last
month. Six years is roughly two job changes.
"""

STRONG_PROFICIENCIES = {"ADVANCED", "EXPERT"}


class MatchableRequirement(Protocol):
    """What the matcher actually reads from a requirement.

    A Protocol rather than the ORM class, because the matcher must not need a
    database — that is the property the determinism tests rest on, and a
    signature naming :class:`JobRequirement` would quietly permit a lazy-loaded
    relationship to creep in later. This also documents the coupling exactly:
    six fields, all of them scalars Phase 5 already resolved.
    """

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def normalized_text(self) -> str: ...

    @property
    def requirement_type(self) -> str: ...

    @property
    def importance(self) -> str: ...

    @property
    def skill_id(self) -> uuid.UUID | None: ...

    @property
    def skill_name(self) -> str | None: ...

    @property
    def years_min(self) -> int | None: ...

    @property
    def source_order(self) -> int: ...


@dataclass(slots=True)
class EvidenceRef:
    """One career fact cited by a verdict."""

    evidence_type: EvidenceType
    entity_id: uuid.UUID
    label: str
    detail: str | None
    verification_status: str
    relevance: int


@dataclass(slots=True)
class Verdict:
    """The complete answer for one requirement."""

    requirement_id: uuid.UUID
    status: MatchStatus
    category: MatchCategory
    score: int
    weight: Decimal
    confidence: int
    explanation: str
    is_blocker: bool
    source_order: int
    evidence: list[EvidenceRef] = field(default_factory=list)

    @property
    def from_project(self) -> bool:
        """Whether a project carried this verdict. Feeds the PROJECTS category
        score, which measures how much of the alignment rests on things the
        user built rather than roles they held."""
        return any(ref.evidence_type is EvidenceType.PROJECT for ref in self.evidence)


def match_requirements(
    requirements: Sequence[MatchableRequirement], snapshot: ProfileSnapshot
) -> list[Verdict]:
    """Evaluate every requirement independently.

    Independently is the operative word: no requirement's verdict depends on
    another's, so a posting cannot drag its own score down by asking for
    something unusual, and the results can be read in any order.
    """
    return [_match_one(requirement, snapshot) for requirement in requirements]


def _match_one(requirement: MatchableRequirement, snapshot: ProfileSnapshot) -> Verdict:
    importance = RequirementImportance(requirement.importance)
    requirement_type = RequirementType(requirement.requirement_type)

    status, confidence, explanation, evidence = _evaluate(requirement, requirement_type, snapshot)

    # A core requirement with a real gap is the blocker case. NO_EVIDENCE never
    # blocks: we have nothing on file, which is a fact about our data rather
    # than about the candidate, and blocking on it would punish an empty
    # profile. UNKNOWN never blocks either — the goal says so outright.
    is_blocker = status is MatchStatus.GAP and can_block(importance)
    if is_blocker:
        status = MatchStatus.BLOCKER
        explanation = f"{explanation} This is listed as essential."

    return Verdict(
        requirement_id=requirement.id,
        status=status,
        category=category_for(requirement_type, importance),
        score=score_for(status),
        weight=weight_for(importance),
        confidence=confidence,
        explanation=explanation,
        is_blocker=is_blocker,
        source_order=requirement.source_order,
        evidence=evidence,
    )


def _evaluate(
    requirement: MatchableRequirement,
    requirement_type: RequirementType,
    snapshot: ProfileSnapshot,
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Dispatch to the rule for this requirement type."""
    if requirement_type is RequirementType.TECHNICAL_SKILL:
        return _match_skill(requirement, snapshot)
    if requirement_type is RequirementType.EXPERIENCE:
        return _match_experience(requirement, snapshot)
    if requirement_type is RequirementType.EDUCATION:
        return _match_education(requirement, snapshot)
    if requirement_type in {RequirementType.DOMAIN_KNOWLEDGE, RequirementType.SOFT_SKILL}:
        return _match_by_text(requirement, requirement_type, snapshot)
    if requirement_type in {
        RequirementType.WORK_AUTHORIZATION,
        RequirementType.LOCATION,
        RequirementType.LANGUAGE,
        RequirementType.OTHER,
    }:
        return _unassessable(requirement_type)

    return _unassessable(requirement_type)  # pragma: no cover - exhaustive above


# --- technical skills ---------------------------------------------------------


def _match_skill(
    requirement: MatchableRequirement, snapshot: ProfileSnapshot
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Exact, then alias, then demonstration, then transferability."""
    name = requirement.skill_name or requirement.normalized_text
    held = snapshot.find_skill(skill_id=requirement.skill_id, name=name)

    if held is not None:
        return _classify_held_skill(held, name, snapshot)

    if not snapshot.skills:
        return (
            MatchStatus.NO_EVIDENCE,
            30,
            f"There are no skills in your profile yet, so {name} could not be checked.",
            [],
        )

    transfer = find_transfer(name, snapshot.held_skill_names())
    if transfer is not None:
        held_name, group = transfer
        transferred = snapshot.skills_by_normalized.get(
            next(iter(s.normalized_name for s in snapshot.skills if s.canonical_name == held_name))
        )
        evidence = [_skill_evidence(transferred, group.strength)] if transferred else []
        return (
            MatchStatus.TRANSFERABLE_MATCH,
            group.strength,
            # Naming both sides and the group is what makes this checkable.
            # "Similar experience" would be an assertion; this is an argument
            # the user can disagree with.
            f"You have {held_name}, not {name}. Both are {group.label}, so the "
            f"experience should transfer — but it is not the same thing.",
            evidence,
        )

    return (
        MatchStatus.GAP,
        75,
        f"{name} is not in your profile.",
        [],
    )


def _classify_held_skill(
    held: SkillEvidence, requested: str, snapshot: ProfileSnapshot
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Turn a held skill into a status, weighing verification, demonstration,
    proficiency, and recency in that order of importance."""
    evidence = [_skill_evidence(held, 80)]
    evidence.extend(_demonstrations(held, snapshot))

    if not held.is_strongly_verified:
        # The goal's rule: inferred or unverified data is never strong evidence.
        # It is still evidence — dropping it would throw away a true fact — so
        # it lands at PARTIAL and says why.
        return (
            MatchStatus.PARTIAL_MATCH,
            45,
            f"{held.canonical_name} is in your profile but has not been confirmed, "
            "so it counts as partial evidence.",
            evidence,
        )

    stale = _is_stale(held)
    demonstrated = held.demonstration_count > 0
    proficient = (held.proficiency or "").upper() in STRONG_PROFICIENCIES

    if stale:
        return (
            MatchStatus.PARTIAL_MATCH,
            60,
            f"You have {held.canonical_name}, but last used it in "
            f"{held.last_used_year}, so it may need refreshing.",
            evidence,
        )

    if demonstrated and (proficient or (held.years_of_experience or 0) >= 3):
        where = "role" if held.experience_ids else "project"
        return (
            MatchStatus.STRONG_MATCH,
            90,
            f"You have {held.canonical_name} and have used it in at least one {where}.",
            evidence,
        )

    if demonstrated or proficient:
        return (
            MatchStatus.MATCH,
            75,
            f"{held.canonical_name} is in your confirmed skills.",
            evidence,
        )

    # Confirmed but never demonstrated and no stated proficiency. A real claim,
    # weaker than one backed by a role.
    return (
        MatchStatus.MATCH,
        60,
        f"{held.canonical_name} is in your confirmed skills, though nothing in your "
        "profile shows where you used it.",
        evidence,
    )


def _is_stale(held: SkillEvidence) -> bool:
    if held.last_used_year is None:
        return False
    # Compared against the most recent year the profile knows about rather than
    # today, so the same snapshot yields the same verdict whenever it is run.
    return held.last_used_year <= _reference_year(held) - STALE_SKILL_YEARS


def _reference_year(held: SkillEvidence) -> int:
    """The year staleness is measured from.

    Uses the skill's own last-used year plus its stated experience, which keeps
    the function pure — reading the clock here would mean a match recomputed
    next year silently disagreed with itself.
    """
    return (held.last_used_year or 0) + (held.years_of_experience or 0) + STALE_SKILL_YEARS - 1


def _skill_evidence(held: SkillEvidence, relevance: int) -> EvidenceRef:
    detail_parts = []
    if held.proficiency:
        detail_parts.append(held.proficiency.capitalize())
    if held.years_of_experience:
        detail_parts.append(f"{held.years_of_experience} years")
    if held.last_used_year:
        detail_parts.append(f"last used {held.last_used_year}")

    return EvidenceRef(
        evidence_type=EvidenceType.SKILL,
        entity_id=held.user_skill_id,
        label=held.canonical_name,
        detail=", ".join(detail_parts) or None,
        verification_status=held.verification_status,
        relevance=relevance,
    )


def _demonstrations(held: SkillEvidence, snapshot: ProfileSnapshot) -> list[EvidenceRef]:
    """The roles and projects where a skill was actually used.

    Sorted deterministically and capped: three citations answer "why do you
    think I match this", and thirty would bury the answer.
    """
    refs: list[EvidenceRef] = []

    by_id = {experience.id: experience for experience in snapshot.experiences}
    for experience_id in held.experience_ids:
        experience = by_id.get(experience_id)
        if experience is None:
            continue
        refs.append(
            EvidenceRef(
                evidence_type=EvidenceType.EXPERIENCE,
                entity_id=experience.id,
                label=f"{experience.title} at {experience.company}",
                detail=experience.description,
                verification_status=experience.verification_status,
                relevance=70,
            )
        )

    projects_by_id = {project.id: project for project in snapshot.projects}
    for project_id in held.project_ids:
        project = projects_by_id.get(project_id)
        if project is None:
            continue
        refs.append(
            EvidenceRef(
                evidence_type=EvidenceType.PROJECT,
                entity_id=project.id,
                label=project.name,
                detail=project.summary or project.description,
                verification_status=project.verification_status,
                relevance=project.depth_signal,
            )
        )

    refs.sort(key=lambda ref: (-ref.relevance, ref.label, str(ref.entity_id)))
    return refs[:3]


# --- experience ---------------------------------------------------------------


def _years_met_sentence(held_years: int, required_years: int) -> str:
    """Say that the years are covered, without inventing a demand.

    A posting whose minimum parses to zero — "0-3 years experience in
    object-oriented development", which is an invitation to juniors — used to
    render as *"You have 3 years against the 0 asked for."* Broken as a
    sentence, and empty as a claim: nobody asked for zero years.

    Only the wording changes. The verdict stays STRONG_MATCH and the confidence
    stays 85, deliberately: those are `MATCHING_ENGINE_VERSION`'s territory, and
    re-scoring on the way past a copy fix is the silent re-ranking that version
    exists to prevent.

    Whether a requirement demanding nothing should score 85 at all is a fair
    question and a different one. It belongs to DEV-011, with the rest of the
    values nobody has calibrated.
    """
    if required_years <= 0:
        return f"This asks for no minimum experience, and you have {held_years} years."
    return f"You have {held_years} years against the {required_years} asked for."


def _match_experience(
    requirement: MatchableRequirement, snapshot: ProfileSnapshot
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Years and kind of work.

    ``docs/05-ai-and-matching.md``: do not treat years as binary. Someone with
    four years against a five-year requirement is a partial match, not a gap,
    and strong project evidence can carry the same weight.
    """
    # Stated years count as evidence in their own right. A user who has filled
    # in "6 years" but not yet added the individual roles has told us something
    # real, and treating that as no evidence would penalise a half-filled
    # profile — which is the thing the goal forbids.
    if not snapshot.experiences and not snapshot.projects and snapshot.stated_years is None:
        return (
            MatchStatus.NO_EVIDENCE,
            30,
            "There is no work history in your profile yet, so this could not be checked.",
            [],
        )

    evidence = _experience_evidence(requirement, snapshot)
    required_years = requirement.years_min

    if required_years is None:
        # A kind of experience rather than a quantity. The evidence search
        # above already looked for it by keyword.
        if evidence:
            return (
                MatchStatus.MATCH,
                65,
                "Your work history covers this.",
                evidence,
            )
        return (
            MatchStatus.GAP,
            55,
            "Nothing in your work history matches this.",
            [],
        )

    held_years = snapshot.stated_years
    if held_years is None:
        held_years = snapshot.total_months // 12

    if held_years >= required_years:
        return (
            MatchStatus.STRONG_MATCH,
            85,
            _years_met_sentence(held_years, required_years),
            evidence,
        )

    if required_years and held_years >= required_years * 0.6:
        return (
            MatchStatus.PARTIAL_MATCH,
            70,
            f"You have {held_years} years against the {required_years} asked for — "
            "close, and years are rarely a hard cut-off.",
            evidence,
        )

    if held_years == 0:
        return (
            MatchStatus.NO_EVIDENCE,
            35,
            "Your profile does not say how many years you have, so this could not be checked.",
            evidence,
        )

    return (
        MatchStatus.GAP,
        70,
        f"This asks for {required_years} years and your profile shows {held_years}.",
        evidence,
    )


def _experience_evidence(
    requirement: MatchableRequirement, snapshot: ProfileSnapshot
) -> list[EvidenceRef]:
    """Roles, achievements, and projects whose words overlap the requirement."""
    terms = _terms(requirement.normalized_text)
    refs: list[EvidenceRef] = []

    for experience in snapshot.experiences:
        haystack = " ".join(
            part for part in (experience.title, experience.description) if part
        ).casefold()
        overlap = sum(1 for term in terms if term in haystack)
        if overlap:
            refs.append(
                EvidenceRef(
                    evidence_type=EvidenceType.EXPERIENCE,
                    entity_id=experience.id,
                    label=f"{experience.title} at {experience.company}",
                    detail=experience.description,
                    verification_status=experience.verification_status,
                    relevance=min(50 + overlap * 15, 100),
                )
            )

        for achievement_id, text, verification in experience.achievements:
            achievement_overlap = sum(1 for term in terms if term in text.casefold())
            if achievement_overlap:
                refs.append(
                    EvidenceRef(
                        evidence_type=EvidenceType.ACHIEVEMENT,
                        entity_id=achievement_id,
                        label=f"{experience.title} at {experience.company}",
                        detail=text,
                        verification_status=verification,
                        relevance=min(45 + achievement_overlap * 15, 100),
                    )
                )

    for project in snapshot.projects:
        haystack = " ".join(
            part for part in (project.name, project.summary, project.description) if part
        ).casefold()
        overlap = sum(1 for term in terms if term in haystack)
        if overlap:
            refs.append(
                EvidenceRef(
                    evidence_type=EvidenceType.PROJECT,
                    entity_id=project.id,
                    label=project.name,
                    detail=project.summary or project.description,
                    verification_status=project.verification_status,
                    relevance=min(project.depth_signal, 50 + overlap * 15),
                )
            )

    refs.sort(key=lambda ref: (-ref.relevance, ref.label, str(ref.entity_id)))
    return refs[:3]


# --- education ----------------------------------------------------------------


def _match_education(
    requirement: MatchableRequirement, snapshot: ProfileSnapshot
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    if not snapshot.education:
        return (
            MatchStatus.NO_EVIDENCE,
            30,
            "There is no education in your profile yet, so this could not be checked.",
            [],
        )

    terms = _terms(requirement.normalized_text)
    best: tuple[int, EvidenceRef] | None = None

    for education in snapshot.education:
        overlap = sum(1 for term in terms if term in education.searchable)
        if not overlap:
            continue
        ref = EvidenceRef(
            evidence_type=EvidenceType.EDUCATION,
            entity_id=education.id,
            label=" — ".join(
                part
                for part in (education.degree or education.institution, education.field_of_study)
                if part
            ),
            detail=education.institution,
            verification_status="USER_CONFIRMED",
            relevance=min(50 + overlap * 20, 100),
        )
        if best is None or overlap > best[0]:
            best = (overlap, ref)

    if best is not None:
        return (
            MatchStatus.MATCH,
            75,
            f"Your {best[1].label} covers this.",
            [best[1]],
        )

    # The user has education and none of it matches. A real gap — though a soft
    # one, since postings routinely list a degree they do not enforce.
    return (
        MatchStatus.GAP,
        55,
        "Your education does not appear to cover this.",
        [],
    )


# --- text-matched types -------------------------------------------------------


def _match_by_text(
    requirement: MatchableRequirement,
    requirement_type: RequirementType,
    snapshot: ProfileSnapshot,
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Domain knowledge and soft skills, found by keyword.

    Never better than PARTIAL_MATCH. A word appearing in a project description
    is weak evidence of domain knowledge, and calling it a strong match would
    put keyword overlap on the same footing as a confirmed, demonstrated skill.

    The same caution applies downward, and used not to. A keyword *missing* is
    weak evidence of absence, and only one of the two types this handles can
    carry a real gap:

    - **Domain knowledge** is the kind of thing a career profile records. Its
      absence is informative — a profile with no mention of telecom anywhere is
      genuine evidence about telecom.
    - **A soft skill** is not. Nothing in the profile is a place to put
      "analytical thinking", so failing to find the phrase says nothing about
      the person. Scoring that as a GAP made the strongest negative claim
      available on the weakest possible evidence, at whatever weight the
      posting's wording happened to earn — 2.00 apiece for three of them on the
      posting this was found on, 30% of the score, all of it noise.

    UNKNOWN instead, which is what this module already returns for everything
    else the profile has no field for — work authorisation, location, spoken
    languages. It still counts toward the score, at the constant that means we
    could not tell rather than at the zero that means we looked and it was not
    there.
    """
    if snapshot.is_empty:
        return (
            MatchStatus.NO_EVIDENCE,
            30,
            "There is nothing in your profile yet to check this against.",
            [],
        )

    evidence = _experience_evidence(requirement, snapshot)
    if evidence:
        return (
            MatchStatus.PARTIAL_MATCH,
            50,
            "Your profile mentions this, though not in a way that proves depth.",
            evidence,
        )

    if requirement_type is RequirementType.SOFT_SKILL:
        return (
            MatchStatus.UNKNOWN,
            20,
            "A profile has nowhere to record this, so it is not something we can check.",
            [],
        )

    return (
        MatchStatus.GAP,
        50,
        "Nothing in your profile mentions this.",
        [],
    )


# --- types we cannot assess ---------------------------------------------------


_UNASSESSABLE_REASONS = {
    RequirementType.WORK_AUTHORIZATION: (
        "Your profile does not record work authorisation, so this is for you to check."
    ),
    RequirementType.LOCATION: (
        "Location depends on what you are willing to do, which your profile does not record."
    ),
    RequirementType.LANGUAGE: (
        "Your profile does not record spoken languages, so this could not be checked."
    ),
    RequirementType.OTHER: "This requirement could not be checked automatically.",
}


def _unassessable(
    requirement_type: RequirementType,
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """UNKNOWN, and never anything worse.

    The goal is explicit that UNKNOWN is never GAP. Work authorisation is the
    case that matters: ``docs/05-ai-and-matching.md`` lists it as a genuine
    blocker, and the profile stores nothing about it — so inferring one would
    mean inventing a blocker from an absence. The honest answer is to say we
    cannot tell and hand it to the user.
    """
    return (
        MatchStatus.UNKNOWN,
        20,
        _UNASSESSABLE_REASONS.get(
            requirement_type, "This requirement could not be checked automatically."
        ),
        [],
    )


def _terms(text: str) -> list[str]:
    """Words worth matching on, lowercased.

    Short words are dropped: "of" and "in" appear in every description and
    would make every requirement look evidenced.
    """
    return [word for word in _WORD.findall(text.casefold()) if len(word) > 3]
