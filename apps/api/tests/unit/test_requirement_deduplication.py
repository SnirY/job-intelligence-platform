"""One skill asked for twice becomes one requirement.

DEV-025. A posting that names a technology in its opening prose and again in
its requirement list, at different strengths, produced two requirements for it.
Both readings are faithful taken alone; nothing reconciled them.

They are duplicates in the sense that decides the score: the matcher resolves
both against the same profile skill and reaches the same verdict for both, so
the pair counts one piece of evidence twice — on both sides. Found on a real
LinkedIn posting where Linux scored MATCH twice and carried 2.50 of weight
against C++'s 2.00, in a C++ role.
"""

from __future__ import annotations

import uuid

from jip_api.application.jobs.analysis_pipeline import STRENGTH_ORDER, _strongest_per_skill
from jip_api.application.jobs.analysis_validation import RequirementDraft
from jip_api.domain.jobs.analysis import (
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
)
from jip_api.domain.matching.rules import IMPORTANCE_WEIGHTS

LINUX = uuid.uuid4()
CPLUSPLUS = uuid.uuid4()


def draft(
    text: str,
    importance: RequirementImportance,
    *,
    order: int = 0,
    skill_name: str | None = None,
) -> RequirementDraft:
    return RequirementDraft(
        requirement_type=RequirementType.TECHNICAL_SKILL,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source_text=text,
        normalized_text=text,
        confidence=90,
        source_order=order,
        skill_name=skill_name,
    )


def test_the_stronger_of_two_mentions_survives() -> None:
    """The exact pair from the network-analytics posting."""
    required = draft("Linux environment familiarity", RequirementImportance.REQUIRED, order=0)
    preferred = draft(
        "Familiarity with Linux environment", RequirementImportance.PREFERRED, order=1
    )

    kept = _strongest_per_skill([(required, LINUX), (preferred, LINUX)])

    assert kept == [required]


def test_the_stronger_mention_survives_whichever_came_first() -> None:
    """Order in the posting must not decide which strength wins — the opening
    prose mentions things before the requirement list does."""
    preferred = draft("Linux is a plus", RequirementImportance.PREFERRED, order=0)
    required = draft("Linux required", RequirementImportance.REQUIRED, order=1)

    kept = _strongest_per_skill([(preferred, LINUX), (required, LINUX)])

    assert kept == [required]


def test_different_skills_are_both_kept() -> None:
    linux = draft("Linux", RequirementImportance.REQUIRED)
    cpp = draft("C++", RequirementImportance.REQUIRED)

    kept = _strongest_per_skill([(linux, LINUX), (cpp, CPLUSPLUS)])

    assert kept == [linux, cpp]


def test_unresolved_requirements_are_never_merged() -> None:
    """Two phrases that resolve to no catalogued skill are not known to be the
    same thing, however alike they read. The matcher treats them separately
    too, so merging here would lose a requirement rather than a duplicate."""
    first = draft("Strong analytical thinking", RequirementImportance.REQUIRED, order=0)
    second = draft("Strong logical thinking", RequirementImportance.REQUIRED, order=1)

    kept = _strongest_per_skill([(first, None), (second, None)])

    assert kept == [first, second]


def test_a_tie_keeps_the_earlier_mention() -> None:
    """The drafts arrive in the posting's order, and the first time it asks for
    something is the wording the reader will recognise."""
    first = draft("Linux experience", RequirementImportance.REQUIRED, order=0)
    second = draft("Experience on Linux", RequirementImportance.REQUIRED, order=1)

    kept = _strongest_per_skill([(first, LINUX), (second, LINUX)])

    assert kept == [first]


def test_three_mentions_collapse_to_the_strongest() -> None:
    weak = draft("Linux a bonus", RequirementImportance.OPTIONAL, order=0)
    strong = draft("Linux essential", RequirementImportance.CORE, order=1)
    middle = draft("Linux required", RequirementImportance.REQUIRED, order=2)

    kept = _strongest_per_skill([(weak, LINUX), (strong, LINUX), (middle, LINUX)])

    assert kept == [strong]


def test_the_strength_order_agrees_with_the_scoring_weights() -> None:
    """The mechanism instead of a comment asking someone to remember.

    Resolving a duplicate in favour of the *stronger* requirement only means
    anything if "stronger" is what the matcher also weighs more. Two orderings
    that drift apart would keep the mention that counts for less, silently.
    """
    by_strength = sorted(STRENGTH_ORDER, key=lambda i: STRENGTH_ORDER[i])
    by_weight = sorted(IMPORTANCE_WEIGHTS, key=lambda i: IMPORTANCE_WEIGHTS[i])

    assert by_strength == by_weight


def test_every_importance_has_a_strength() -> None:
    """A missing member would raise KeyError inside the worker, on a posting
    whose shape nobody predicted."""
    assert set(STRENGTH_ORDER) == set(RequirementImportance)
