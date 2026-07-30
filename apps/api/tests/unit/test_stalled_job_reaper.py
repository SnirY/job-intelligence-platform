"""Failing jobs whose worker never reported back.

DEV-013. What these protect:

- a job that was never picked up eventually becomes actionable;
- a job that is merely slow is left alone;
- a reaped job is retriable, because nothing about its input was rejected;
- the attempt budget still ends the loop.

No database. The reaper reads two timestamps and writes four fields, and `now`
is injected so the thresholds can be tested without waiting them out.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from jip_api.application.processing.reaper import STALLED, reap_if_stalled
from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
    ProcessingStep,
)

NOW = dt.datetime(2026, 7, 29, 12, 0, tzinfo=dt.UTC)
PENDING_LIMIT = 300
RUNNING_LIMIT = 1800


class FakeSession:
    """Enough Session for the reaper: it looks entities up and flushes."""

    def __init__(self, entity: object | None = None) -> None:
        self.entity = entity
        self.flushed = False

    def get(self, _model: object, _pk: uuid.UUID) -> object | None:
        return self.entity

    def flush(self) -> None:
        self.flushed = True


def job(
    *,
    status: ProcessingJobStatus = ProcessingJobStatus.PENDING,
    age_seconds: int = 0,
    started_seconds_ago: int | None = None,
    attempts: int = 0,
    max_attempts: int = 5,
    kind: ProcessingJobKind = ProcessingJobKind.RESUME_IMPORT,
) -> ProcessingJob:
    row = ProcessingJob(
        user_id=uuid.uuid4(),
        kind=kind,
        status=status,
        step=ProcessingStep.QUEUED,
        entity_type="source_document",
        entity_id=uuid.uuid4(),
        attempts=attempts,
        max_attempts=max_attempts,
        is_retriable=False,
    )
    row.id = uuid.uuid4()
    row.created_at = NOW - dt.timedelta(seconds=age_seconds)
    row.started_at = (
        NOW - dt.timedelta(seconds=started_seconds_ago) if started_seconds_ago is not None else None
    )
    return row


def reap(row: ProcessingJob, session: FakeSession | None = None) -> bool:
    return reap_if_stalled(
        session or FakeSession(),  # type: ignore[arg-type]
        row,
        pending_timeout_seconds=PENDING_LIMIT,
        running_timeout_seconds=RUNNING_LIMIT,
        now=NOW,
    )


# --- pending ------------------------------------------------------------------


def test_a_job_that_was_never_picked_up_is_failed() -> None:
    """The case DEV-013 was opened for: the worker raised before writing a
    status, so the row sat PENDING with no recovery path at all."""
    row = job(age_seconds=PENDING_LIMIT + 1)

    assert reap(row) is True
    assert row.status is ProcessingJobStatus.FAILED
    assert row.error_code == STALLED
    assert row.finished_at == NOW


def test_a_recently_queued_job_is_left_alone() -> None:
    """Queued behind other work is not the same as dead."""
    row = job(age_seconds=PENDING_LIMIT - 1)

    assert reap(row) is False
    assert row.status is ProcessingJobStatus.PENDING


def test_the_message_says_nothing_was_lost() -> None:
    """The user's question is "did I lose my upload", and the answer is no."""
    row = job(age_seconds=PENDING_LIMIT + 1)

    reap(row)

    assert "Nothing was lost" in (row.error_message or "")


# --- running ------------------------------------------------------------------


def test_a_job_whose_worker_died_partway_is_failed() -> None:
    row = job(status=ProcessingJobStatus.RUNNING, started_seconds_ago=RUNNING_LIMIT + 1)

    assert reap(row) is True
    assert row.status is ProcessingJobStatus.FAILED


def test_a_slow_job_is_not_killed() -> None:
    """A resume parse with retries and backoff takes minutes legitimately, and
    reporting a slow success as a failure would be worse than waiting."""
    row = job(status=ProcessingJobStatus.RUNNING, started_seconds_ago=RUNNING_LIMIT - 1)

    assert reap(row) is False


def test_running_is_measured_from_when_it_started() -> None:
    """Not from creation: a job queued an hour ago and running for ten seconds
    is healthy."""
    row = job(
        status=ProcessingJobStatus.RUNNING,
        age_seconds=RUNNING_LIMIT * 2,
        started_seconds_ago=10,
    )

    assert reap(row) is False


# --- states that are not stalled ------------------------------------------------


@pytest.mark.parametrize("status", [ProcessingJobStatus.COMPLETED, ProcessingJobStatus.FAILED])
def test_a_finished_job_is_never_touched(status: ProcessingJobStatus) -> None:
    row = job(status=status, age_seconds=RUNNING_LIMIT * 10)

    assert reap(row) is False
    assert row.status is status


# --- retriability ---------------------------------------------------------------


def test_a_reaped_job_is_retriable() -> None:
    """Nothing about the input was rejected — the attempt that never happened
    is exactly the one worth making again."""
    row = job(age_seconds=PENDING_LIMIT + 1)

    reap(row)

    assert row.is_retriable is True


def test_a_job_out_of_attempts_is_not_offered_a_retry() -> None:
    """Otherwise a crash loop would offer a button that rebuilds the loop."""
    row = job(age_seconds=PENDING_LIMIT + 1, attempts=5, max_attempts=5)

    reap(row)

    assert row.is_retriable is False


# --- the entity it was working on -------------------------------------------------


def test_the_document_is_released_from_its_in_progress_state() -> None:
    """Otherwise the job reports failed while its document still says PARSING,
    and the screen shows a spinner beside a retry button."""
    from jip_api.domain.documents.models import DocumentStatus

    document = SimpleNamespace(status=DocumentStatus.PARSING)
    session = FakeSession(document)

    reap(job(age_seconds=PENDING_LIMIT + 1), session)

    assert document.status is DocumentStatus.FAILED
    assert session.flushed is True


def test_an_already_parsed_document_is_not_walked_backwards() -> None:
    """A job can stall after its real work landed. Marking the document FAILED
    would discard a parse the user can still review."""
    from jip_api.domain.documents.models import DocumentStatus

    document = SimpleNamespace(status=DocumentStatus.PARSED)

    reap(job(age_seconds=PENDING_LIMIT + 1), FakeSession(document))

    assert document.status is DocumentStatus.PARSED


def test_a_stalled_analysis_leaves_the_job_able_to_be_read() -> None:
    """ANALYSIS_FAILED, not FAILED: the description is intact, and FAILED is
    what the UI reads to offer a paste box."""
    from jip_api.domain.jobs.models import JobProcessingStatus

    target = SimpleNamespace(status=JobProcessingStatus.PARSING)

    reap(
        job(age_seconds=PENDING_LIMIT + 1, kind=ProcessingJobKind.JOB_ANALYSIS),
        FakeSession(target),
    )

    assert target.status is JobProcessingStatus.ANALYSIS_FAILED


def test_a_missing_entity_does_not_crash_the_reaper() -> None:
    """The document may have been deleted while the job was stuck."""
    row = job(age_seconds=PENDING_LIMIT + 1)

    assert reap(row, FakeSession(None)) is True


def test_a_naive_timestamp_is_treated_as_utc() -> None:
    """Some drivers hand back naive values from a timezone-aware column, and
    subtracting those raises rather than comparing wrongly."""
    row = job()
    row.created_at = (NOW - dt.timedelta(seconds=PENDING_LIMIT + 1)).replace(tzinfo=None)

    assert reap(row) is True
