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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from jip_api.application.matching.evidence import (
    EducationEvidence,
    ProfileSnapshot,
    SkillEvidence,
)
from jip_api.domain.jobs.analysis import (
    RequirementImportance,
    RequirementType,
)
from jip_api.domain.matching.education import answers as education_answers
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
    requirements: Sequence[MatchableRequirement],
    snapshot: ProfileSnapshot,
    canonical_names: Mapping[uuid.UUID, str] | None = None,
) -> list[Verdict]:
    """Evaluate every requirement independently.

    Independently is the operative word: no requirement's verdict depends on
    another's, so a posting cannot drag its own score down by asking for
    something unusual, and the results can be read in any order.

    ``canonical_names`` maps a resolved ``skill_id`` to the catalogue's own name
    for it. Passed in rather than looked up, for the same reason ``snapshot``
    is: the matcher must not touch a database, and that property is what the
    determinism tests rest on.

    Optional, and its absence is a silent loss of transferability rather than an
    error — see :func:`_match_skill` for why, and DEV-059 for what that cost.
    """
    lookup = canonical_names or {}
    return [_match_one(requirement, snapshot, lookup) for requirement in requirements]


def _match_one(
    requirement: MatchableRequirement,
    snapshot: ProfileSnapshot,
    canonical_names: Mapping[uuid.UUID, str],
) -> Verdict:
    importance = RequirementImportance(requirement.importance)
    requirement_type = RequirementType(requirement.requirement_type)

    status, confidence, explanation, evidence = _evaluate(
        requirement, requirement_type, snapshot, canonical_names
    )

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
    canonical_names: Mapping[uuid.UUID, str],
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Dispatch to the rule for this requirement type."""
    if requirement_type is RequirementType.TECHNICAL_SKILL:
        return _match_skill(requirement, snapshot, canonical_names)
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


_ALTERNATIVE_SEPARATORS = re.compile(
    r"\s*/\s*|\s+(?:or|and/or)\s+",
    re.IGNORECASE,
)
"""What separates one offered skill from another.

A slash with optional spaces, or the words "or" / "and/or" **surrounded by
spaces**. The spaces are load-bearing: without them this splits `Fortran` into
`F` and `tran`, and `Terraform` into `Terraf` and `m`.
"""


def _alternatives(name: str) -> list[str]:
    """The separate skills a composite requirement name offers.

    `Linux/Unix` is two, `C/C++` is two, `Node.js` is one — the split is on
    separators between words, and a dot inside a name is not one.

    Returns nothing for a name with no separator, so the ordinary case does no
    extra work and cannot be changed by this at all.

    Length-guarded: a requirement whose "skill name" is a whole sentence — "at
    least one programming or scripting language (e.g. Python, Go, Bash)" — is
    not repairable by splitting, and pretending otherwise would produce
    fragments that match nothing. That case needs the parse schema to carry a
    list, which is the other half of DEV-055 and is still open.
    """
    if len(name) > 40:
        return []
    parts = [part.strip() for part in _ALTERNATIVE_SEPARATORS.split(name)]
    return [part for part in parts if part and part != name]


def _match_skill(
    requirement: MatchableRequirement,
    snapshot: ProfileSnapshot,
    canonical_names: Mapping[uuid.UUID, str],
) -> tuple[MatchStatus, int, str, list[EvidenceRef]]:
    """Exact, then alias, then demonstration, then transferability.

    Two names, deliberately. ``name`` is what the posting wrote and is what the
    user reads back; ``lookup`` is what the catalogue calls it and is what the
    transferability table is keyed by.

    Collapsing them cost DEV-059. A posting asking for `C/C++` — an alias of
    `C++` — resolved correctly, and then lost transferability, because
    `find_transfer` was handed the alias:

        find_transfer("C++",   ["C", ...])  ->  C via systems languages
        find_transfer("C/C++", ["C", ...])  ->  NO TRANSFER

    A profile holding C was told it had no C/C++, while the same requirement
    written `C++` on another posting returned TRANSFERABLE. Every alias in the
    catalogue had this, not only the ones spelling out alternatives, and only
    on the transfer path — direct matching goes by ``skill_id`` and was always
    right, which is why it stayed hidden.
    """
    name = requirement.skill_name or requirement.normalized_text
    lookup = canonical_names.get(requirement.skill_id) if requirement.skill_id else None
    lookup = lookup or name

    held = snapshot.find_skill(skill_id=requirement.skill_id, name=lookup)

    # DEV-055. A posting writing `Linux/Unix` means either one, and the whole
    # string resolves to neither — so a profile holding Linux was told it had
    # no Linux/Unix. Splitting is done here rather than at parse time because
    # it repairs the postings already analysed; the parse schema still carries
    # one name per requirement, and until it carries a list this is the half of
    # the fix that costs nothing to apply.
    #
    # "Any of these" is the right reading: a posting offering alternatives is
    # satisfied by one of them, and treating it as demanding all would make the
    # posting stricter than it wrote itself.
    if held is None:
        for alternative in _alternatives(name):
            held = snapshot.find_skill(skill_id=None, name=alternative)
            if held is not None:
                lookup = alternative
                break

    if held is not None:
        return _classify_held_skill(held, name, snapshot)

    if not snapshot.skills:
        return (
            MatchStatus.NO_EVIDENCE,
            30,
            f"There are no skills in your profile yet, so {name} could not be checked.",
            [],
        )

    transfer = find_transfer(lookup, snapshot.held_skill_names())
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


def _years_met_sentence(
    held_years: int, required_years: int, counted: list[EvidenceRef] | None = None
) -> str:
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
    phrase = _years_phrase(held_years, counted or [])
    if required_years <= 0:
        return f"This asks for no minimum experience, and you have {phrase}."
    return f"You have {phrase} against the {required_years} asked for."


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

    # DEV-061, part 2. A requirement naming a subject must find the subject.
    #
    # Until now the years branch compared numbers and nothing else, so "1 year
    # of experience with digital logic design" was answered STRONG_MATCH by
    # three years of anything — radar technician work from 2014, in the case
    # that found this. "3 years of experience in neurosurgery" scored 100.
    #
    # PARTIAL_MATCH rather than GAP, and the difference matters more than it
    # looks: a GAP on a CORE requirement becomes a BLOCKER, the strongest claim
    # this engine makes, and keyword absence does not justify it. [employer 1]'s "1-2
    # years of experience in Data Science and/or AI Engineering" blocked a
    # profile carrying three machine-learning projects, because none of them
    # writes the words "data science".
    #
    # So: credit the years, deny the subject, and say both. The sentence carries
    # the doubt, which is where `docs/05` wants it — the reader may know better
    # than a word comparison does.
    #
    # Checked only when there is something to search. A profile carrying a stated "6
    # years" and no roles has no text for the keyword pass to read, so every
    # subject-bearing requirement would fail it — and **"cannot check" is not
    # "absent"**. That is the half-filled profile `GOAL.md` protects, and it is
    # a different case from a profile full of radar work that genuinely says
    # nothing about chip design.
    searchable = bool(snapshot.experiences or snapshot.projects)

    # A posting demanding nothing has no subject to evidence. "No prior
    # professional experience required" parses to zero years, and running the
    # check on it produced *"you have 3 years, but nothing in your profile is
    # about required"* — a shortfall invented against an invitation to juniors.
    subject = _subject_of(requirement.normalized_text) if required_years > 0 else None
    if subject and searchable and not _subject_is_evidenced(subject, snapshot):
        sources = _years_evidence(snapshot)
        return (
            MatchStatus.PARTIAL_MATCH,
            45,
            f"You have {_years_phrase(held_years, sources)}, but nothing in your "
            f"profile is about {subject}.",
            sources,
        )

    # DEV-061, parts 1 and 3. Cite the roles the years were counted from, and
    # say so in the sentence.
    #
    # These used to disagree. The number came from summing `experiences`, the
    # evidence came from a keyword search that also reads projects, and nothing
    # made them meet — so a verdict reading "you have 3 years" cited three
    # projects that had contributed no part of it. The evidence drawer is the
    # feature this product is built on, and it was showing decoration.
    counted = _years_evidence(snapshot) if snapshot.stated_years is None else []
    shown = counted or evidence

    if held_years >= required_years:
        return (
            MatchStatus.STRONG_MATCH,
            85,
            _years_met_sentence(held_years, required_years, counted),
            shown,
        )

    if required_years and held_years >= required_years * 0.6:
        return (
            MatchStatus.PARTIAL_MATCH,
            70,
            f"You have {_years_phrase(held_years, counted)} against the "
            f"{required_years} asked for — close, and years are rarely a hard cut-off.",
            shown,
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
        shown,
    )


_YEARS_BOILERPLATE = frozenset(
    {
        # Connectives. `_terms` filters on length alone, and "with" is four
        # characters — long enough to survive, common enough to appear in
        # almost every description. It let "digital logic design" pass the
        # subject check on "with" plus "design", found in "Designed for
        # medical-grade reliability" in a computer-vision project.
        "with",
        "within",
        "and",
        "the",
        "for",
        "from",
        "that",
        "this",
        "into",
        "using",
        "such",
        "including",
        "across",
        "over",
        "have",
        "must",
        "should",
        # How much the posting wants it. These say nothing about *what* it
        # wants, and they never appear in anybody's CV — so leaving them in the
        # subject made "5 years of backend required" ask for a profile
        # containing the word "required", which no profile contains. Every
        # requirement phrased that way would have failed the check below.
        "required",
        "require",
        "requires",
        "preferred",
        "mandatory",
        "essential",
        "advantage",
        "advantageous",
        "needed",
        "necessary",
        "nice",
        "ideally",
        "desirable",
        # Intensifiers. They qualify a subject without naming one.
        "strong",
        "solid",
        "good",
        "deep",
        "excellent",
        "demonstrated",
        "practical",
        "extensive",
        "some",
        "prior",
        "previous",
        "year",
        "years",
        "experience",
        "experienced",
        "professional",
        "industry",
        "commercial",
        "hands",
        "working",
        "work",
        "minimum",
        "least",
        "plus",
        "relevant",
        "proven",
        "track",
        "record",
        "role",
        "roles",
        "position",
        "full",
        "time",
    }
)


def _subject_of(text: str) -> str | None:
    """What a years requirement is *about*, if it is about anything.

    "3+ years of professional experience" is a quantity and nothing else, and
    the total is the right answer for it. "1 year of experience with digital
    logic design principles" is a quantity **and a subject**, and answering it
    without looking for the subject is how a radar technician came to have a
    year of chip design.

    Returns the subject words joined, for the explanation to quote back, or
    ``None`` when the requirement names none.
    """
    words = [word for word in _terms(text) if word not in _YEARS_BOILERPLATE]
    return " ".join(words) if words else None


def _subject_is_evidenced(subject: str, snapshot: ProfileSnapshot) -> bool:
    """Whether one role or project is about ``subject``, rather than sharing a
    word with it.

    Two words have to land **in the same item**, which is what separates
    evidence from coincidence. "Digital logic design" first passed this check on
    the word `design` alone, found inside "Designed for medical-grade
    reliability" in a computer-vision project — a single common word, in an
    unrelated sentence, standing in for a subject the profile knows nothing
    about.

    A one-word subject needs that one word, because there is nothing else to
    ask for. Two is the threshold everywhere else, not a majority: "digital
    logic design principles" should not need `principles`, which appears in no
    CV ever written.
    """
    # Deduplicated. "digital logic design principles and RTL design concepts"
    # names `design` twice, and counting it twice let one word clear a
    # two-word threshold — the coincidence this function exists to reject,
    # passing because the posting repeated itself.
    words = sorted(set(subject.split()))
    needed = min(2, len(words))

    for haystack in _searchable_texts(snapshot):
        if sum(1 for word in words if word in haystack) >= needed:
            return True
    return False


def _searchable_texts(snapshot: ProfileSnapshot) -> list[str]:
    """Every role and project as one lowercased blob each.

    Per item rather than concatenated, so words from two unrelated projects
    cannot combine into evidence for a subject neither of them is about.
    """
    texts = [
        " ".join(part for part in (e.title, e.description) if part).casefold()
        for e in snapshot.experiences
    ]
    texts += [
        " ".join(part for part in (p.name, p.summary, p.description) if part).casefold()
        for p in snapshot.projects
    ]
    return texts


def _years_evidence(snapshot: ProfileSnapshot) -> list[EvidenceRef]:
    """The roles the year count was actually summed from, newest first."""
    dated = [experience for experience in snapshot.experiences if experience.months]
    dated.sort(key=lambda e: (e.months, str(e.id)), reverse=True)
    return [
        EvidenceRef(
            evidence_type=EvidenceType.EXPERIENCE,
            entity_id=experience.id,
            label=f"{experience.title} at {experience.company}",
            detail=experience.description,
            verification_status=experience.verification_status,
            relevance=90,
        )
        for experience in dated
    ]


def _years_phrase(held_years: int, counted: list[EvidenceRef]) -> str:
    """ "3 years" or "3 years, from Team Leader Technician at the IDF".

    Naming the source is the whole of DEV-061 part 3. A reader who is told what
    was counted can disagree with it in one glance; a bare number gives them
    nothing to disagree with, which is how three years of radar work passed for
    three years of software.
    """
    plural = "year" if held_years == 1 else "years"
    if not counted:
        return f"{held_years} {plural}"
    if len(counted) == 1:
        return f"{held_years} {plural}, from {counted[0].label}"
    return f"{held_years} {plural}, from {counted[0].label} and {len(counted) - 1} more"


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


def _education_evidence(education: EducationEvidence, *, relevance: int = 90) -> EvidenceRef:
    """One qualification, cited.

    The label reads as the user wrote it — degree and field — because the point
    of evidence is that they recognise it.
    """
    return EvidenceRef(
        evidence_type=EvidenceType.EDUCATION,
        entity_id=education.id,
        label=" — ".join(
            part
            for part in (education.degree or education.institution, education.field_of_study)
            if part
        ),
        detail=education.institution,
        verification_status="USER_CONFIRMED",
        relevance=relevance,
    )


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

    # Equivalence first, words second. DEV-060: a B.Sc. in Software Engineering
    # shares no word with "Bachelor's degree in Computer Science", so the word
    # comparison below returned a GAP — and on a CORE requirement, which these
    # usually are, a BLOCKER against a qualification the user holds.
    for education in snapshot.education:
        matched, via = education_answers(
            requirement.normalized_text,
            education.degree or "",
            education.field_of_study or "",
        )
        if not matched:
            continue

        ref = _education_evidence(education)
        if via is None:
            return (MatchStatus.MATCH, 80, f"Your {ref.label} covers this.", [ref])
        # Named on both sides rather than asserted. `docs/05` forbids reporting
        # similarity as equivalence, and a reader who disagrees that these two
        # fields answer each other can see exactly what was claimed.
        return (
            MatchStatus.MATCH,
            70,
            f"Your {ref.label} is in {via.title()}, not what the posting named, "
            "but it is the same kind of degree.",
            [ref],
        )

    terms = _terms(requirement.normalized_text)
    best: tuple[int, EvidenceRef] | None = None

    for education in snapshot.education:
        overlap = sum(1 for term in terms if term in education.searchable)
        if not overlap:
            continue
        ref = _education_evidence(education, relevance=min(50 + overlap * 20, 100))
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
