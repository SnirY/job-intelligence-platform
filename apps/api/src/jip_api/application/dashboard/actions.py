"""What the user should do next, derived rather than guessed.

``docs/07-applications-and-career-intelligence.md`` asks for "a small
prioritized set, not dozens of recommendations", and requires every insight to
carry an observation, its evidence, and a suggested action. It also says, for
this phase: descriptive analytics and rule-based insights, and explicitly *not*
a model trained on a personal dataset of a few dozen rows.

So every action here is a fact about the user's own data with a link attached.
Nothing is scored, ranked by a learned weight, or phrased as a prediction. The
`reason` on each one is the evidence, written so it can be checked against the
screen it points at — an action a user cannot verify is a recommendation they
have to take on trust, which is the thing this product is built not to be.

**Order is priority.** ``ACTION_ORDER`` is the whole ranking: a blocked
prerequisite comes before a stale result, which comes before an opportunity, so
the list reads top-down as "fix this, then refresh that, then go do the work".
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from dataclasses import dataclass


class ActionKind(enum.StrEnum):
    """The rule that produced an action.

    Named for the situation rather than the button, so the frontend chooses the
    wording and this stays a statement about the data.
    """

    BUILD_PROFILE = "BUILD_PROFILE"
    """Nothing to match against yet."""

    ANALYSE_JOB = "ANALYSE_JOB"
    """A saved job nobody has read into requirements."""

    RETRY_ANALYSIS = "RETRY_ANALYSIS"
    """An analysis that failed and can be run again."""

    MATCH_JOB = "MATCH_JOB"
    """An analysed job never compared against the profile."""

    REFRESH_MATCH = "REFRESH_MATCH"
    """A match whose inputs have since changed."""

    PREPARE_APPLICATION = "PREPARE_APPLICATION"
    """A good match with no application started."""

    FOLLOW_UP = "FOLLOW_UP"
    """An application sent a while ago with no movement since."""


ACTION_ORDER: tuple[ActionKind, ...] = (
    ActionKind.BUILD_PROFILE,
    ActionKind.RETRY_ANALYSIS,
    ActionKind.ANALYSE_JOB,
    ActionKind.MATCH_JOB,
    ActionKind.REFRESH_MATCH,
    ActionKind.FOLLOW_UP,
    ActionKind.PREPARE_APPLICATION,
)
"""Priority, most blocking first.

An empty profile comes first because every other action produces a meaningless
answer without one. A failed analysis outranks an unstarted one: the user
already asked for that, and a retry is one click against work already paid for.
Preparing an application sits last — it is the largest piece of work on the
list, and the only one that is not repairing something.
"""

MAX_ACTIONS = 5
"""The "small prioritized set" the goal asks for.

Five rather than a screenful, because a list long enough to need scanning is a
list that gets ignored, and the ones past the fold are by construction the
least urgent.
"""

FOLLOW_UP_AFTER_DAYS = 14
"""How long a sent application may sit before it is worth chasing.

Two weeks is a convention, not a measurement, and it is the only number in this
module that is not read from the data. It is stated here rather than inlined so
DEV-011 can find it when there is enough history to calibrate against.
"""

GOOD_MATCH_SCORE = 60
"""The score at which an unstarted application becomes worth suggesting.

Also a reasoned guess, and also flagged for DEV-011. It is deliberately not one
of the alignment band edges: those describe how a score reads, and this decides
whether to interrupt someone, which is a different question.
"""


@dataclass(frozen=True, slots=True)
class NextAction:
    """One thing worth doing, with the fact that produced it."""

    kind: ActionKind
    subject: str
    """What it is about, in the user's words — a job title, usually."""

    reason: str
    """The evidence. Checkable against the screen this points at."""

    job_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None


def rank(actions: list[NextAction]) -> list[NextAction]:
    """Most blocking first, capped at :data:`MAX_ACTIONS`.

    Stable within a kind, so the caller's own ordering — newest job, oldest
    application — survives.
    """
    order = {kind: index for index, kind in enumerate(ACTION_ORDER)}
    return sorted(actions, key=lambda action: order[action.kind])[:MAX_ACTIONS]


def is_stale_application(applied_at: dt.datetime | None, now: dt.datetime) -> bool:
    """Whether a sent application has gone quiet for long enough to chase.

    ``applied_at`` is null for an application that was never sent, which is not
    the same as one sent today — the first has nothing to follow up.
    """
    if applied_at is None:
        return False
    moment = applied_at if applied_at.tzinfo else applied_at.replace(tzinfo=dt.UTC)
    return (now - moment).days >= FOLLOW_UP_AFTER_DAYS
