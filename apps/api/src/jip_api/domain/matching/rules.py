"""The scoring rules. Deterministic, versioned, and free of AI.

``docs/05-ai-and-matching.md`` gives the starting values and requires them to be
versioned and calibrated. This module is that table, and
:data:`MATCHING_ENGINE_VERSION` is what makes a change to it visible: every
match records the version that produced it, so re-tuning a weight does not
silently re-score history.

Everything here is a pure function of its inputs. No database, no clock, no
provider — which is what lets the determinism test assert that the same inputs
produce byte-identical output.
"""

from __future__ import annotations

from decimal import Decimal

from jip_api.domain.jobs.analysis import RequirementImportance, RequirementType
from jip_api.domain.matching.models import MatchCategory, MatchStatus, Recommendation

MATCHING_ENGINE_VERSION = "4.0.0"
"""Bump on any change to the values or logic below.

Major for a change that reorders which jobs look better than which; minor for a
new rule that leaves existing verdicts alone; patch for a fix that could not
change a score.

**4.0.0 (2026-08-15) — DEV-061**, and the first change here that *lowers*
scores. Found by a user asking why the engine credited him a year of chip
design.

The years branch compared numbers and read nothing else, so three years of
radar-technician work answered "1 year of experience with digital logic design"
with STRONG_MATCH and a score of 100. "3 years of experience in neurosurgery"
scored 100 as well. Three parts:

*The evidence must be what produced the verdict.* The number was summed from
`experiences`; the evidence came from a keyword pass that also reads projects;
nothing made them meet. A verdict reading "you have 3 years" cited three
projects that had contributed none of it.

*A requirement naming a subject must find the subject*, and two of its words
have to land in the same item. One word is coincidence: "digital logic design"
first passed on `design` alone, inside "Designed for medical-grade reliability"
in a computer-vision project.

*The sentence must say what it counted.* "You have 3 years, from Team Leader
Technician at the IDF" is disagreed with in one glance; "You have 3 years" gives
a reader nothing to disagree with, which is how three years of radar work passed
for three years of software.

A bare "3+ years of experience" is still answered by the total, and a profile
with stated years and no roles listed still passes — it has no text to search,
and cannot check is not absent.

**3.0.0 (2026-08-15) — DEV-055 and DEV-060**, both found on posting 3 of the
DEV-011 calibration and both turning a qualification the user holds into a gap.

*DEV-055, the half that costs nothing to apply.* A posting writing `Linux/Unix`
offers either, and the whole string resolved to neither — so a profile holding
Linux was told it had no Linux/Unix, at REQUIRED weight. `_match_skill` now
splits a composite name on `/`, `or` and `and/or` and accepts any alternative.
The separator must be surrounded by space or `Fortran` splits into `F` and
`tran`. Whole sentences are left alone: "at least one programming or scripting
language (e.g. Python, Go, Bash)" is not repairable by splitting, and needs the
parse schema to carry a list, which remains open.

*DEV-060.* `_match_education` counted shared words, and a **B.Sc. in Software
Engineering** shares none with **"Bachelor's degree in Computer Science"** —
GAP, and on a CORE requirement a BLOCKER. `domain/matching/education.py` now
holds degree-level abbreviations and one group of fields a software posting
treats as answering each other. It returns MATCH rather than STRONG_MATCH and
names both sides, because `docs/05` forbids reporting similarity as equivalence.

Major again: both move requirements off zero, so scores rise and jobs reorder.

**2.0.0 (2026-08-15) — DEV-059.** A requirement that resolved through a
catalogue alias lost transferability, because `_match_skill` handed the
posting's own wording to `find_transfer` instead of the canonical name the
transfer table is keyed by. `C/C++` is an alias of `C++`; a profile holding `C`
was told it had no `C/C++`, while the same requirement written `C++` returned
TRANSFERABLE.

Major rather than patch, and the values below are untouched. GAP scores 0 and
TRANSFERABLE_MATCH scores 50, so every affected requirement moves fifty points
and jobs reorder against each other. The rule above is about consequence, not
about which file changed.

Found on the second posting of the DEV-011 calibration, and fixed before the
remaining eighteen so the set is measured against one engine.

**1.0.0** — the values from `docs/05-ai-and-matching.md` as first written.
"""


STATUS_SCORES: dict[MatchStatus, int] = {
    MatchStatus.STRONG_MATCH: 100,
    MatchStatus.MATCH: 85,
    MatchStatus.PARTIAL_MATCH: 60,
    MatchStatus.TRANSFERABLE_MATCH: 50,
    MatchStatus.UNKNOWN: 35,
    MatchStatus.NO_EVIDENCE: 0,
    MatchStatus.GAP: 0,
    MatchStatus.BLOCKER: 0,
}
"""The mapping from ``docs/05-ai-and-matching.md``, exactly.

NO_EVIDENCE carries a zero here but never reaches the average — see
:func:`weighted_score`, which drops it from both sides of the division. The
zero exists only so the column is never null.

TRANSFERABLE_MATCH at 50 rather than nearer MATCH is deliberate. Django
experience is real evidence for a Spring Boot role and it is not Spring Boot;
scoring it at 75 would make the two indistinguishable in aggregate, which is
precisely the equivalence the document forbids.
"""


IMPORTANCE_WEIGHTS: dict[RequirementImportance, Decimal] = {
    RequirementImportance.CORE: Decimal("3.00"),
    RequirementImportance.REQUIRED: Decimal("2.00"),
    RequirementImportance.PREFERRED: Decimal("0.50"),
    RequirementImportance.OPTIONAL: Decimal("0.25"),
    RequirementImportance.UNKNOWN: Decimal("1.00"),
}
"""How much each requirement counts.

Decimal, not float: the weighted average has to reproduce exactly across a
database round trip, and binary floating point does not promise that.

Preferred sits at a sixth of core because the goal requires preferences to
affect the score *lightly*. A posting with twenty nice-to-haves and four real
requirements must still be scored on the four.
"""


TYPE_CATEGORIES: dict[RequirementType, MatchCategory] = {
    RequirementType.TECHNICAL_SKILL: MatchCategory.TECHNICAL,
    RequirementType.EXPERIENCE: MatchCategory.EXPERIENCE,
    RequirementType.EDUCATION: MatchCategory.EDUCATION,
    RequirementType.DOMAIN_KNOWLEDGE: MatchCategory.DOMAIN,
    RequirementType.LANGUAGE: MatchCategory.OTHER,
    RequirementType.SOFT_SKILL: MatchCategory.OTHER,
    RequirementType.LOCATION: MatchCategory.OTHER,
    RequirementType.WORK_AUTHORIZATION: MatchCategory.OTHER,
    RequirementType.OTHER: MatchCategory.OTHER,
}


BLOCKER_CAP = 45
"""The ceiling on a match with an unmet core requirement.

``docs/05-ai-and-matching.md`` allows real blockers to cap the overall score.
Forty-five sits below every "worth pursuing" band, so a blocked job cannot
present as a good opportunity however well the rest of it scores — while
staying above zero, because the rest of it is still true and the user may
disagree with our reading of the blocker.
"""


def category_for(
    requirement_type: RequirementType, importance: RequirementImportance
) -> MatchCategory:
    """Which category an item is scored in.

    Importance wins over type: ``docs/05-ai-and-matching.md`` lists "preferred
    requirements" as a category alongside technical and experience, so a
    preferred technical skill is scored as a preference. Without this a posting
    could dilute its own technical score by listing optional extras.
    """
    if importance in {RequirementImportance.PREFERRED, RequirementImportance.OPTIONAL}:
        return MatchCategory.PREFERRED
    return TYPE_CATEGORIES.get(requirement_type, MatchCategory.OTHER)


def weight_for(importance: RequirementImportance) -> Decimal:
    return IMPORTANCE_WEIGHTS.get(importance, Decimal("1.00"))


def score_for(status: MatchStatus) -> int:
    return STATUS_SCORES[status]


def can_block(importance: RequirementImportance) -> bool:
    """Whether an unmet requirement of this importance is a blocker.

    Only CORE. REQUIRED is heavily weighted but does not cap, and the goal is
    explicit that a preference must never become one — a "nice to have" that
    blocked an application would be the promotion failure from Phase 5 wearing
    a different hat.
    """
    return importance is RequirementImportance.CORE


def weighted_score(scored: list[tuple[int, Decimal]]) -> int | None:
    """sum(score * weight) / sum(weight), rounded half-up.

    ``scored`` excludes NO_EVIDENCE items — the caller drops them, because an
    item we could not assess must not pull the average down. Returns ``None``
    when nothing was assessable: no number at all is the honest answer, and
    zero would be a claim about the candidate we have no grounds for.
    """
    total_weight = sum((weight for _, weight in scored), Decimal("0"))
    if total_weight <= 0:
        return None

    total = sum((Decimal(score) * weight for score, weight in scored), Decimal("0"))
    # Half-up rather than banker's rounding: 84.5 becoming 84 surprises people,
    # and the difference has to be reproducible rather than merely unbiased.
    return int((total / total_weight + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))


ALIGNMENT_BANDS: list[tuple[int, str]] = [
    (85, "Strong alignment"),
    (70, "Good alignment"),
    (50, "Partial alignment"),
    (30, "Limited alignment"),
    (0, "Little alignment"),
]
"""Words for the number.

``docs/05-ai-and-matching.md`` is categorical that a score must be presented as
profile-to-job alignment and never as a chance of being hired. A band label
carries that meaning where a bare percentage invites the other reading.
"""


def alignment_label(score: int | None) -> str:
    if score is None:
        return "Not enough profile data"
    return next(label for floor, label in ALIGNMENT_BANDS if score >= floor)


def recommend(
    *,
    score: int | None,
    has_blockers: bool,
    unmet_core: int,
    unmet_required: int,
    assessable_ratio: float,
) -> tuple[Recommendation, list[str]]:
    """What to do about this job, and why.

    Deliberately not a second reading of the score.
    ``docs/05-ai-and-matching.md`` lists blockers, core requirements, role
    alignment, seniority, and gap severity as inputs beyond the number, so the
    recommendation and the percentage are allowed to disagree — and when they
    do, the disagreement is the useful part.

    Returns the reasons alongside, because a recommendation the user cannot
    interrogate is one they have to take on trust.
    """
    reasons: list[str] = []

    if score is None:
        return Recommendation.CONSIDER, [
            "There is not enough in your profile yet to compare against this job."
        ]

    if has_blockers:
        reasons.append(
            f"{unmet_core} essential requirement{'s' if unmet_core != 1 else ''} "
            "has no evidence in your profile."
        )
        # Not PROBABLY_SKIP: a blocker is our reading of the posting, and the
        # user knows things we do not. LOW_PRIORITY says "look at this last",
        # which is advice; "skip" would be a decision.
        return (
            Recommendation.PROBABLY_SKIP if unmet_core >= 3 else Recommendation.LOW_PRIORITY
        ), reasons

    if assessable_ratio < 0.5:
        reasons.append(
            "Less than half of this posting could be checked against your profile, "
            "so this score is a weak signal."
        )
        return Recommendation.CONSIDER, reasons

    if score >= 85 and unmet_required == 0:
        reasons.append("Your profile covers every stated requirement.")
        return Recommendation.STRONG_APPLY, reasons

    if score >= 70:
        if unmet_required:
            reasons.append(
                f"{unmet_required} stated requirement{'s' if unmet_required != 1 else ''} "
                "is not evidenced, but the rest lines up well."
            )
        else:
            reasons.append("Your profile covers the important requirements.")
        return Recommendation.APPLY, reasons

    if score >= 50:
        reasons.append("A partial fit — worth reading the gaps before deciding.")
        return Recommendation.CONSIDER, reasons

    if score >= 30:
        reasons.append("Most of what this posting asks for is not yet evidenced.")
        return Recommendation.LOW_PRIORITY, reasons

    reasons.append("Very little of this posting matches your profile as it stands.")
    return Recommendation.PROBABLY_SKIP, reasons
