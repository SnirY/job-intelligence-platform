"""The application lifecycle.

``docs/11-engineering-standards.md`` names application transitions in its
unit-test priorities, and this is why: the table is the only thing standing
between a Kanban board and a history that says an interview happened when it
did not.

The rules these protect:

- a stage cannot be un-happened;
- a sent application cannot go back to being a plan;
- an ending is reachable from anywhere, because processes really do end
  anywhere;
- every status has a defined answer, so a new one cannot be added without
  deciding where it leads.

No database, no clock. Everything here is a question about two enum values.
"""

from __future__ import annotations

import pytest

from jip_api.domain.applications.models import ApplicationStatus as S
from jip_api.domain.applications.transitions import (
    allowed_from,
    can_transition,
    refusal_reason,
)

BEFORE_APPLYING = [S.SAVED, S.INTERESTED, S.ANALYZING, S.PREPARING, S.READY_TO_APPLY]
AFTER_APPLYING = [S.APPLIED, S.HR_SCREEN, S.TECHNICAL_INTERVIEW, S.FINAL_INTERVIEW, S.OFFER]
ENDINGS = [S.REJECTED, S.WITHDRAWN, S.GHOSTED, S.ARCHIVED]


# --- the shape of the table -----------------------------------------------------


@pytest.mark.parametrize("status", list(S))
def test_every_status_has_an_answer(status: S) -> None:
    """A missing key would be a KeyError at the moment a user drags a card.

    This is the test that makes adding a fifteenth status a deliberate act: it
    fails until someone decides where the new one leads.
    """
    assert isinstance(allowed_from(status), frozenset)


def test_no_status_can_transition_to_itself_except_a_repeating_round() -> None:
    """Multi-round technical loops are real, and forcing a distinct status for
    round two would lose the count. Everything else self-looping would be a
    no-op that still writes an event."""
    self_looping = [status for status in S if can_transition(status, status)]

    assert self_looping == [S.TECHNICAL_INTERVIEW]


# --- preparation ----------------------------------------------------------------


@pytest.mark.parametrize("status", BEFORE_APPLYING)
def test_preparation_can_reach_applied(status: S) -> None:
    """Someone who already applied elsewhere must be able to record it without
    walking through every intermediate stage first."""
    assert can_transition(status, S.APPLIED)


def test_preparation_can_move_backwards() -> None:
    """It is the user's own workflow and nothing has left their hands, so
    changing your mind is not falsifying a record."""
    assert can_transition(S.PREPARING, S.INTERESTED)
    assert can_transition(S.READY_TO_APPLY, S.PREPARING)


# --- after submission -------------------------------------------------------------


def test_a_stage_cannot_be_un_happened() -> None:
    """The core rule. After submission the stages record what the employer did,
    and moving back would delete an interview that took place."""
    assert not can_transition(S.TECHNICAL_INTERVIEW, S.HR_SCREEN)
    assert not can_transition(S.FINAL_INTERVIEW, S.TECHNICAL_INTERVIEW)
    assert not can_transition(S.OFFER, S.FINAL_INTERVIEW)


def test_stages_may_be_skipped() -> None:
    """Plenty of companies go straight to a technical round, and a tracker that
    insisted on an HR screen would make the user invent one."""
    assert can_transition(S.APPLIED, S.TECHNICAL_INTERVIEW)
    assert can_transition(S.APPLIED, S.OFFER)
    assert can_transition(S.HR_SCREEN, S.FINAL_INTERVIEW)


@pytest.mark.parametrize("sent", AFTER_APPLYING)
@pytest.mark.parametrize("plan", BEFORE_APPLYING)
def test_a_sent_application_never_returns_to_preparation(sent: S, plan: S) -> None:
    """What happened after it was sent is a record, not a plan."""
    assert not can_transition(sent, plan)


# --- endings ----------------------------------------------------------------------


@pytest.mark.parametrize("status", BEFORE_APPLYING + AFTER_APPLYING)
@pytest.mark.parametrize("ending", ENDINGS)
def test_any_live_application_can_end(status: S, ending: S) -> None:
    """A company can go silent before replying and a user can withdraw while
    still preparing. Every ending is reachable from every live stage."""
    assert can_transition(status, ending)


@pytest.mark.parametrize("ending", [S.REJECTED, S.WITHDRAWN, S.GHOSTED])
def test_an_ended_application_can_only_be_filed_away(ending: S) -> None:
    assert allowed_from(ending) == frozenset({S.ARCHIVED})


def test_archived_is_the_one_true_dead_end() -> None:
    assert allowed_from(S.ARCHIVED) == frozenset()


@pytest.mark.parametrize("ending", ENDINGS)
def test_an_ending_cannot_become_a_different_ending(ending: S) -> None:
    """Rejected and ghosted say different things about what went wrong, and
    rewriting one as the other would corrupt the only signal there is."""
    others = {e for e in ENDINGS if e is not ending and e is not S.ARCHIVED}

    assert not any(can_transition(ending, other) for other in others)


# --- the vocabulary ----------------------------------------------------------------


def test_silence_is_its_own_outcome() -> None:
    """The funnel needs GHOSTED apart from REJECTED because they mean different
    things — and neither may become the other, which is what actually keeps
    them distinct."""
    assert S.GHOSTED.is_terminal
    assert S.REJECTED.is_terminal
    assert not can_transition(S.GHOSTED, S.REJECTED)
    assert not can_transition(S.REJECTED, S.GHOSTED)


@pytest.mark.parametrize("status", BEFORE_APPLYING)
def test_preparation_statuses_are_before_applying(status: S) -> None:
    assert status.is_before_applying


@pytest.mark.parametrize("status", AFTER_APPLYING + ENDINGS)
def test_everything_else_is_not(status: S) -> None:
    assert not status.is_before_applying


@pytest.mark.parametrize("status", BEFORE_APPLYING + AFTER_APPLYING)
def test_live_stages_are_active(status: S) -> None:
    assert status.is_active


# --- refusals ------------------------------------------------------------------------


def test_a_refusal_explains_rather_than_blames() -> None:
    reason = refusal_reason(S.TECHNICAL_INTERVIEW, S.HR_SCREEN)

    assert "un-happened" in reason
    assert "invalid" not in reason.lower()


def test_a_refusal_from_a_terminal_state_says_it_ended() -> None:
    reason = refusal_reason(S.REJECTED, S.OFFER)

    assert "ended as rejected" in reason
    assert "Archive it" in reason


def test_a_refusal_backwards_past_submission_names_the_reason() -> None:
    reason = refusal_reason(S.HR_SCREEN, S.PREPARING)

    assert "already been sent" in reason
    assert "a record, not a plan" in reason


def test_moving_somewhere_it_already_is_says_so_plainly() -> None:
    assert "already saved" in refusal_reason(S.SAVED, S.SAVED)
