"""Liveness checking: what a status means, and what gets written.

The fetcher has its own socket-level tests next door. What matters here is the
two things that layer cannot get right on its own — the mapping from an HTTP
status to a verdict, and the rule that an inconclusive check leaves no trace.

The second is the one to protect. Every other test in this file would still
pass if UNKNOWN quietly recorded a timestamp, and the product defect that
follows is a live posting shown to the user as closed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import cast

import pytest
from sqlalchemy.orm import Session

from jip_api.application.jobs.liveness import (
    LivenessReason,
    LivenessVerdict,
    classify,
    run_liveness_check,
)
from jip_api.domain.jobs.models import Job, JobImportMethod, JobProcessingStatus
from jip_api.infrastructure.fetching import FetchError, FetchResult

NOW = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC)
EARLIER = dt.datetime(2026, 8, 1, 9, 30, tzinfo=dt.UTC)


class _Session:
    """Enough of a session for a row that is never queried."""

    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


def _job(*, source_url: str | None = "https://jobs.example.com/role/12") -> Job:
    return Job(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Backend Engineer",
        normalized_title="backend engineer",
        source_url=source_url,
        import_method=JobImportMethod.URL if source_url else JobImportMethod.PASTED_DESCRIPTION,
        status=JobProcessingStatus.RAW,
    )


def _result(status: int) -> FetchResult:
    return FetchResult(
        final_url="https://jobs.example.com/role/12",
        status=status,
        content_type="text/html",
        body="<html></html>",
        byte_count=13,
    )


# --- classification -----------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201, 204, 399])
def test_a_status_under_400_is_alive(status: int) -> None:
    reading = classify(status)

    assert reading.verdict is LivenessVerdict.ALIVE
    assert reading.reason is LivenessReason.OK


@pytest.mark.parametrize("status", [404, 410])
def test_only_not_found_and_gone_read_as_closed(status: int) -> None:
    reading = classify(status)

    assert reading.verdict is LivenessVerdict.GONE
    assert reading.reason is LivenessReason.NOT_FOUND
    assert reading.status == status


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, LivenessReason.BLOCKED),
        (403, LivenessReason.BLOCKED),
        (429, LivenessReason.BLOCKED),
        (500, LivenessReason.SERVER_ERROR),
        (503, LivenessReason.SERVER_ERROR),
        (400, LivenessReason.INCONCLUSIVE),
        (405, LivenessReason.INCONCLUSIVE),
    ],
)
def test_every_other_failure_is_unknown(status: int, reason: LivenessReason) -> None:
    """A refusal, a rate limit and a server fault all mean we could not look.

    None of them are evidence about the posting, and the whole module turns on
    not confusing them with evidence.
    """
    reading = classify(status)

    assert reading.verdict is LivenessVerdict.UNKNOWN
    assert reading.reason is reason


def test_no_status_at_all_is_unknown() -> None:
    """DNS failure, a blocked target, a redirect loop. Unreachable is not gone."""
    reading = classify(None)

    assert reading.verdict is LivenessVerdict.UNKNOWN
    assert reading.reason is LivenessReason.UNREACHABLE
    assert reading.status is None


# --- what gets written --------------------------------------------------------


def test_alive_records_when_it_was_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", lambda *a, **k: _result(200))
    job = _job()

    outcome = run_liveness_check(
        cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW
    )

    assert outcome.verdict is LivenessVerdict.ALIVE
    assert job.last_seen_alive_at == NOW
    assert job.closed_detected_at is None


def test_answering_again_clears_a_previous_closure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reposted or restored role must not stay marked closed forever.

    The column means "closed since when", not "was closed once".
    """
    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", lambda *a, **k: _result(200))
    job = _job()
    job.closed_detected_at = EARLIER

    run_liveness_check(cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW)

    # Ordered so the freshly-recorded value is asserted first: mypy narrows
    # `closed_detected_at` to non-None at the assignment above and cannot see
    # that the call clears it, so an `is None` check has to come last or every
    # line after it reads as unreachable.
    assert job.last_seen_alive_at == NOW
    assert job.closed_detected_at is None


def test_gone_records_the_first_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> FetchResult:
        raise FetchError("gone", code="HTTP_ERROR", status=404)

    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", _raise)
    job = _job()

    outcome = run_liveness_check(
        cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW
    )

    assert outcome.verdict is LivenessVerdict.GONE
    assert job.closed_detected_at == NOW
    assert job.last_seen_alive_at is None


def test_a_second_gone_check_does_not_move_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise "closed on the 1st" silently becomes "closed today"."""

    def _raise(*_a: object, **_k: object) -> FetchResult:
        raise FetchError("gone", code="HTTP_ERROR", status=410)

    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", _raise)
    job = _job()
    job.closed_detected_at = EARLIER

    run_liveness_check(cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW)

    assert job.closed_detected_at == EARLIER


@pytest.mark.parametrize(
    "error",
    [
        FetchError("refused", code="HTTP_ERROR", status=403),
        FetchError("slow", code="TIMEOUT"),
        FetchError("blocked", code="BLOCKED_URL"),
        FetchError("looping", code="TOO_MANY_REDIRECTS"),
    ],
)
def test_an_inconclusive_check_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, error: FetchError
) -> None:
    """The rule the module exists for.

    Both columns keep meaning what they meant, including when what they meant
    was "never observed".
    """

    def _raise(*_a: object, **_k: object) -> FetchResult:
        raise error

    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", _raise)
    job = _job()
    session = _Session()

    outcome = run_liveness_check(
        cast(Session, session), job, timeout_seconds=5, max_bytes=1000, now=NOW
    )

    assert outcome.verdict is LivenessVerdict.UNKNOWN
    assert outcome.checked_at is None
    assert job.last_seen_alive_at is None
    assert job.closed_detected_at is None
    assert session.flushes == 0


def test_an_inconclusive_check_leaves_an_earlier_answer_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that is down today does not erase what we knew yesterday."""

    def _raise(*_a: object, **_k: object) -> FetchResult:
        raise FetchError("down", code="HTTP_ERROR", status=503)

    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", _raise)
    job = _job()
    job.last_seen_alive_at = EARLIER

    run_liveness_check(cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW)

    assert job.last_seen_alive_at == EARLIER


def test_a_job_with_no_link_is_not_a_failure() -> None:
    """Pasted jobs have nothing to check. That is not the same as a failed check."""
    job = _job(source_url=None)

    outcome = run_liveness_check(
        cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW
    )

    assert outcome.verdict is LivenessVerdict.UNKNOWN
    assert outcome.reason is LivenessReason.NO_URL
    assert job.last_seen_alive_at is None
    assert job.closed_detected_at is None


@pytest.mark.parametrize("status", [200, 404, 403])
def test_a_check_never_archives_or_changes_status(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Archiving is the user's decision about their own list.

    A posting closing is not that decision being made on their behalf, and the
    processing status describes the pipeline rather than the world.
    """

    def _fetch(*_a: object, **_k: object) -> FetchResult:
        if status >= 400:
            raise FetchError("no", code="HTTP_ERROR", status=status)
        return _result(status)

    monkeypatch.setattr("jip_api.application.jobs.liveness.fetch_url", _fetch)
    job = _job()

    run_liveness_check(cast(Session, _Session()), job, timeout_seconds=5, max_bytes=1000, now=NOW)

    assert job.archived_at is None
    assert job.status is JobProcessingStatus.RAW
