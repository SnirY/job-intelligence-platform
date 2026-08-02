"""What must never reach a log.

``docs/11-engineering-standards.md`` lists four things:

    full resume text · authentication tokens · API keys · unnecessary personal
    details

A rule in a document is a to-do until something fails when it is broken. These
are that something.

The case that prompted them: ``parse_structured_output`` recorded
``first 200 chars: {response!r}`` in ``AIError.details``, and
``processing.jobs.mark_failed`` logs ``details``. On a resume parse the model's
output *is* the resume, so a malformed response put the user's name and
employers into the application log — while looking like an ordinary diagnostic.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from jip_ai import AIError, AIFailureCode
from jip_ai.structured import parse_structured_output

# A response shaped like a real resume parse, and broken so it takes the
# failure path. Every value here is the kind of thing that must not be logged.
BROKEN_RESUME_RESPONSE = """{
  "full_name": "Dana Kowalczyk",
  "email": "dana.kowalczyk@example.com",
  "phone": "+972-50-555-0134",
  "experiences": [{"company": "Verdant Logistics", "title": "Senior Engineer"
"""

FORBIDDEN = [
    "Dana Kowalczyk",
    "dana.kowalczyk@example.com",
    "+972-50-555-0134",
    "Verdant Logistics",
]


def test_a_malformed_response_does_not_carry_its_content_into_the_error() -> None:
    with pytest.raises(AIError) as raised:
        parse_structured_output(BROKEN_RESUME_RESPONSE)

    details = raised.value.details or ""
    leaked = [secret for secret in FORBIDDEN if secret in details]

    assert not leaked, f"personal data reached AIError.details: {leaked}"


def test_the_error_still_says_enough_to_diagnose_the_failure() -> None:
    """The other half, and the reason this was not simply deleted.

    DEV-015: a failure whose real cause was "credit balance too low", with
    nothing recorded. Stripping diagnostics to protect data trades one silent
    failure for another.
    """
    with pytest.raises(AIError) as raised:
        parse_structured_output(BROKEN_RESUME_RESPONSE)

    details = raised.value.details or ""

    assert "char" in details, "the response length is what shows a truncation"
    assert "opens" in details, "whether it began as an object at all"
    # The decode error's own message, carrying line and column.
    assert "line" in details or "column" in details or "Expecting" in details


def test_an_empty_response_is_reported_without_inventing_detail() -> None:
    with pytest.raises(AIError) as raised:
        parse_structured_output("   ")

    assert raised.value.code is AIFailureCode.INVALID_OUTPUT


def test_a_json_array_is_refused_by_shape_alone() -> None:
    """A valid-JSON non-object never reaches the shape helper, and its detail
    names the type rather than the contents — a list of the user's employers
    would otherwise be quoted whole."""
    with pytest.raises(AIError) as raised:
        parse_structured_output(json.dumps(["Verdant Logistics", "Northwind"]))

    details = raised.value.details or ""

    assert "list" in details
    assert "Verdant Logistics" not in details


# --- the logging call itself --------------------------------------------------


def test_a_failed_processing_job_logs_no_personal_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end over the path that made this a defect rather than a risk.

    `mark_failed` logs `error.details`, so this asserts against the record a
    log aggregator would actually receive, not against the string in isolation.
    """
    from jip_api.application.processing import jobs as jobs_uc

    with pytest.raises(AIError) as raised:
        parse_structured_output(BROKEN_RESUME_RESPONSE)

    job = _StubJob()
    with caplog.at_level(logging.WARNING):
        jobs_uc.mark_failed(_NullSession(), job, raised.value)  # type: ignore[arg-type]

    emitted = "\n".join(
        f"{record.getMessage()} {getattr(record, 'detail', '')}" for record in caplog.records
    )
    leaked = [secret for secret in FORBIDDEN if secret in emitted]

    assert leaked == [], f"personal data reached the log: {leaked}"


class _StubJob:
    """Only what `mark_failed` assigns to, so the test needs no database."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.status = None
        self.step = None
        self.error_code = None
        self.error_message = None
        self.is_retriable = False
        self.attempts = 1
        self.max_attempts = 5
        self.finished_at = None


class _NullSession:
    def flush(self) -> None:
        return None

    def add(self, _obj: object) -> None:
        return None
