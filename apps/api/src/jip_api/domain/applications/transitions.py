"""Which status changes are legal, and why.

``docs/07-applications-and-career-intelligence.md`` lists fourteen statuses and
no edges between them. Left unconstrained, a Kanban board would happily drag a
REJECTED card back to HR_SCREEN and the funnel would report an interview that
never happened.

So the edges are written down here, explicitly, in the domain layer — the same
shape as the resume lifecycle's allowed transitions and the matching engine's
transferability table, and for the same reason: a rule that lives in a table can
be read, tested, and changed on purpose. ``docs/11-engineering-standards.md``
names application transitions in its unit-test priorities.

Pure. No database, no clock, no user. Everything here is a question about two
enum values.
"""

from __future__ import annotations

from jip_api.domain.applications.models import ApplicationStatus

S = ApplicationStatus

_ENDINGS: frozenset[ApplicationStatus] = frozenset({S.REJECTED, S.WITHDRAWN, S.GHOSTED, S.ARCHIVED})
"""Reachable from anywhere.

A process can end at any point: a company can go silent before replying, and a
user can withdraw while still preparing. Enumerating these against every stage
would be fourteen near-identical rows that all say the same thing.
"""

_FORWARD: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    # Preparation. Free movement, because it is the user's own workflow and
    # nothing has left their hands — going back from PREPARING to INTERESTED is
    # a change of mind, not a falsified record.
    S.SAVED: frozenset({S.INTERESTED, S.ANALYZING, S.PREPARING, S.READY_TO_APPLY, S.APPLIED}),
    S.INTERESTED: frozenset({S.SAVED, S.ANALYZING, S.PREPARING, S.READY_TO_APPLY, S.APPLIED}),
    S.ANALYZING: frozenset({S.INTERESTED, S.PREPARING, S.READY_TO_APPLY, S.APPLIED}),
    S.PREPARING: frozenset({S.INTERESTED, S.ANALYZING, S.READY_TO_APPLY, S.APPLIED}),
    S.READY_TO_APPLY: frozenset({S.PREPARING, S.APPLIED}),
    # After submission the process belongs to the employer, and the stages
    # record what they did. Skipping ahead is allowed — plenty of companies go
    # straight to a technical round — but going back is not, because that would
    # mean un-happening an interview that took place.
    S.APPLIED: frozenset({S.HR_SCREEN, S.TECHNICAL_INTERVIEW, S.FINAL_INTERVIEW, S.OFFER}),
    S.HR_SCREEN: frozenset({S.TECHNICAL_INTERVIEW, S.FINAL_INTERVIEW, S.OFFER}),
    S.TECHNICAL_INTERVIEW: frozenset({S.TECHNICAL_INTERVIEW, S.FINAL_INTERVIEW, S.OFFER}),
    S.FINAL_INTERVIEW: frozenset({S.OFFER}),
    S.OFFER: frozenset(),
    # An ending goes nowhere but the filing cabinet. ARCHIVED is not an outcome
    # — it is the user tidying up — so every other ending may reach it, and it
    # reaches nothing.
    S.REJECTED: frozenset(),
    S.WITHDRAWN: frozenset(),
    S.GHOSTED: frozenset(),
    S.ARCHIVED: frozenset(),
}
"""Deliberate forward edges, before the endings are added.

``TECHNICAL_INTERVIEW`` includes itself: multi-round technical loops are normal,
and forcing a user to invent a distinct status for round two would lose the
count. It is the one self-edge, because it is the one stage that genuinely
repeats.
"""


def allowed_from(status: ApplicationStatus) -> frozenset[ApplicationStatus]:
    """Every status ``status`` may legally move to.

    Used by the API to tell the UI which columns a card may be dropped into, so
    the board and the endpoint cannot disagree about what is possible — the same
    ``can_x`` / ``blocking_reason`` pattern the match and tailoring endpoints
    already use.
    """
    if status is S.ARCHIVED:
        # The one true dead end. Everything else can still be filed away.
        return frozenset()

    if status.is_terminal:
        # An ending may be filed, and nothing else. Rejected and ghosted say
        # different things about what went wrong, so letting one become the
        # other would corrupt the only outcome signal the funnel has — and it
        # would do it silently, by looking like an ordinary correction.
        return frozenset({S.ARCHIVED})

    # Endings are reachable from any *live* stage: a company can go silent
    # before replying, and a user can withdraw while still preparing.
    return _FORWARD[status] | _ENDINGS


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in allowed_from(current)


def refusal_reason(current: ApplicationStatus, target: ApplicationStatus) -> str:
    """Why a move was refused, in words worth showing someone.

    A bare "invalid transition" tells the user nothing about what they did.
    These distinguish the two cases that actually occur, because they call for
    different responses: one is a mistake, the other is the record protecting
    itself.
    """
    if current is target:
        return f"This application is already {_label(current)}."

    if current.is_terminal:
        return (
            f"This application ended as {_label(current)}, and its history is kept as it "
            "happened. Archive it, or add a note if something changed."
        )

    if not current.is_before_applying and target.is_before_applying:
        return (
            f"This application has already been sent, so it cannot go back to "
            f"{_label(target)}. What happened after it was sent is a record, not a plan."
        )

    return (
        f"{_label(current)} does not lead to {_label(target)}. A stage cannot be "
        "un-happened once it is recorded."
    )


def _label(status: ApplicationStatus) -> str:
    return str(status).replace("_", " ").lower()
