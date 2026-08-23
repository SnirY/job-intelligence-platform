"""What we noticed about a posting, as distinct from what we concluded about fit.

`docs/05-ai-and-matching.md` separates what a posting *said* from what we read
into it. This module is the second half of that separation applied to a
different question: not "does this person fit the role" but "is this posting
what it claims to be".

**There is no legitimacy score, and that absence is the design.** A number is
something that can be averaged, weighted, ranked and eventually folded into
another number — and the one rule this must keep is that a concern never moves
the match. A list of named, evidenced concerns cannot be folded into anything
without someone deciding to write the code that does it, which is exactly the
friction wanted here.

Nothing in this module is persisted. Every input is already stored — the
posting text, the dates — and the rules are versioned by living in code, so a
concern is derived on read. A stored verdict would go stale against a rule that
improved, and a stale verdict about whether something is a scam is worse than no
verdict.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PostingConcernType(enum.StrEnum):
    """What was noticed. One member per rule, so a concern can be acted on
    without parsing its prose."""

    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    """The posting asks the applicant for money.

    The strongest signal here by a distance. A legitimate employer does not
    charge to be hired, and no reading of an ordinary posting produces this.
    """

    OFF_PLATFORM_CONTACT = "OFF_PLATFORM_CONTACT"
    """Applicants are directed to a personal messaging account.

    A recruiter using a company address is normal. A posting that routes hiring
    through WhatsApp or Telegram is routing it somewhere with no employer
    identity attached, which is the mechanism most hiring scams need.
    """

    THIN_DESCRIPTION = "THIN_DESCRIPTION"
    """There is very little posting text.

    Named for what it measures rather than what it might mean. This is not
    evidence of a scam and must not be worded as if it were — plenty of real
    postings are short. What it says is that there is not much here to judge,
    which is worth a reader knowing before they spend an evening on it.
    """

    LONG_RUNNING = "LONG_RUNNING"
    """The posting has been open for a long time.

    A role advertised continuously for months is sometimes a pipeline-building
    listing with no headcount behind it. Sometimes it is a hard role to fill.
    The concern says how long, and does not claim to know which.
    """


class ConcernConfidence(enum.StrEnum):
    """How much the rule that raised this can support.

    Present so the screen can order concerns and word them differently, and
    deliberately not a number — see the module docstring. Three levels, because
    a fourth would be a distinction none of the current rules can actually
    defend.
    """

    OBSERVED = "OBSERVED"
    """A fact about the posting, stated without interpretation. `THIN_DESCRIPTION`
    and `LONG_RUNNING` are measurements."""

    SUSPICIOUS = "SUSPICIOUS"
    """A pattern that usually means something is wrong, and occasionally does
    not."""

    NEAR_CERTAIN = "NEAR_CERTAIN"
    """Something a legitimate posting does not do."""


@dataclass(frozen=True, slots=True)
class PostingConcern:
    """One thing noticed, and what in the posting caused it."""

    type: PostingConcernType
    confidence: ConcernConfidence

    summary: str
    """What was noticed, in words safe to show. States the observation, never a
    verdict about the employer — `docs/08-ui-ux.md` on not softening a blocker
    cuts both ways, and asserting fraud on a regex would be the same defect in
    the opposite direction."""

    evidence: str | None = None
    """The posting's own words, quoted.

    The same discipline the matcher uses: a reading that cannot point at what
    produced it is a reading the user cannot check. `None` only where the rule
    measures rather than reads — there is no phrase to quote for "this posting
    is 40 characters long".
    """


@dataclass(frozen=True, slots=True)
class LegitimacyReading:
    """Every concern raised about one posting.

    Carries no score, no rating and no overall verdict. What a reader gets is
    the list and its length, and if the list is empty that means **no rule
    fired**, which is not the same as "this posting is trustworthy". The screen
    has to say the weaker of those two things.
    """

    concerns: list[PostingConcern] = field(default_factory=list)

    @property
    def has_concerns(self) -> bool:
        return bool(self.concerns)
