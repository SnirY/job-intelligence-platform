"""Scanning several boards, and what happens when one of them will not answer.

The property under test is a product one rather than a technical one: **ten
watched companies must not become zero postings because one of them is having
an outage.** A scan reports per board, because "we read four of your five" is
only actionable if the screen can name the fifth.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from jip_sources import BoardRef, BoardUnavailable, RawPosting, get_provider, scan
from jip_sources.registry import PROVIDERS, UnknownProvider

POSTING_BOARD = BoardRef("greenhouse", "good")
BROKEN_BOARD = BoardRef("greenhouse", "broken")

ONE = RawPosting(
    provider="greenhouse",
    board="good",
    external_id="1",
    title="Senior Backend Engineer",
    url="https://example.com/1",
)


class _Provider:
    """Answers for `good`, refuses `broken`, explodes on `bug`."""

    name = "greenhouse"

    def fetch(self, board: BoardRef, *, timeout_seconds: float = 15.0) -> Sequence[RawPosting]:
        if board.token == "broken":
            raise BoardUnavailable("gone", code="HTTP_ERROR", status=404)
        if board.token == "bug":
            raise RuntimeError("a defect in a provider")
        return [ONE]


@pytest.fixture(autouse=True)
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PROVIDERS, "greenhouse", _Provider())


def test_the_three_providers_are_registered() -> None:
    assert sorted(PROVIDERS) == ["ashby", "greenhouse", "lever"]


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(UnknownProvider):
        get_provider("linkedin")


def test_one_unreadable_board_does_not_end_the_scan() -> None:
    result = scan([POSTING_BOARD, BROKEN_BOARD, BoardRef("greenhouse", "alsogood")])

    assert len(result.postings) == 2
    assert len(result.failures) == 1


def test_a_failure_names_the_board_it_belongs_to() -> None:
    """An aggregate count would let a company quietly stop being watched."""
    result = scan([POSTING_BOARD, BROKEN_BOARD])

    failure = result.failures[0]
    assert failure.board.token == "broken"
    assert failure.error_code == "HTTP_ERROR"


def test_an_unknown_provider_fails_only_its_own_board() -> None:
    result = scan([POSTING_BOARD, BoardRef("workday", "somewhere")])

    assert len(result.postings) == 1
    assert result.failures[0].error_code == "UNKNOWN_PROVIDER"


def test_a_provider_raising_a_bug_is_contained() -> None:
    """A defect in one provider is still not a reason to lose the other boards."""
    result = scan([POSTING_BOARD, BoardRef("greenhouse", "bug")])

    assert len(result.postings) == 1
    assert result.failures[0].error_code == "INTERNAL"


def test_an_empty_board_is_a_success() -> None:
    """A company with nothing open is an answer, not a failure to dismiss."""

    class _Empty:
        name = "greenhouse"

        def fetch(self, board: BoardRef, *, timeout_seconds: float = 15.0) -> Sequence[RawPosting]:
            return []

    PROVIDERS["greenhouse"] = _Empty()

    result = scan([POSTING_BOARD])

    assert result.postings == []
    assert result.failures == []
    assert result.outcomes[0].succeeded
