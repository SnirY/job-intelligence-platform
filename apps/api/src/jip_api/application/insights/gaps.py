"""How much of a gap a skill actually is.

``docs/07-applications-and-career-intelligence.md`` names four states and does
not say how to reach them. This does, from evidence the profile already holds:

```text
STRONG_GAP     nothing on the profile
PARTIAL_GAP    on the profile, but not confirmed by the user
WEAK_EVIDENCE  confirmed, and demonstrated nowhere
NO_GAP         confirmed, and demonstrated in real work
```

The middle two are the reason this is not a boolean. A skill listed once and
never attached to a job or a project is a claim; the same skill attached to two
roles is a record. ``docs/03-domain-model.md`` built `ExperienceSkill` and
`ProjectSkill` to keep that difference, and this is where it earns its keep.

Nothing here reads a match score. Gap state is a statement about the user's own
profile, so it stays true whatever the matching weights turn out to be —
which is the property DEV-026 costs everything else on this screen.
"""

from __future__ import annotations

import enum

from jip_api.application.matching.evidence import STRONG_VERIFICATION, SkillEvidence


class GapState(enum.StrEnum):
    """The four from ``docs/07``, strongest gap first."""

    STRONG_GAP = "STRONG_GAP"
    PARTIAL_GAP = "PARTIAL_GAP"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    NO_GAP = "NO_GAP"


GAP_SEVERITY: dict[GapState, int] = {
    GapState.STRONG_GAP: 3,
    GapState.PARTIAL_GAP: 2,
    GapState.WEAK_EVIDENCE: 1,
    GapState.NO_GAP: 0,
}
"""For ordering. Not a weight and not a score — nothing multiplies by this.

It exists so "worst gap first" is one declared ordering rather than a sort key
written out at each call site, and so a state added later has to be placed here
deliberately.
"""


def gap_state(held: SkillEvidence | None) -> GapState:
    """What kind of gap this skill is, given what the profile says about it.

    ``held`` is None when the skill is not on the profile at all.
    """
    if held is None:
        return GapState.STRONG_GAP

    if held.verification_status not in STRONG_VERIFICATION:
        # On the profile because something inferred it — a resume import, most
        # often — and the user has never said yes. `docs/06` forbids treating
        # that as a fact elsewhere, and treating it as covering a requirement
        # here would be the same mistake in a different place.
        return GapState.PARTIAL_GAP

    if held.demonstration_count == 0:
        return GapState.WEAK_EVIDENCE

    return GapState.NO_GAP


def is_gap(state: GapState) -> bool:
    """Whether this belongs on a list headed "gaps".

    WEAK_EVIDENCE counts. A confirmed skill with nowhere to point is exactly
    the thing a posting will ask about and the profile cannot answer, and
    leaving it off would make the list agree with the user's optimism rather
    than with their evidence.
    """
    return state is not GapState.NO_GAP
