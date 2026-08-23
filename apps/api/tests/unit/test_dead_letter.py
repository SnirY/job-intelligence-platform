"""When a failure is worth another attempt, and when it is finished.

Phase 11 carried retry flows as partial with one thing named: a dead-letter path
and any view across failures. The retrying worked; what was missing was a way to
*ask* whether a failure was over, without attempting it and reading the refusal.

Three stored facts decide it, and until now only `prepare_retry` knew how they
combined. These tests are about the rule now having one home, and about the two
questions it answers being different: `can_be_retried` is "may I offer this",
`is_dead` is "is this finished".
"""

from __future__ import annotations

import uuid

import pytest

from jip_api.domain.processing.models import (
    ProcessingJob,
    ProcessingJobKind,
    ProcessingJobStatus,
    ProcessingStep,
)


def job(
    *,
    status: ProcessingJobStatus = ProcessingJobStatus.FAILED,
    retriable: bool = True,
    attempts: int = 1,
    max_attempts: int = 5,
) -> ProcessingJob:
    return ProcessingJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=ProcessingJobKind.RESUME_IMPORT,
        status=status,
        step=ProcessingStep.QUEUED,
        entity_type="source_document",
        entity_id=uuid.uuid4(),
        attempts=attempts,
        max_attempts=max_attempts,
        is_retriable=retriable,
    )


# --- what can still be tried ---------------------------------------------------


def test_a_transient_failure_with_attempts_left_can_be_retried() -> None:
    assert job().can_be_retried is True


def test_a_permanent_failure_cannot() -> None:
    """A PDF with no text layer stays a PDF with no text layer.

    `is_retriable` is recorded when the failure is classified rather than
    re-derived later, which is the whole reason this answer is trustworthy.
    """
    assert job(retriable=False).can_be_retried is False


def test_a_failure_that_ran_out_of_attempts_cannot() -> None:
    assert job(attempts=5, max_attempts=5).can_be_retried is False


@pytest.mark.parametrize(
    "status",
    [ProcessingJobStatus.PENDING, ProcessingJobStatus.RUNNING, ProcessingJobStatus.COMPLETED],
)
def test_only_a_failed_job_is_a_retry_candidate(status: ProcessingJobStatus) -> None:
    """Retrying something still running would run it twice."""
    assert job(status=status).can_be_retried is False


# --- what is finished ----------------------------------------------------------


def test_a_permanent_failure_is_dead() -> None:
    assert job(retriable=False).is_dead is True


def test_an_exhausted_failure_is_dead() -> None:
    assert job(attempts=5, max_attempts=5).is_dead is True


def test_a_failure_that_can_still_be_tried_is_not_dead() -> None:
    """The distinction the list exists to draw.

    Both appear in the failures view; only one is offered a button.
    """
    row = job()
    assert row.can_be_retried is True
    assert row.is_dead is False


@pytest.mark.parametrize(
    "status",
    [ProcessingJobStatus.PENDING, ProcessingJobStatus.RUNNING, ProcessingJobStatus.COMPLETED],
)
def test_a_job_that_has_not_failed_is_not_dead(status: ProcessingJobStatus) -> None:
    """Dead means failed and finished, not merely un-retriable.

    A completed job is un-retriable and is the opposite of a dead letter, so the
    two questions cannot share an implementation.
    """
    assert job(status=status).is_dead is False


def test_the_two_answers_never_both_hold() -> None:
    """One row cannot be both worth trying and finished with."""
    for row in (
        job(),
        job(retriable=False),
        job(attempts=5, max_attempts=5),
        job(status=ProcessingJobStatus.COMPLETED),
    ):
        assert not (row.can_be_retried and row.is_dead)
