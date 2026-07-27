"""The resume parsing service, against a fake provider.

No live model, per ``docs/11-engineering-standards.md``. What is under test is
the orchestration: prompt rendering, the schema handed to the provider, retry
behaviour, and — the part the AI feature gate turns on — that every attempt
produces a trace, including the failed ones.
"""

from __future__ import annotations

from typing import Any

import pytest

from jip_ai import AIError, AIFailureCode, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.documents.upload import DOCX, PDF
from jip_api.application.resumes.parsing import ResumeParsingService

DOCUMENT = (
    "MAYA OKONKWO\nBackend Engineer\n\n"
    "EXPERIENCE\nJunior Backend Engineer, Verdant Logistics\n"
    "Built REST endpoints in FastAPI.\n\nSKILLS\nPython, FastAPI\n"
)

GOOD_RESPONSE: dict[str, Any] = {
    "skills": [{"name": "Python", "confidence": 95, "source_text": "Python, FastAPI"}],
    "experiences": [
        {
            "company": "Verdant Logistics",
            "title": "Junior Backend Engineer",
            "confidence": 95,
            "achievements": [{"text": "Built REST endpoints in FastAPI.", "confidence": 90}],
        }
    ],
}


def service(provider: FakeLLMProvider, *, max_attempts: int = 3, max_chars: int = 60_000) -> Any:
    router = build_router(
        resume_parse_model="test-model",
        resume_parse_max_output_tokens=8000,
        resume_parse_effort="medium",
    )
    return ResumeParsingService(
        provider, router, max_input_chars=max_chars, max_attempts=max_attempts
    )


def test_parses_and_validates() -> None:
    outcome = service(FakeLLMProvider([GOOD_RESPONSE])).parse(DOCUMENT, content_type=PDF)

    assert len(outcome.validated.candidates) == 2
    assert outcome.prompt_version == "resume_parser_v1"
    assert outcome.model == "test-model"


def test_the_document_reaches_the_prompt() -> None:
    provider = FakeLLMProvider([GOOD_RESPONSE])

    service(provider).parse(DOCUMENT, content_type=PDF)

    assert "Verdant Logistics" in provider.requests[0].user


def test_the_format_label_reaches_the_prompt() -> None:
    """The parser is told which format the text came from, because extraction
    artefacts differ between PDF and DOCX."""
    provider = FakeLLMProvider([GOOD_RESPONSE])

    service(provider).parse(DOCUMENT, content_type=DOCX)

    assert "Word (DOCX)" in provider.requests[0].user


def test_the_route_configures_the_request() -> None:
    provider = FakeLLMProvider([GOOD_RESPONSE])

    service(provider).parse(DOCUMENT, content_type=PDF)

    request = provider.requests[0]
    assert request.max_output_tokens == 8000
    assert request.effort == "medium"
    assert request.json_schema["type"] == "object"


def test_a_successful_parse_produces_one_trace() -> None:
    outcome = service(FakeLLMProvider([GOOD_RESPONSE])).parse(DOCUMENT, content_type=PDF)

    assert len(outcome.traces) == 1
    trace = outcome.traces[0]
    assert trace.succeeded
    assert trace.attempt == 1
    assert trace.estimated_cost_usd is None or trace.estimated_cost_usd >= 0


def test_every_attempt_is_traced_including_failures() -> None:
    """A trace that only records the final outcome hides the fact that a
    "successful" parse cost three calls."""
    provider = FakeLLMProvider([AIError(AIFailureCode.RATE_LIMIT, "slow down"), GOOD_RESPONSE])

    outcome = service(provider).parse(DOCUMENT, content_type=PDF)

    assert len(outcome.traces) == 2
    assert outcome.traces[0].failure_code is AIFailureCode.RATE_LIMIT
    assert outcome.traces[1].succeeded


def test_malformed_output_is_invalid_output() -> None:
    provider = FakeLLMProvider(["not json at all"] * 3)

    with pytest.raises(AIError) as caught:
        service(provider).parse(DOCUMENT, content_type=PDF)

    assert caught.value.code is AIFailureCode.INVALID_OUTPUT


def test_output_of_the_wrong_shape_is_invalid_output() -> None:
    """Well-formed JSON that is not the agreed schema. Classified as
    INVALID_OUTPUT, not VALIDATION_FAILURE — nothing reached a business rule."""
    provider = FakeLLMProvider([{"skills": "not a list"}] * 3)

    with pytest.raises(AIError) as caught:
        service(provider).parse(DOCUMENT, content_type=PDF)

    assert caught.value.code is AIFailureCode.INVALID_OUTPUT


def test_a_permanent_failure_is_not_retried() -> None:
    provider = FakeLLMProvider([AIError(AIFailureCode.CONTENT_UNAVAILABLE, "declined")])

    with pytest.raises(AIError) as caught:
        service(provider).parse(DOCUMENT, content_type=PDF)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE


def test_empty_text_never_reaches_the_provider() -> None:
    """Paying for a call that cannot succeed is exactly the cost discipline
    docs/11-engineering-standards.md asks about."""
    provider = FakeLLMProvider([GOOD_RESPONSE])

    with pytest.raises(AIError) as caught:
        service(provider).parse("   \n  ", content_type=PDF)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert provider.requests == []


def test_oversized_input_is_truncated_and_reported() -> None:
    """Silently sending half a resume and presenting the result as a full parse
    is the kind of quiet incorrectness GOAL.md rules out."""
    provider = FakeLLMProvider([GOOD_RESPONSE])
    long_document = DOCUMENT + ("x" * 5000)

    outcome = service(provider, max_chars=500).parse(long_document, content_type=PDF)

    assert any("longer than" in w for w in outcome.warnings)
    assert len(provider.requests[0].user) < len(long_document)


def test_input_hash_is_stable_across_runs() -> None:
    """This is what lets a re-upload of an identical resume reuse a stored
    result instead of paying for the same call twice."""
    first = service(FakeLLMProvider([GOOD_RESPONSE])).parse(DOCUMENT, content_type=PDF)
    second = service(FakeLLMProvider([GOOD_RESPONSE])).parse(DOCUMENT, content_type=PDF)

    assert first.input_hash == second.input_hash


def test_a_different_document_hashes_differently() -> None:
    first = service(FakeLLMProvider([GOOD_RESPONSE])).parse(DOCUMENT, content_type=PDF)
    second = service(FakeLLMProvider([GOOD_RESPONSE])).parse(
        DOCUMENT + "\nExtra line", content_type=PDF
    )

    assert first.input_hash != second.input_hash


def test_validation_warnings_reach_the_outcome() -> None:
    provider = FakeLLMProvider(
        [{"skills": [{"name": "Python", "confidence": 95, "source_text": "never written"}]}]
    )

    outcome = service(provider).parse(DOCUMENT, content_type=PDF)

    assert any("does not appear" in w for w in outcome.warnings)


def test_an_empty_result_is_not_an_error() -> None:
    """A document with no career facts is a valid answer the user should be
    told about, not a failure to retry."""
    outcome = service(FakeLLMProvider([{}])).parse(DOCUMENT, content_type=PDF)

    assert outcome.result.is_empty
    assert outcome.validated.is_empty
