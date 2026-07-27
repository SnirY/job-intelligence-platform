"""The bridge between the two seniority vocabularies.

There are two on purpose: :class:`AnalyzedSeniority` is what a *posting*
implies, :class:`Seniority` is what a *person* aims for. Phase 6 has to compare
them, and this mapping exists so it does not invent one.
"""

from __future__ import annotations

import pytest

from jip_api.domain.career.models import Seniority
from jip_api.domain.jobs.analysis import AnalyzedSeniority, to_target_seniority


@pytest.mark.parametrize(
    ("analyzed", "target"),
    [
        (AnalyzedSeniority.INTERN, Seniority.INTERN),
        (AnalyzedSeniority.ENTRY_LEVEL, Seniority.JUNIOR),
        (AnalyzedSeniority.JUNIOR, Seniority.JUNIOR),
        (AnalyzedSeniority.MID, Seniority.MID),
        (AnalyzedSeniority.SENIOR, Seniority.SENIOR),
        (AnalyzedSeniority.STAFF_PLUS, Seniority.STAFF),
    ],
)
def test_maps_a_known_level(analyzed: AnalyzedSeniority, target: Seniority) -> None:
    assert to_target_seniority(analyzed) is target


def test_unknown_maps_to_nothing() -> None:
    """A comparison against a level nobody established is worse than no
    comparison, so this returns None rather than picking a middle value."""
    assert to_target_seniority(AnalyzedSeniority.UNKNOWN) is None


def test_staff_plus_lands_on_the_floor_of_its_band() -> None:
    """STAFF_PLUS covers staff, principal, and above. Mapping to the lowest of
    those is the only choice that cannot overstate what the posting said."""
    assert to_target_seniority(AnalyzedSeniority.STAFF_PLUS) is Seniority.STAFF


def test_every_analyzed_level_is_accounted_for() -> None:
    """A new member added without a mapping would silently return None, which
    reads as "unknown" — a wrong answer that looks like an honest one."""
    unmapped = [
        level
        for level in AnalyzedSeniority
        if level is not AnalyzedSeniority.UNKNOWN and to_target_seniority(level) is None
    ]

    assert not unmapped, f"no target seniority for {unmapped}"
