"""The deterministic matcher and scorer.

Everything here runs without a database, a clock, or a model — which is the
property under test as much as any individual verdict. If this file ever needs
a fixture with I/O in it, the engine has stopped being deterministic.

The rules these protect, in the order they matter:

- transferable is never a direct match;
- unverified data is never strong evidence;
- UNKNOWN is never a gap, and never a blocker;
- an incomplete profile does not reduce the score;
- a preference never blocks;
- the same inputs always produce the same number.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from jip_api.application.matching.evidence import (
    ExperienceEvidence,
    ProfileSnapshot,
    ProjectEvidence,
    SkillEvidence,
)
from jip_api.application.matching.matcher import Verdict, match_requirements
from jip_api.application.matching.scoring import score_match
from jip_api.domain.matching.models import MatchCategory, MatchStatus, Recommendation
from jip_api.domain.matching.rules import BLOCKER_CAP, weighted_score
from jip_api.domain.matching.transferable import find_transfer, groups_for

EXPERIENCE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def skill(
    name: str,
    *,
    proficiency: str | None = "ADVANCED",
    years: int | None = 4,
    last_used: int | None = None,
    verification: str = "USER_CONFIRMED",
    experiences: tuple[uuid.UUID, ...] = (),
    projects: tuple[uuid.UUID, ...] = (),
) -> SkillEvidence:
    normalized = name.lower().replace(".", "").replace(" ", "-")
    return SkillEvidence(
        user_skill_id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        canonical_name=name,
        normalized_name=normalized,
        proficiency=proficiency,
        years_of_experience=years,
        last_used_year=last_used,
        verification_status=verification,
        experience_ids=experiences,
        project_ids=projects,
    )


def profile(*skills: SkillEvidence, years: int | None = 6, **extra: object) -> ProfileSnapshot:
    snapshot = ProfileSnapshot(
        user_id=uuid.uuid4(),
        profile=SimpleNamespace(years_of_experience=years, current_location="Lisbon"),
    )
    for item in skills:
        snapshot.skills.append(item)
        snapshot.skills_by_id[item.skill_id] = item
        snapshot.skills_by_normalized[item.normalized_name] = item

    if extra.get("with_experience"):
        snapshot.experiences.append(
            ExperienceEvidence(
                id=EXPERIENCE_ID,
                company="Verdant",
                title="Senior Backend Engineer",
                normalized_title="senior backend engineer",
                start_date=dt.date(2019, 1, 1),
                end_date=None,
                is_current=True,
                description="Built distributed routing services and mentored engineers.",
                verification_status="USER_CONFIRMED",
                achievements=(),
            )
        )
    return snapshot


def requirement(
    text: str,
    requirement_type: str = "TECHNICAL_SKILL",
    importance: str = "REQUIRED",
    *,
    skill_name: str | None = None,
    years_min: int | None = None,
    order: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        normalized_text=text,
        requirement_type=requirement_type,
        importance=importance,
        skill_id=None,
        skill_name=skill_name if skill_name is not None else text,
        years_min=years_min,
        source_order=order,
    )


def verdict_for(
    requirements: list[SimpleNamespace],
    snapshot: ProfileSnapshot,
    canonical_names: dict[uuid.UUID, str] | None = None,
) -> Verdict:
    return match_requirements(requirements, snapshot, canonical_names)[0]


# --- transferability ----------------------------------------------------------


def test_an_alias_still_finds_the_transfer_behind_it() -> None:
    """DEV-059, found on the second posting of the DEV-011 calibration.

    A posting asked for `C/C++`, which the catalogue holds as an alias of `C++`,
    so it resolved correctly. The transfer table is keyed by canonical names, and
    `_match_skill` was handing it the posting's own wording:

        find_transfer("C++",   ["C", ...])  ->  C via systems languages
        find_transfer("C/C++", ["C", ...])  ->  NO TRANSFER

    A profile holding C was told it had no C/C++, while the same requirement
    written `C++` on another posting returned TRANSFERABLE. Same skill, same
    profile, opposite verdicts, decided by how the posting happened to spell it.
    """
    skill_id = uuid.uuid4()
    written_as_alias = requirement("Experience with C/C++", skill_name="C/C++")
    written_as_alias.skill_id = skill_id

    result = verdict_for([written_as_alias], profile(skill("C")), {skill_id: "C++"})

    assert result.status is MatchStatus.TRANSFERABLE_MATCH


def test_the_user_reads_the_wording_the_posting_used() -> None:
    """The canonical name is for looking up, not for talking.

    Telling someone "C++ is not in your profile" when the posting said `C/C++`
    describes a requirement they did not read. The explanation quotes the
    posting; only the lookup is translated.
    """
    skill_id = uuid.uuid4()
    asked = requirement("Experience with C/C++", skill_name="C/C++")
    asked.skill_id = skill_id

    result = verdict_for([asked], profile(skill("C")), {skill_id: "C++"})

    assert "C/C++" in result.explanation


def test_transferability_still_works_with_no_catalogue_lookup() -> None:
    """The mapping is optional, and its absence must not be silently worse than
    passing it. A posting whose wording *is* the canonical name — the ordinary
    case — resolves the same either way."""
    result = verdict_for([requirement("C++")], profile(skill("C")))

    assert result.status is MatchStatus.TRANSFERABLE_MATCH


def test_a_transferable_skill_is_never_a_direct_match() -> None:
    """The rule docs/05-ai-and-matching.md states outright: Django is not
    Spring Boot. Scoring them alike would make the two indistinguishable in
    aggregate, which is exactly the equivalence it forbids."""
    result = verdict_for([requirement("Spring Boot")], profile(skill("FastAPI")))

    assert result.status is MatchStatus.TRANSFERABLE_MATCH
    # Spelled out rather than "is not MATCH", so the guarantee covers every
    # status that would overstate the evidence rather than just the nearest one.
    assert result.status not in {MatchStatus.MATCH, MatchStatus.STRONG_MATCH}


def test_a_transferable_explanation_names_both_sides() -> None:
    """ "Similar experience" is an assertion. Naming the held skill, the wanted
    skill, and the group is an argument the user can disagree with."""
    result = verdict_for([requirement("Spring Boot")], profile(skill("FastAPI")))

    assert "FastAPI" in result.explanation
    assert "Spring Boot" in result.explanation
    assert "server-side web frameworks" in result.explanation


def test_a_transferable_match_scores_below_a_real_one() -> None:
    transferable = verdict_for([requirement("Spring Boot")], profile(skill("FastAPI")))
    direct = verdict_for([requirement("FastAPI")], profile(skill("FastAPI")))

    assert transferable.score < direct.score


def test_unrelated_skills_do_not_transfer() -> None:
    """Python and Java are both languages and are deliberately in no group
    together. A transferable claim there would mislead."""
    assert find_transfer("Java", ["Python"]) is None


def test_a_skill_in_no_group_transfers_to_nothing() -> None:
    assert groups_for("Cobol") == ()


def test_the_same_skill_is_not_its_own_transfer() -> None:
    """A direct match is not this module's business to report."""
    assert find_transfer("React", ["React"]) is None


def test_transfer_selection_is_deterministic() -> None:
    held = ["Django", "Flask", "Express"]
    assert find_transfer("Spring Boot", held) == find_transfer("Spring Boot", held)


# --- verification ---------------------------------------------------------------


def test_unverified_evidence_is_never_a_strong_match() -> None:
    """The goal's rule. An AI-inferred skill the user never confirmed cannot be
    the reason we tell them they are a strong fit."""
    result = verdict_for(
        [requirement("Docker")],
        profile(skill("Docker", verification="AI_INFERRED", experiences=(EXPERIENCE_ID,))),
    )

    assert result.status is MatchStatus.PARTIAL_MATCH


def test_unverified_evidence_is_still_shown() -> None:
    """Weaker, not discarded. Dropping it would throw away a true fact."""
    result = verdict_for(
        [requirement("Docker")], profile(skill("Docker", verification="UNVERIFIED"))
    )

    assert result.evidence
    assert "not been confirmed" in result.explanation


def test_a_confirmed_demonstrated_skill_is_a_strong_match() -> None:
    result = verdict_for(
        [requirement("Python")],
        profile(skill("Python", experiences=(EXPERIENCE_ID,)), with_experience=True),
    )

    assert result.status is MatchStatus.STRONG_MATCH


def test_a_confirmed_but_undemonstrated_skill_is_only_a_match() -> None:
    result = verdict_for(
        [requirement("Python")], profile(skill("Python", proficiency=None, years=None))
    )

    assert result.status is MatchStatus.MATCH


def test_a_long_unused_skill_is_downgraded() -> None:
    """docs/03-domain-model.md: recency matters as much as depth."""
    result = verdict_for(
        [requirement("Perl")],
        profile(skill("Perl", last_used=2005, years=2, experiences=(EXPERIENCE_ID,))),
    )

    assert result.status is MatchStatus.PARTIAL_MATCH
    assert "2005" in result.explanation


# --- gaps, unknowns, and absent evidence ----------------------------------------


def test_a_missing_skill_is_a_gap_when_the_profile_has_skills() -> None:
    result = verdict_for([requirement("Rust")], profile(skill("Python")))

    assert result.status is MatchStatus.GAP


def test_a_missing_skill_is_no_evidence_when_the_profile_has_none() -> None:
    """Absence of data is a fact about us, not about the candidate."""
    result = verdict_for([requirement("Rust")], profile())

    assert result.status is MatchStatus.NO_EVIDENCE


def test_work_authorisation_is_unknown_and_never_a_gap() -> None:
    """The profile stores nothing about it, so inferring a blocker would mean
    inventing one from an absence."""
    result = verdict_for(
        [requirement("Right to work", "WORK_AUTHORIZATION", "CORE")], profile(skill("Python"))
    )

    assert result.status is MatchStatus.UNKNOWN
    assert result.is_blocker is False


@pytest.mark.parametrize(
    "requirement_type", ["WORK_AUTHORIZATION", "LOCATION", "LANGUAGE", "OTHER"]
)
def test_unassessable_types_are_unknown_whatever_their_importance(requirement_type: str) -> None:
    result = verdict_for(
        [requirement("Something", requirement_type, "CORE")], profile(skill("Python"))
    )

    assert result.status is MatchStatus.UNKNOWN


def test_unknown_scores_neutrally_rather_than_as_a_failure() -> None:
    result = verdict_for(
        [requirement("Right to work", "WORK_AUTHORIZATION", "CORE")], profile(skill("Python"))
    )

    assert result.score == 35


# --- blockers -------------------------------------------------------------------


def test_a_core_gap_becomes_a_blocker() -> None:
    result = verdict_for([requirement("Rust", importance="CORE")], profile(skill("Python")))

    assert result.status is MatchStatus.BLOCKER
    assert result.is_blocker is True


def test_a_required_gap_is_not_a_blocker() -> None:
    result = verdict_for([requirement("Rust", importance="REQUIRED")], profile(skill("Python")))

    assert result.status is MatchStatus.GAP
    assert result.is_blocker is False


def test_a_preferred_gap_never_blocks() -> None:
    """The goal is explicit. A nice-to-have that blocked an application would
    be Phase 5's promotion failure wearing a different hat."""
    result = verdict_for([requirement("Rust", importance="PREFERRED")], profile(skill("Python")))

    assert result.is_blocker is False


def test_no_evidence_never_blocks() -> None:
    """An empty profile must not produce a blocked match."""
    result = verdict_for([requirement("Rust", importance="CORE")], profile())

    assert result.status is MatchStatus.NO_EVIDENCE
    assert result.is_blocker is False


def test_a_blocker_caps_the_overall_score() -> None:
    verdicts = match_requirements(
        [
            requirement("Python", importance="REQUIRED", order=0),
            requirement("FastAPI", importance="REQUIRED", order=1),
            requirement("Rust", importance="CORE", order=2),
        ],
        profile(skill("Python", experiences=(EXPERIENCE_ID,)), skill("FastAPI")),
    )

    result = score_match(verdicts)

    assert result.has_blockers is True
    assert result.overall_score == BLOCKER_CAP
    assert result.score_cap == BLOCKER_CAP
    assert result.score_cap_reason


def test_a_capped_score_says_it_was_capped() -> None:
    """Needs a match that would otherwise score *above* the cap. Enough strong
    matches to outweigh one blocker, so the ceiling is doing visible work."""
    verdicts = match_requirements(
        [
            *[requirement(f"Python{i}", order=i) for i in range(4)],
            requirement("Rust", importance="CORE", order=4),
        ],
        profile(*[skill(f"Python{i}", experiences=(EXPERIENCE_ID,)) for i in range(4)]),
    )
    result = score_match(verdicts)

    assert result.overall_score == BLOCKER_CAP
    assert "Capped" in (result.score_cap_reason or "")


def test_a_score_already_below_the_cap_is_not_reported_as_capped() -> None:
    """The ceiling only applies when it actually lowered something. Claiming
    otherwise would blame the blocker for a score the arithmetic produced."""
    verdicts = match_requirements(
        [requirement("Python", order=0), requirement("Rust", importance="CORE", order=1)],
        profile(skill("Python", experiences=(EXPERIENCE_ID,))),
    )
    result = score_match(verdicts)

    assert result.has_blockers is True
    assert result.score_cap is None
    assert result.overall_score is not None
    assert result.overall_score < BLOCKER_CAP


# --- scoring ---------------------------------------------------------------------


def test_no_evidence_is_excluded_from_the_score_rather_than_scored_zero() -> None:
    """The goal's rule: an incomplete profile must not automatically reduce the
    score. Scoring an unknown as a failure is exactly that reduction."""
    verdicts = match_requirements(
        [
            requirement("Python", order=0),
            requirement("Kubernetes", "EXPERIENCE", years_min=3, order=1),
        ],
        profile(skill("Python", experiences=(EXPERIENCE_ID,)), years=None),
    )
    result = score_match(verdicts)

    no_evidence = [v for v in verdicts if v.status is MatchStatus.NO_EVIDENCE]
    assert no_evidence
    assert result.scored_requirements < result.total_requirements
    # Python alone is a strong match, so the score reflects only what we know.
    assert result.overall_score == 100


def test_an_empty_profile_produces_no_score_rather_than_zero() -> None:
    """Zero is a claim about the candidate. Null is a claim about our data."""
    verdicts = match_requirements([requirement("Python"), requirement("Rust")], profile())
    result = score_match(verdicts)

    assert result.overall_score is None
    assert result.alignment_label == "Not enough profile data"


def test_unknowns_alone_do_not_manufacture_a_score() -> None:
    """A posting whose only assessable requirement is an UNKNOWN would
    otherwise report the neutral 35 as though it were a measurement. A score
    needs at least one verdict that engaged with the profile."""
    verdicts = match_requirements(
        [
            requirement("Rust", order=0),
            requirement("Right to work", "WORK_AUTHORIZATION", order=1),
        ],
        profile(),
    )
    result = score_match(verdicts)

    assert {v.status for v in verdicts} == {MatchStatus.NO_EVIDENCE, MatchStatus.UNKNOWN}
    assert result.overall_score is None


def test_unknown_still_counts_once_something_was_assessed() -> None:
    """The documented 35 applies in every mixed case — it is only barred from
    being the sole basis of a number."""
    verdicts = match_requirements(
        [
            requirement("Python", order=0),
            requirement("Right to work", "WORK_AUTHORIZATION", order=1),
        ],
        profile(skill("Python", experiences=(EXPERIENCE_ID,))),
    )
    result = score_match(verdicts)

    assert result.overall_score is not None
    # 100 and 35, weighted 2 and 2 → 68 (rounded from 67.5).
    assert result.overall_score == 68


def test_preferred_requirements_move_the_score_only_slightly() -> None:
    """A posting with twenty nice-to-haves and four real requirements must
    still be scored on the four."""
    strong = profile(skill("Python", experiences=(EXPERIENCE_ID,)))
    base = score_match(match_requirements([requirement("Python", importance="CORE")], strong))

    with_preferences = score_match(
        match_requirements(
            [
                requirement("Python", importance="CORE", order=0),
                *[requirement(f"Extra{i}", importance="PREFERRED", order=i + 1) for i in range(5)],
            ],
            strong,
        )
    )

    assert base.overall_score == 100
    # Five unmet preferences against one core requirement: a real dent, but the
    # core requirement still dominates.
    assert with_preferences.overall_score is not None
    assert with_preferences.overall_score >= 50


def test_the_weighted_average_follows_the_documented_formula() -> None:
    from decimal import Decimal

    # (100*3 + 0*1) / 4 = 75
    assert weighted_score([(100, Decimal("3")), (0, Decimal("1"))]) == 75


def test_weighted_score_is_none_when_nothing_is_scorable() -> None:
    assert weighted_score([]) is None


def test_every_status_appears_in_the_counts() -> None:
    """A client rendering a bar should not have to know which statuses exist."""
    result = score_match(match_requirements([requirement("Python")], profile(skill("Python"))))

    assert set(result.status_counts) == {str(s) for s in MatchStatus}


# --- categories ------------------------------------------------------------------


def test_a_preferred_requirement_is_scored_as_a_preference() -> None:
    """Importance wins over type, or a posting could dilute its own technical
    score by listing optional extras."""
    result = verdict_for(
        [requirement("Kubernetes", "TECHNICAL_SKILL", "PREFERRED")], profile(skill("Python"))
    )

    assert result.category is MatchCategory.PREFERRED


def test_a_required_technical_skill_is_scored_as_technical() -> None:
    result = verdict_for(
        [requirement("Python", "TECHNICAL_SKILL", "CORE")], profile(skill("Python"))
    )

    assert result.category is MatchCategory.TECHNICAL


def test_the_projects_category_is_derived_from_evidence() -> None:
    """No requirement asks for "a project", so the category measures how much
    of the alignment is carried by things the user built."""
    project_id = uuid.uuid4()
    snapshot = profile(skill("Rust", projects=(project_id,)))
    snapshot.projects.append(
        ProjectEvidence(
            id=project_id,
            name="Route planner",
            summary="A solver for delivery routes.",
            description="Written in Rust.",
            start_date=None,
            end_date=None,
            has_repository=True,
            verification_status="USER_CONFIRMED",
            skill_ids=frozenset(),
        )
    )

    result = score_match(match_requirements([requirement("Rust")], snapshot))
    categories = {c.category for c in result.category_scores}

    assert MatchCategory.PROJECTS in categories


# --- experience ------------------------------------------------------------------


def test_meeting_the_years_asked_for_is_a_strong_match() -> None:
    result = verdict_for(
        [requirement("5+ years backend", "EXPERIENCE", years_min=5)],
        profile(skill("Python"), years=6),
    )

    assert result.status is MatchStatus.STRONG_MATCH


def test_years_are_not_treated_as_binary() -> None:
    """docs/05-ai-and-matching.md says so outright: four years against five is
    a partial match, not a gap."""
    result = verdict_for(
        [requirement("5+ years backend", "EXPERIENCE", years_min=5)],
        profile(skill("Python"), years=4),
    )

    assert result.status is MatchStatus.PARTIAL_MATCH


def test_far_too_few_years_is_a_gap() -> None:
    result = verdict_for(
        [requirement("10+ years backend", "EXPERIENCE", years_min=10)],
        profile(skill("Python"), years=1),
    )

    assert result.status is MatchStatus.GAP


def test_a_minimum_of_zero_does_not_claim_anything_was_asked_for() -> None:
    """Found on screen: *"You have 3 years against the 0 asked for."*

    "0-3 years experience in object-oriented development" parses to a minimum
    of zero, which is an invitation to juniors rather than a demand for
    nothing. The old sentence was broken grammar over an empty claim.
    """
    result = verdict_for(
        [requirement("0-3 years experience", "EXPERIENCE", years_min=0)],
        profile(skill("Python"), years=3),
    )

    assert "asked for" not in result.explanation
    assert "no minimum experience" in result.explanation
    assert "3 years" in result.explanation


def test_a_minimum_of_zero_still_scores_as_it_did() -> None:
    """The copy changed and the verdict did not, on purpose.

    Re-scoring on the way past a wording fix is exactly the silent re-ranking
    `MATCHING_ENGINE_VERSION` exists to make visible. Whether a requirement
    demanding nothing deserves STRONG_MATCH is DEV-011's question.
    """
    result = verdict_for(
        [requirement("0-3 years experience", "EXPERIENCE", years_min=0)],
        profile(skill("Python"), years=3),
    )

    assert result.status is MatchStatus.STRONG_MATCH


def test_a_stated_minimum_still_names_it() -> None:
    """The zero case must not swallow the ordinary one."""
    result = verdict_for(
        [requirement("5+ years backend", "EXPERIENCE", years_min=5)],
        profile(skill("Python"), years=6),
    )

    assert "6 years against the 5 asked for" in result.explanation


# --- recommendation ---------------------------------------------------------------


def test_a_full_match_recommends_applying_strongly() -> None:
    result = score_match(
        match_requirements(
            [requirement("Python", importance="CORE")],
            profile(skill("Python", experiences=(EXPERIENCE_ID,))),
        )
    )

    assert result.recommendation is Recommendation.STRONG_APPLY


def test_a_blocked_match_is_never_recommended_for_application() -> None:
    result = score_match(
        match_requirements(
            [requirement("Python", order=0), requirement("Rust", importance="CORE", order=1)],
            profile(skill("Python", experiences=(EXPERIENCE_ID,))),
        )
    )

    assert result.recommendation in {Recommendation.LOW_PRIORITY, Recommendation.PROBABLY_SKIP}


def test_the_recommendation_explains_itself() -> None:
    result = score_match(
        match_requirements([requirement("Rust", importance="CORE")], profile(skill("Python")))
    )

    assert result.recommendation_reasons


def test_an_unscoreable_match_recommends_considering_rather_than_skipping() -> None:
    """With no profile there is nothing to judge, and "skip" would be a
    decision rather than advice."""
    result = score_match(match_requirements([requirement("Python")], profile()))

    assert result.recommendation is Recommendation.CONSIDER


# --- determinism -------------------------------------------------------------------


def test_the_same_inputs_always_produce_the_same_result() -> None:
    """The property the whole engine rests on. If this fails, no score in the
    database can be reproduced or defended."""
    requirements = [
        requirement("Python", importance="CORE", order=0),
        requirement("Spring Boot", order=1),
        requirement("Rust", importance="CORE", order=2),
        requirement("5+ years", "EXPERIENCE", years_min=5, order=3),
        requirement("Right to work", "WORK_AUTHORIZATION", order=4),
    ]
    snapshot = profile(
        skill("Python", experiences=(EXPERIENCE_ID,)),
        skill("FastAPI"),
        with_experience=True,
    )

    first = score_match(match_requirements(requirements, snapshot))
    second = score_match(match_requirements(requirements, snapshot))

    assert first.overall_score == second.overall_score
    assert first.recommendation is second.recommendation
    assert first.status_counts == second.status_counts
    assert first.confidence == second.confidence
    assert first.category_scores_json() == second.category_scores_json()


def test_requirement_order_does_not_change_the_score() -> None:
    """Requirements are evaluated independently, so a posting cannot score
    differently for listing the same things in another order."""
    snapshot = profile(skill("Python", experiences=(EXPERIENCE_ID,)), skill("FastAPI"))
    forward = [
        requirement("Python", order=0),
        requirement("Rust", order=1),
        requirement("FastAPI", order=2),
    ]
    reversed_order = [
        requirement("FastAPI", order=0),
        requirement("Rust", order=1),
        requirement("Python", order=2),
    ]

    assert (
        score_match(match_requirements(forward, snapshot)).overall_score
        == score_match(match_requirements(reversed_order, snapshot)).overall_score
    )


def test_every_requirement_produces_exactly_one_verdict() -> None:
    """Traceability: the completion criteria require every requirement to have
    a result, and a silently dropped one would be invisible."""
    requirements = [requirement(f"Skill{i}", order=i) for i in range(7)]

    verdicts = match_requirements(requirements, profile(skill("Python")))

    assert len(verdicts) == len(requirements)
    assert {v.requirement_id for v in verdicts} == {r.id for r in requirements}


def test_every_verdict_carries_an_explanation() -> None:
    """An item nobody can explain is an item nobody can check."""
    requirements = [
        requirement("Python", order=0),
        requirement("Rust", importance="CORE", order=1),
        requirement("Right to work", "WORK_AUTHORIZATION", order=2),
        requirement("5+ years", "EXPERIENCE", years_min=5, order=3),
    ]

    for verdict in match_requirements(requirements, profile(skill("Python"))):
        assert verdict.explanation.strip()


# --- soft skills, which a profile has nowhere to record ------------------------


def test_an_unevidenced_soft_skill_is_unknown_rather_than_a_gap() -> None:
    """The asymmetry this file's own rule implies and the code used to miss.

    `_match_by_text` already refuses to call a keyword hit a strong match, on
    the grounds that a word in a project description is weak evidence. A word
    *missing* is weak evidence too, and it used to produce GAP — the strongest
    negative available — for a trait the profile has no field for.

    Found on a real posting: three soft skills, all marked REQUIRED, carrying
    2.00 apiece and 30% of the score between them, one of them scored zero for
    the absence of the word "analytical".
    """
    result = verdict_for(
        [requirement("Strong analytical and logical thinking", "SOFT_SKILL")],
        profile(skill("Python"), with_experience=True),
    )

    assert result.status is MatchStatus.UNKNOWN


def test_an_unevidenced_soft_skill_costs_less_than_a_real_gap() -> None:
    """UNKNOWN carries its documented 35 rather than a gap's zero.

    Not dropped from the number — that is NO_EVIDENCE's behaviour, and the
    profile here is not empty. This is the same treatment work authorisation
    already gets: counted, at the constant that says we could not tell, instead
    of at the zero that says we looked and it was not there.

    Compared against an identically weighted requirement the engine *can*
    assess, so the assertion is about the change rather than about a constant.
    """
    soft = score_match(
        match_requirements(
            [
                requirement("Python", order=0),
                requirement("Strong analytical thinking", "SOFT_SKILL", order=1),
            ],
            profile(skill("Python"), with_experience=True),
        )
    )
    assessable = score_match(
        match_requirements(
            [
                requirement("Python", order=0),
                requirement("Telecom billing", "DOMAIN_KNOWLEDGE", order=1),
            ],
            profile(skill("Python"), with_experience=True),
        )
    )

    assert soft.overall_score is not None and assessable.overall_score is not None
    assert soft.overall_score > assessable.overall_score


def test_domain_knowledge_still_carries_a_real_gap() -> None:
    """The other half of the same branch, and the reason this is not a blanket
    change. A career profile does record the domains someone has worked in, so
    finding no mention of telecom anywhere is genuine evidence about telecom.
    """
    result = verdict_for(
        [requirement("Telecom billing systems", "DOMAIN_KNOWLEDGE")],
        profile(skill("Python"), with_experience=True),
    )

    assert result.status is MatchStatus.GAP


def test_a_soft_skill_the_profile_does_mention_is_still_credited() -> None:
    """Only the negative side changed. A keyword hit remains a PARTIAL_MATCH,
    capped as it always was."""
    result = verdict_for(
        [requirement("Mentored engineers", "SOFT_SKILL")],
        profile(skill("Python"), with_experience=True),
    )

    assert result.status is MatchStatus.PARTIAL_MATCH


def test_a_soft_skill_can_never_block() -> None:
    """Even promoted to CORE by a posting that insists on it, an unevidencable
    trait must not cap the score — a blocker built from an absence the profile
    cannot express is exactly what UNKNOWN exists to prevent."""
    result = verdict_for(
        [requirement("Exceptional communication", "SOFT_SKILL", importance="CORE")],
        profile(skill("Python"), with_experience=True),
    )

    assert result.is_blocker is False
