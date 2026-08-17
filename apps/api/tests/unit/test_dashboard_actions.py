"""What the dashboard tells the user to do next.

The rules are deterministic and the ordering is the whole recommendation
engine, so this is where Phase 9's only real logic lives. ``docs/07`` asks for
"a small prioritized set, not dozens", every item carrying its evidence.

What these protect:

- the most blocking thing is first, whatever order the rules ran in;
- the list is capped, so a user with forty jobs is not handed forty chores;
- an application that was never sent is never chased.
"""

from __future__ import annotations

import datetime as dt

from jip_api.application.dashboard.actions import (
    ACTION_ORDER,
    MAX_ACTIONS,
    ActionKind,
    NextAction,
    is_stale_application,
    rank,
)

NOW = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC)


def action(kind: ActionKind, subject: str = "A job") -> NextAction:
    return NextAction(kind=kind, subject=subject, reason="because")


# --- priority -----------------------------------------------------------------


def test_the_blocking_action_comes_first() -> None:
    """An empty profile makes every other answer meaningless, so it outranks
    them however late its rule happens to run."""
    ranked = rank(
        [
            action(ActionKind.PREPARE_APPLICATION),
            action(ActionKind.MATCH_JOB),
            action(ActionKind.BUILD_PROFILE),
        ]
    )

    assert ranked[0].kind is ActionKind.BUILD_PROFILE


def test_a_failed_analysis_outranks_one_never_started() -> None:
    """The user already asked for that one, and a retry is a click against work
    already paid for."""
    ranked = rank([action(ActionKind.ANALYSE_JOB), action(ActionKind.RETRY_ANALYSIS)])

    assert [item.kind for item in ranked] == [
        ActionKind.RETRY_ANALYSIS,
        ActionKind.ANALYSE_JOB,
    ]


def test_preparing_an_application_comes_last() -> None:
    """The largest piece of work on the list, and the only one not repairing
    something. Asserted against a set small enough to survive the cap, so the
    claim is about the ordering rather than about what got truncated."""
    ranked = rank(
        [
            action(ActionKind.PREPARE_APPLICATION),
            action(ActionKind.FOLLOW_UP),
            action(ActionKind.REFRESH_MATCH),
        ]
    )

    assert ranked[-1].kind is ActionKind.PREPARE_APPLICATION


def test_the_list_is_capped() -> None:
    """Twelve saved jobs must not produce twelve chores. A list long enough to
    need scanning is one that gets ignored."""
    ranked = rank([action(ActionKind.ANALYSE_JOB, f"Job {i}") for i in range(12)])

    assert len(ranked) == MAX_ACTIONS


def test_the_only_work_that_is_not_repair_keeps_a_slot() -> None:
    """`PREPARE_APPLICATION` ranks last on merit and was therefore cut on every
    account with five other things pending — so the busier someone got, the more
    certain it became that the product only ever offered maintenance.

    Six rules firing, and the reserved kind is the one that survives the cap.
    """
    ranked = rank(
        [
            action(ActionKind.RETRY_ANALYSIS),
            action(ActionKind.ANALYSE_JOB),
            action(ActionKind.MATCH_JOB),
            action(ActionKind.REFRESH_MATCH),
            action(ActionKind.FOLLOW_UP),
            action(ActionKind.PREPARE_APPLICATION, "Senior Backend Engineer"),
        ]
    )

    assert len(ranked) == MAX_ACTIONS
    assert ranked[-1].kind is ActionKind.PREPARE_APPLICATION
    assert ranked[-1].subject == "Senior Backend Engineer"


def test_reserving_a_slot_never_overtakes_a_blocker() -> None:
    """A reservation, not a promotion. It costs the sixth item — which by
    construction is the least urgent thing that would have been shown — and
    never the first, which is the most blocking.
    """
    ranked = rank(
        [
            action(ActionKind.BUILD_PROFILE),
            action(ActionKind.RETRY_ANALYSIS),
            action(ActionKind.ANALYSE_JOB),
            action(ActionKind.MATCH_JOB),
            action(ActionKind.REFRESH_MATCH),
            action(ActionKind.PREPARE_APPLICATION),
        ]
    )

    assert ranked[0].kind is ActionKind.BUILD_PROFILE
    assert [item.kind for item in ranked[:4]] == list(ACTION_ORDER[:4])


def test_nothing_is_reserved_when_there_is_nothing_to_reserve() -> None:
    """The cap is unchanged for an account with no application to prepare."""
    ranked = rank([action(ActionKind.ANALYSE_JOB, f"Job {i}") for i in range(12)])

    assert len(ranked) == MAX_ACTIONS
    assert all(item.kind is ActionKind.ANALYSE_JOB for item in ranked)


def test_order_within_a_kind_is_preserved() -> None:
    """The caller sorts jobs newest first; ranking must not shuffle them."""
    ranked = rank([action(ActionKind.ANALYSE_JOB, name) for name in ("first", "second", "third")])

    assert [item.subject for item in ranked] == ["first", "second", "third"]


def test_every_kind_has_a_place_in_the_order() -> None:
    """A missing member would raise KeyError inside the ranking, on whichever
    account first produced that situation."""
    assert set(ACTION_ORDER) == set(ActionKind)


# --- following up -------------------------------------------------------------


def test_an_application_never_sent_is_never_chased() -> None:
    """`applied_at` is null for one still being prepared, which is not the same
    as one sent today — there is nothing to follow up on."""
    assert is_stale_application(None, NOW) is False


def test_a_recent_application_is_left_alone() -> None:
    assert is_stale_application(NOW - dt.timedelta(days=3), NOW) is False


def test_an_application_sitting_a_fortnight_is_worth_chasing() -> None:
    assert is_stale_application(NOW - dt.timedelta(days=14), NOW) is True


def test_a_naive_timestamp_does_not_raise() -> None:
    """The columns are timezone-aware and some drivers hand back naive values.
    Subtracting the two raises rather than comparing wrongly, and this runs on
    every dashboard load."""
    naive = (NOW - dt.timedelta(days=30)).replace(tzinfo=None)

    assert is_stale_application(naive, NOW) is True
