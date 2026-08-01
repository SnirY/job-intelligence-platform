"""Gap states, and the ordering that puts the worst first.

``docs/07`` names four states and does not say how to reach them. These fix the
mapping, and the middle two are the reason it is not a boolean:

- a skill an import inferred and the user never confirmed is a claim;
- a skill the user confirmed but attached to no job or project is a claim they
  believe;
- a skill attached to real work is a record.

Nothing here reads a match score, which is the property that makes Phase 10
safe to build while DEV-026 is open.
"""

from __future__ import annotations

import uuid

from jip_api.application.insights.demand import DemandReport, SkillDemand, build_gaps
from jip_api.application.insights.gaps import GAP_SEVERITY, GapState, gap_state, is_gap
from jip_api.application.matching.evidence import SkillEvidence


def held(
    *,
    verification: str = "USER_CONFIRMED",
    experiences: tuple[uuid.UUID, ...] = (),
    projects: tuple[uuid.UUID, ...] = (),
) -> SkillEvidence:
    return SkillEvidence(
        user_skill_id=uuid.uuid4(),
        skill_id=uuid.uuid4(),
        canonical_name="Python",
        normalized_name="python",
        proficiency="ADVANCED",
        years_of_experience=4,
        last_used_year=2026,
        verification_status=verification,
        experience_ids=experiences,
        project_ids=projects,
    )


# --- the four states ----------------------------------------------------------


def test_a_skill_absent_from_the_profile_is_a_strong_gap() -> None:
    assert gap_state(None) is GapState.STRONG_GAP


def test_an_unconfirmed_skill_is_a_partial_gap() -> None:
    """On the profile because a resume import inferred it, and never confirmed.

    `docs/06` forbids treating that as a fact when writing a resume claim.
    Treating it as covering a requirement here would be the same mistake in a
    different place.
    """
    assert gap_state(held(verification="AI_INFERRED")) is GapState.PARTIAL_GAP
    assert gap_state(held(verification="UNVERIFIED")) is GapState.PARTIAL_GAP


def test_a_confirmed_skill_demonstrated_nowhere_is_weak_evidence() -> None:
    """The distinction `ExperienceSkill` and `ProjectSkill` exist to keep."""
    assert gap_state(held()) is GapState.WEAK_EVIDENCE


def test_a_confirmed_skill_used_in_real_work_is_no_gap() -> None:
    assert gap_state(held(experiences=(uuid.uuid4(),))) is GapState.NO_GAP
    assert gap_state(held(projects=(uuid.uuid4(),))) is GapState.NO_GAP


def test_evidence_backed_counts_as_confirmed() -> None:
    """Both strong statuses, not just the one a person clicked."""
    backed = held(verification="EVIDENCE_BACKED", projects=(uuid.uuid4(),))

    assert gap_state(backed) is GapState.NO_GAP


# --- what counts as a gap -----------------------------------------------------


def test_weak_evidence_belongs_on_the_gap_list() -> None:
    """A confirmed skill with nowhere to point is exactly what a posting will
    ask about and the profile cannot answer. Leaving it off would make the list
    agree with the user's optimism rather than with their evidence.
    """
    assert is_gap(GapState.WEAK_EVIDENCE)
    assert not is_gap(GapState.NO_GAP)


def test_every_state_has_a_severity() -> None:
    """A missing member would raise KeyError inside the sort, on whichever
    account first produced that state."""
    assert set(GAP_SEVERITY) == set(GapState)


def test_severity_orders_the_states_as_declared() -> None:
    """The enum is written strongest-gap-first, and the ordering has to agree —
    two orderings that disagree would put the least urgent gap at the top."""
    by_severity = sorted(GAP_SEVERITY, key=lambda state: -GAP_SEVERITY[state])

    assert by_severity == list(GapState)


# --- ordering the list --------------------------------------------------------


def demand(name: str, jobs: int, state: GapState) -> SkillDemand:
    return SkillDemand(
        key=name.lower(),
        skill_id=uuid.uuid4(),
        name=name,
        catalogued=True,
        jobs=jobs,
        share=50,
        state=state,
        held=False,
    )


def test_the_worst_gap_comes_first_even_when_asked_for_less() -> None:
    """`docs/07`'s own point: a gap in a strong opportunity can outweigh one
    that merely appears more often."""
    report = DemandReport(
        analysed_jobs=4,
        skills=[
            demand("Linux", 4, GapState.WEAK_EVIDENCE),
            demand("Rust", 1, GapState.STRONG_GAP),
        ],
    )

    assert [gap.name for gap in build_gaps(report)] == ["Rust", "Linux"]


def test_within_a_severity_the_more_demanded_comes_first() -> None:
    report = DemandReport(
        analysed_jobs=6,
        skills=[
            demand("Go", 1, GapState.STRONG_GAP),
            demand("Rust", 5, GapState.STRONG_GAP),
        ],
    )

    assert [gap.name for gap in build_gaps(report)] == ["Rust", "Go"]


def test_a_covered_skill_is_not_a_gap() -> None:
    report = DemandReport(
        analysed_jobs=3,
        skills=[demand("Python", 3, GapState.NO_GAP), demand("Rust", 1, GapState.STRONG_GAP)],
    )

    assert [gap.name for gap in build_gaps(report)] == ["Rust"]


def test_the_order_is_stable_between_two_identical_reports() -> None:
    """Ties break alphabetically rather than by dictionary order, so reloading
    the page does not reshuffle the list."""
    skills = [
        demand("Redis", 2, GapState.STRONG_GAP),
        demand("Kafka", 2, GapState.STRONG_GAP),
        demand("Docker", 2, GapState.STRONG_GAP),
    ]

    first = [gap.name for gap in build_gaps(DemandReport(analysed_jobs=2, skills=skills))]
    second = [gap.name for gap in build_gaps(DemandReport(analysed_jobs=2, skills=skills))]

    assert first == second == ["Docker", "Kafka", "Redis"]
