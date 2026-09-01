"""Testing the ruler before measuring anything with it.

A wrong error rate does not fail. It returns a plausible number, and every
measurement taken with it afterwards is worthless in a way that leaves no
trace. So each case here has an answer that can be counted by hand, and the
comment says the count.

Needs nothing installed. This is arithmetic.
"""

from __future__ import annotations

import pytest

from tests.ocr_metrics import (
    character_error_rate,
    edit_distance,
    normalise,
    word_error_rate,
)

# --- The distance itself -------------------------------------------------------


def test_identical_sequences_are_zero_apart() -> None:
    assert edit_distance("engineer", "engineer") == 0


def test_one_substitution() -> None:
    """`rn` read as `m` is the classic confusion; here just one letter."""
    assert edit_distance("Engineer", "Enqineer") == 1


def test_one_deletion_and_one_insertion() -> None:
    assert edit_distance("Python", "Pythn") == 1  # deleted the o
    assert edit_distance("Python", "Pythonn") == 1  # inserted an n


def test_an_empty_side_costs_the_whole_other_side() -> None:
    assert edit_distance("", "Docker") == 6
    assert edit_distance("Docker", "") == 6


def test_it_finds_the_cheapest_route_not_the_obvious_one() -> None:
    """`kitten` to `sitting` is the textbook case, and the answer is three.

    Worth having because it is the one place a hand-rolled implementation
    usually goes wrong: taking substitutions one at a time and never noticing
    that an insertion was cheaper.
    """
    assert edit_distance("kitten", "sitting") == 3


# --- Character error rate ------------------------------------------------------


def test_a_perfect_read_is_zero() -> None:
    assert character_error_rate("Backend Engineer", "Backend Engineer") == 0.0


def test_one_wrong_character_in_ten() -> None:
    assert character_error_rate("PostgreSQL", "PostgreSQI") == pytest.approx(0.1)


def test_it_can_exceed_one() -> None:
    """Insertions count, so an engine can be more than 100% wrong.

    Capping it at 1.0 would round the worst failures into the merely bad, which
    is the opposite of what a measurement is for.
    """
    assert character_error_rate("hi", "hi and a page of invented noise") > 1.0


def test_layout_is_not_scored_as_spelling() -> None:
    """An engine rebuilds line breaks from the geometry of the page.

    It will not reproduce the exact runs of whitespace a text layer had, and
    counting those would measure the layout rather than the reading.
    """
    assert character_error_rate("Python   FastAPI", "Python FastAPI") == 0.0
    assert character_error_rate("Python\nFastAPI", "Python FastAPI") == 0.0


def test_case_is_still_an_error() -> None:
    """Reading `Python` as `python` is wrong, and a reader would notice."""
    assert character_error_rate("Python", "python") > 0.0


# --- Word error rate -----------------------------------------------------------


def test_one_wrong_word_in_four() -> None:
    truth = "Built REST endpoints in FastAPI"
    read = "Built REST endpoints in FastAPl"

    assert word_error_rate(truth, read) == pytest.approx(1 / 5)


def test_word_error_is_never_kinder_than_character_error() -> None:
    """One bad character spoils a whole word, so WER >= CER on the same pair.

    The gap between them is itself informative: a large one means the damage is
    scattered across many words, a small one means it is concentrated.
    """
    truth = "Junior Backend Engineer, Verdant Logistics"
    read = "Junior Backend Enqineer, Verdant Loqistics"

    assert word_error_rate(truth, read) >= character_error_rate(truth, read)


# --- Normalising ---------------------------------------------------------------


def test_normalise_collapses_and_trims() -> None:
    assert normalise("  Python \n\n  FastAPI  ") == "Python FastAPI"


def test_empty_truth_against_empty_read_is_not_an_error() -> None:
    """A blank page read as blank is a correct reading, not a division by zero."""
    assert character_error_rate("", "") == 0.0
    assert word_error_rate("", "") == 0.0


def test_empty_truth_against_invented_text_is_wholly_wrong() -> None:
    assert character_error_rate("", "invented") == 1.0
    assert word_error_rate("", "invented") == 1.0
