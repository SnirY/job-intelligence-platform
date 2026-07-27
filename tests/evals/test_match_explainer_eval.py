"""Evaluation for ``match_explainer_v1``.

The narrowest evaluation in the suite, because the prompt is the narrowest. The
score, the statuses, and the recommendation are all decided before it runs, so
there is no coverage to measure — only whether the summary stays inside its
bounds.

Three of these are correctness rather than quality: the summary must not
contradict the verdicts it was given, must not talk about hiring odds, and must
not invent a fact. The fourth is that a failure costs a paragraph rather than a
match.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from jip_ai import AIError, AIFailureCode, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.matching.explain import MatchExplainerService
from jip_api.application.matching.matcher import Verdict
from jip_api.application.matching.scoring import score_match
from jip_api.domain.matching.models import MatchCategory, MatchStatus

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "matches"
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURE_DIR.glob("*.json"))]

FORBIDDEN_PHRASES = (
    "chance of getting",
    "likely to get",
    "you will get",
    "guaranteed",
    "probability of",
    "odds of",
)
"""docs/05-ai-and-matching.md: never present a score as a hiring probability."""


def _router() -> Any:
    return build_router(
        resume_parse_model="eval-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )


def _verdicts(match_case: dict[str, Any]) -> tuple[list[Verdict], dict[uuid.UUID, Any]]:
    from types import SimpleNamespace

    verdicts: list[Verdict] = []
    requirements: dict[uuid.UUID, Any] = {}
    for index, raw in enumerate(match_case["verdicts"]):
        requirement_id = uuid.uuid4()
        status = MatchStatus(raw["status"])
        verdicts.append(
            Verdict(
                requirement_id=requirement_id,
                status=status,
                category=MatchCategory.TECHNICAL,
                score=raw["score"],
                weight=Decimal(str(raw.get("weight", "2.00"))),
                confidence=raw.get("confidence", 70),
                explanation=raw["explanation"],
                is_blocker=raw.get("is_blocker", False),
                source_order=index,
            )
        )
        requirements[requirement_id] = SimpleNamespace(normalized_text=raw["requirement"])
    return verdicts, requirements


@pytest.mark.parametrize("match_case", CASES, ids=[c["name"] for c in CASES])
def test_the_summary_is_returned(match_case: dict[str, Any]) -> None:
    verdicts, requirements = _verdicts(match_case)
    service = MatchExplainerService(
        FakeLLMProvider([match_case["recorded_output"]]), _router(), max_attempts=1
    )

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )

    assert outcome.summary
    assert outcome.warnings == []


@pytest.mark.parametrize("match_case", CASES, ids=[c["name"] for c in CASES])
def test_the_summary_never_claims_a_hiring_chance(match_case: dict[str, Any]) -> None:
    verdicts, requirements = _verdicts(match_case)
    service = MatchExplainerService(
        FakeLLMProvider([match_case["recorded_output"]]), _router(), max_attempts=1
    )

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )
    lowered = (outcome.summary or "").lower()

    offending = [phrase for phrase in FORBIDDEN_PHRASES if phrase in lowered]
    assert not offending, f"{match_case['name']}: summary claims hiring odds {offending}"


@pytest.mark.parametrize("match_case", CASES, ids=[c["name"] for c in CASES])
def test_the_summary_mentions_what_it_must(match_case: dict[str, Any]) -> None:
    """A blocker that goes unmentioned is the failure that matters — someone
    reads an encouraging paragraph and misses the one thing that rules them
    out."""
    verdicts, requirements = _verdicts(match_case)
    service = MatchExplainerService(
        FakeLLMProvider([match_case["recorded_output"]]), _router(), max_attempts=1
    )

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )
    lowered = (outcome.summary or "").lower()

    missing = [
        term for term in match_case.get("expect_mentions", []) if term.lower() not in lowered
    ]
    assert not missing, f"{match_case['name']}: summary omits {missing}"


@pytest.mark.parametrize("match_case", CASES, ids=[c["name"] for c in CASES])
def test_the_summary_invents_nothing(match_case: dict[str, Any]) -> None:
    verdicts, requirements = _verdicts(match_case)
    service = MatchExplainerService(
        FakeLLMProvider([match_case["recorded_output"]]), _router(), max_attempts=1
    )

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )
    lowered = (outcome.summary or "").lower()

    offending = [term for term in match_case.get("forbid_mentions", []) if term.lower() in lowered]
    assert not offending, f"{match_case['name']}: summary invented {offending}"


def test_a_provider_failure_costs_a_paragraph_not_a_match() -> None:
    """The contract the whole design rests on. The match is already persisted
    by the time this runs, so an exception escaping here would turn a cosmetic
    failure into a lost verdict."""
    verdicts, requirements = _verdicts(CASES[0])
    provider = FakeLLMProvider([AIError(AIFailureCode.PROVIDER_ERROR, "The provider is down.")])
    service = MatchExplainerService(provider, _router(), max_attempts=1)

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )

    assert outcome.summary is None
    assert outcome.warnings
    assert "match itself is complete" in outcome.warnings[0]


def test_malformed_output_is_handled_the_same_way() -> None:
    verdicts, requirements = _verdicts(CASES[0])
    service = MatchExplainerService(
        FakeLLMProvider([{"wrong": "shape"}]), _router(), max_attempts=1
    )

    outcome = service.explain(
        result=score_match(verdicts), verdicts=verdicts, requirements=requirements
    )

    assert outcome.summary is None
    assert outcome.warnings
