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


def sections(response: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """`GOOD_RESPONSE` split the way the parser now asks for it.

    DEV-017 made a parse four calls, one per section, so a fake provider needs
    four responses where it needed one. `FakeLLMProvider` replays in request
    order, which is `RESUME_SECTION_PROMPTS`.
    """
    source = GOOD_RESPONSE if response is None else response
    return [
        {"skills": source.get("skills", [])},
        {"experiences": source.get("experiences", [])},
        {"projects": source.get("projects", [])},
        {"education": source.get("education", [])},
    ]


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
    outcome = service(FakeLLMProvider(sections())).parse(DOCUMENT, content_type=PDF)

    assert len(outcome.validated.candidates) == 2
    # The set, not a member of it. Each trace still carries the section prompt
    # that produced it — see the trace test below.
    assert outcome.prompt_version == "resume_sections_v1"
    assert outcome.model == "test-model"


def test_the_document_reaches_the_prompt() -> None:
    provider = FakeLLMProvider(sections())

    service(provider).parse(DOCUMENT, content_type=PDF)

    assert "Verdant Logistics" in provider.requests[0].user


def test_the_format_label_reaches_the_prompt() -> None:
    """The parser is told which format the text came from, because extraction
    artefacts differ between PDF and DOCX."""
    provider = FakeLLMProvider(sections())

    service(provider).parse(DOCUMENT, content_type=DOCX)

    assert "Word (DOCX)" in provider.requests[0].user


def test_the_route_configures_the_request() -> None:
    provider = FakeLLMProvider(sections())

    service(provider).parse(DOCUMENT, content_type=PDF)

    request = provider.requests[0]
    assert request.max_output_tokens == 8000
    assert request.effort == "medium"
    assert request.json_schema["type"] == "object"


def test_a_successful_parse_produces_one_trace_per_section() -> None:
    """Four calls since DEV-017, and each one accounted for separately.

    The per-section prompt name on each trace is the whole reason the outcome
    can name the set without losing provenance."""
    outcome = service(FakeLLMProvider(sections())).parse(DOCUMENT, content_type=PDF)

    assert [trace.prompt_version for trace in outcome.traces] == [
        "resume_skills_v1",
        "resume_experiences_v1",
        "resume_projects_v1",
        "resume_education_v1",
    ]

    assert len(outcome.traces) == 4
    trace = outcome.traces[0]
    assert trace.succeeded
    assert trace.attempt == 1
    assert trace.estimated_cost_usd is None or trace.estimated_cost_usd >= 0


def test_every_attempt_is_traced_including_failures() -> None:
    """A trace that only records the final outcome hides the fact that a
    "successful" parse cost three calls."""
    provider = FakeLLMProvider([AIError(AIFailureCode.RATE_LIMIT, "slow down"), *sections()])

    outcome = service(provider).parse(DOCUMENT, content_type=PDF)

    # One failed skills attempt, one that succeeded, then the other three
    # sections. The retry is per section: a flaky call no longer re-runs and
    # re-bills the sections that already answered.
    assert len(outcome.traces) == 5
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
    provider = FakeLLMProvider(sections())

    with pytest.raises(AIError) as caught:
        service(provider).parse("   \n  ", content_type=PDF)

    assert caught.value.code is AIFailureCode.CONTENT_UNAVAILABLE
    assert provider.requests == []


def test_oversized_input_is_truncated_and_reported() -> None:
    """Silently sending half a resume and presenting the result as a full parse
    is the kind of quiet incorrectness GOAL.md rules out."""
    provider = FakeLLMProvider(sections())
    long_document = DOCUMENT + ("x" * 5000)

    outcome = service(provider, max_chars=500).parse(long_document, content_type=PDF)

    assert any("longer than" in w for w in outcome.warnings)
    assert len(provider.requests[0].user) < len(long_document)


def test_input_hash_is_stable_across_runs() -> None:
    """This is what lets a re-upload of an identical resume reuse a stored
    result instead of paying for the same call twice."""
    first = service(FakeLLMProvider(sections())).parse(DOCUMENT, content_type=PDF)
    second = service(FakeLLMProvider(sections())).parse(DOCUMENT, content_type=PDF)

    assert first.input_hash == second.input_hash


def test_a_different_document_hashes_differently() -> None:
    first = service(FakeLLMProvider(sections())).parse(DOCUMENT, content_type=PDF)
    second = service(FakeLLMProvider(sections())).parse(DOCUMENT + "\nExtra line", content_type=PDF)

    assert first.input_hash != second.input_hash


def test_validation_warnings_reach_the_outcome() -> None:
    provider = FakeLLMProvider(
        sections({"skills": [{"name": "Python", "confidence": 95, "source_text": "never written"}]})
    )

    outcome = service(provider).parse(DOCUMENT, content_type=PDF)

    assert any("does not appear" in w for w in outcome.warnings)


def test_an_empty_result_is_not_an_error() -> None:
    """A document with no career facts is a valid answer the user should be
    told about, not a failure to retry."""
    outcome = service(FakeLLMProvider(sections({}))).parse(DOCUMENT, content_type=PDF)

    assert outcome.result.is_empty
    assert outcome.validated.is_empty
