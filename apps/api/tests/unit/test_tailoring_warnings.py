"""Merging warnings onto a strategy across repeated runs.

Small enough to look obvious, and it was not: the route appended
unconditionally, so pressing `Suggest changes` twice after a failure stored the
same sentence twice and the user was told about one failure two times.
"""

from __future__ import annotations

from jip_api.application.resumes.tailoring_service import merge_warnings

FAILED = "Suggestions could not be generated. Your resume is unchanged, and you can try again."
PLANNED = (
    "A written plan could not be generated, so this strategy shows the selected evidence only."
)


def test_a_repeated_warning_is_stored_once() -> None:
    """Walked 2026-08-11. Two failed attempts, and the screen said it twice.

    React also refused the list, because the component keyed each item by its
    own text — a duplicate key, which in production drops a row rather than
    warning about one.
    """
    assert merge_warnings([FAILED], [FAILED]) == [FAILED]


def test_a_warning_from_planning_survives_a_later_run() -> None:
    """Appended, not replaced. The plan's warning still describes the plan."""
    assert merge_warnings([PLANNED], [FAILED]) == [PLANNED, FAILED]


def test_the_first_occurrence_keeps_its_position() -> None:
    """The list is a record of what went wrong. Re-ordering it on a retry would
    make the oldest problem look like the newest."""
    assert merge_warnings([PLANNED, FAILED], [FAILED, "Something new."]) == [
        PLANNED,
        FAILED,
        "Something new.",
    ]


def test_repeats_within_one_batch_are_also_collapsed() -> None:
    """Nothing currently emits the same warning twice in one outcome, and
    relying on that is how the original bug got in."""
    assert merge_warnings([], [FAILED, FAILED]) == [FAILED]


def test_nothing_incoming_leaves_the_list_alone() -> None:
    assert merge_warnings([PLANNED], []) == [PLANNED]


def test_the_original_list_is_not_mutated() -> None:
    """The caller assigns the result onto a SQLAlchemy column. Mutating the
    existing list in place would work by accident and stop working the day the
    attribute is not the same object."""
    existing = [PLANNED]
    merged = merge_warnings(existing, [FAILED])

    assert existing == [PLANNED]
    assert merged == [PLANNED, FAILED]
