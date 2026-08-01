"""A requirement the job title names is core, whatever the model said.

DEV-028. Across 31 requirements from two analyses of a real posting the model
assigned CORE zero times, so the 3.00 weight and ``BLOCKER_CAP`` — both gated
on CORE alone — had never applied to a real match. The prompt asked it to "use
sparingly", which is a statement about frequency rather than a test, and the
only reading that always satisfies it is never.

The prompt now gives a test. This is the half that holds when the model does
not follow it.
"""

from __future__ import annotations

from jip_api.application.jobs.analysis_pipeline import _named_in_title, _promote_title_skills
from jip_api.application.jobs.analysis_validation import RequirementDraft
from jip_api.domain.jobs.analysis import (
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
)
from jip_api.domain.matching.rules import can_block

Acme Networks_TITLE = "Acme Networks גיוס Junior Software Engineer C++ | עובדים Israel LinkedIn"


def draft(
    skill_name: str | None,
    importance: RequirementImportance = RequirementImportance.REQUIRED,
) -> RequirementDraft:
    return RequirementDraft(
        requirement_type=RequirementType.TECHNICAL_SKILL,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_text=skill_name or "something",
        normalized_text=skill_name or "something",
        confidence=90,
        source_order=0,
        skill_name=skill_name,
    )


# --- the promotion ------------------------------------------------------------


def test_the_skill_in_the_title_becomes_core() -> None:
    """The exact case that closed DEV-028: a posting titled for C++ whose C++
    requirement came back REQUIRED, twice, on two separate runs."""
    kept = _promote_title_skills([draft("C++")], Acme Networks_TITLE)

    assert kept[0].importance is RequirementImportance.CORE


def test_promotion_makes_the_blocker_cap_reachable() -> None:
    """The point of the whole change. ``can_block`` gates on CORE and nothing
    had ever produced one, so a cap the documentation describes as protecting
    the user had never applied to anything."""
    before = draft("C++")
    after = _promote_title_skills([before], Acme Networks_TITLE)[0]

    assert not can_block(before.importance)
    assert can_block(after.importance)


def test_a_skill_absent_from_the_title_is_left_alone() -> None:
    kept = _promote_title_skills([draft("Linux")], Acme Networks_TITLE)

    assert kept[0].importance is RequirementImportance.REQUIRED


def test_nothing_is_ever_moved_down() -> None:
    """Only promotes. A model that did mark something CORE keeps it, and a
    preference the title does not name stays a preference."""
    kept = _promote_title_skills(
        [draft("Kubernetes", RequirementImportance.PREFERRED)], Acme Networks_TITLE
    )

    assert kept[0].importance is RequirementImportance.PREFERRED


def test_a_requirement_with_no_resolved_skill_is_left_alone() -> None:
    """There is no name to look for, and matching the whole sentence against
    the title would promote on coincidence."""
    kept = _promote_title_skills([draft(None)], Acme Networks_TITLE)

    assert kept[0].importance is RequirementImportance.REQUIRED


def test_an_empty_title_promotes_nothing() -> None:
    """A URL import has a placeholder title until the page is fetched."""
    kept = _promote_title_skills([draft("C++")], "   ")

    assert kept[0].importance is RequirementImportance.REQUIRED


# --- the boundary test --------------------------------------------------------


def test_punctuation_heavy_skill_names_are_found() -> None:
    """The names a regex would need escaping for, which is why this is not one."""
    assert _named_in_title("C++", "Senior C++ Engineer")
    assert _named_in_title("C#", "C# Developer")
    assert _named_in_title(".NET", "Backend .NET Engineer")
    assert _named_in_title("F#", "F# Analyst")


def test_a_skill_name_inside_a_longer_word_does_not_count() -> None:
    """ "Go" is a language and "Google" is a company, and a plain substring test
    cannot tell a job at one from a job needing the other."""
    assert not _named_in_title("Go", "Software Engineer at Google")
    assert not _named_in_title("R", "Senior Ruby Engineer")
    assert not _named_in_title("Java", "JavaScript Developer")


def test_a_later_occurrence_still_counts() -> None:
    """The first hit can be the one inside a longer word. Finding it must not
    stop the search."""
    assert _named_in_title("Java", "JavaScript and Java Engineer")


def test_matching_ignores_case_and_surrounding_text() -> None:
    assert _named_in_title("c++", Acme Networks_TITLE)
    assert _named_in_title("PYTHON", "Senior python developer, remote")


def test_multi_word_skills_are_found() -> None:
    assert _named_in_title("Spring Boot", "Java / Spring Boot Engineer")
    assert not _named_in_title("Spring Boot", "Java Spring Engineer")
