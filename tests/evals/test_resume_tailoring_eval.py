"""Evaluations for ``resume_strategy_v1`` and ``resume_rewrite_v1``.

Two prompts, one invariant:

```text
Invented metrics = 0
```

the resume-engine equivalent of *hallucinated facts = 0*. `docs/06-resume-engine.md`
states it without qualification, and it is the only rule in this phase that a
suggestion cannot be shown to have broken and still be applied automatically.

These replay a recorded response through :class:`FakeLLMProvider` and then run
the real schema validation and the real
:func:`jip_api.application.resumes.truth.validate_rewrite` over it. No database
is needed, because the guard is deterministic and pure — which is the point of
having put it there rather than in the model.

**What these cannot catch**, per DEV-017: whether the API will compile the
schema at all. A recorded response replayed through a fake provider proves the
shape parses, not that Anthropic accepts it. Both schemas here were checked
against the live API separately, and any change to them has to be checked the
same way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jip_ai import AIOperation, StructuredRequest, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.application.resumes.tailoring_schema import (
    ResumeRewriteResult,
    ResumeStrategyResult,
    resume_rewrite_json_schema,
    resume_strategy_json_schema,
)
from jip_api.application.resumes.truth import validate_rewrite
from jip_api.domain.resumes.tailoring import ClaimStatus, SuggestionRisk
from jip_prompts import RESUME_REWRITE_LATEST, RESUME_STRATEGY_LATEST, get_prompt

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "resumes"
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURE_DIR.glob("*.json"))]
IDS = [tailoring_case["name"] for tailoring_case in CASES]


def _router() -> Any:
    return build_router(
        resume_parse_model="eval-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )


def _strategy(tailoring_case: dict[str, Any]) -> ResumeStrategyResult:
    """Replay the recorded plan through the real prompt and the real schema."""
    prompt = get_prompt(RESUME_STRATEGY_LATEST)
    rendered = prompt.render(
        job=tailoring_case["job_text"],
        match=tailoring_case["match_summary"],
        selected="\n".join(tailoring_case["selected"]) or "(nothing selected)",
        unselected="\n".join(tailoring_case["withheld"]) or "(nothing withheld)",
    )
    route = _router().route(AIOperation.RESUME_STRATEGY)
    provider = FakeLLMProvider([tailoring_case["recorded_strategy"]])
    response = provider.generate_structured(
        StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=resume_strategy_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        ),
        model=route.model,
    )
    return ResumeStrategyResult.model_validate(response.payload)


def _rewrites(tailoring_case: dict[str, Any]) -> ResumeRewriteResult:
    prompt = get_prompt(RESUME_REWRITE_LATEST)
    rendered = prompt.render(
        job=tailoring_case["job_text"],
        strategy=tailoring_case["recorded_strategy"]["summary"],
        items="\n\n".join(
            f"id: {item['id']}\ntext: {item['text']}\nsupporting facts: {'; '.join(item['facts'])}"
            for item in tailoring_case["items"]
        ),
    )
    route = _router().route(AIOperation.RESUME_REWRITE)
    provider = FakeLLMProvider([tailoring_case["recorded_rewrite"]])
    response = provider.generate_structured(
        StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=resume_rewrite_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        ),
        model=route.model,
    )
    return ResumeRewriteResult.model_validate(response.payload)


def _reports(tailoring_case: dict[str, Any]) -> dict[str, Any]:
    """Every suggestion, run through the real truth validator."""
    by_id = {item["id"]: item for item in tailoring_case["items"]}
    reports = {}
    for candidate in _rewrites(tailoring_case).suggestions:
        item = by_id[candidate.item_id]
        reports[candidate.item_id] = validate_rewrite(
            original=item["text"],
            suggested=candidate.suggested_text,
            source_facts=item["facts"],
        )
    return reports


# --- the strategy ---------------------------------------------------------------


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_the_plan_parses_and_says_what_to_lead_with(tailoring_case: dict[str, Any]) -> None:
    result = _strategy(tailoring_case)

    missing = [
        term
        for term in tailoring_case["expect_emphasize"]
        if not any(term.lower() in entry.lower() for entry in result.emphasize)
    ]
    assert not missing, f"{tailoring_case['name']}: plan omits {missing}"


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_a_career_gap_is_named_as_one(tailoring_case: dict[str, Any]) -> None:
    """The distinction ``docs/06-resume-engine.md`` insists on. A career gap
    filed as a resume gap tells someone to rewrite their way out of something
    no amount of rewriting fixes."""
    result = _strategy(tailoring_case)
    gaps = " ".join(result.career_gaps).lower()

    missing = [
        term for term in tailoring_case["expect_career_gap_terms"] if term.lower() not in gaps
    ]
    assert not missing, f"{tailoring_case['name']}: career gaps omit {missing}"


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_the_plan_invents_nothing(tailoring_case: dict[str, Any]) -> None:
    """Withheld evidence is the trap: an unverified skill was shown to the
    model as unconfirmed, and a plan that leads with it would be recommending
    a claim the user never made."""
    result = _strategy(tailoring_case)
    everything = " ".join(
        [
            result.summary,
            result.reorder_note,
            *result.emphasize,
            *result.reduce,
            *result.priority_projects,
            *result.missing_evidence,
        ]
    ).lower()

    offending = [
        term for term in tailoring_case["forbid_strategy_terms"] if term.lower() in everything
    ]
    assert not offending, f"{tailoring_case['name']}: plan invented {offending}"


# --- the rewrites ---------------------------------------------------------------


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_every_suggestion_names_an_item_we_sent(tailoring_case: dict[str, Any]) -> None:
    known = {item["id"] for item in tailoring_case["items"]}

    unknown = [c.item_id for c in _rewrites(tailoring_case).suggestions if c.item_id not in known]
    assert not unknown, f"{tailoring_case['name']}: suggestions reference unknown items {unknown}"


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_an_invented_number_is_blocked(tailoring_case: dict[str, Any]) -> None:
    """The invariant. A figure the profile does not contain never reaches the
    page without the user being told, whatever the model returned."""
    reports = _reports(tailoring_case)

    blocked = sorted(
        item_id
        for item_id, report in reports.items()
        if any(claim.status is ClaimStatus.BLOCKED for claim in report.claims)
    )
    assert blocked == sorted(tailoring_case.get("expect_blocked_items", [])), (
        f"{tailoring_case['name']}: blocked {blocked}"
    )


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_the_blocked_figure_is_quoted_back(tailoring_case: dict[str, Any]) -> None:
    """Naming the number is what makes the message actionable: the user can
    tell at a glance whether it is real and belongs in their profile."""
    reports = _reports(tailoring_case)

    quoted = {
        claim.text
        for report in reports.values()
        for claim in report.claims
        if claim.status is ClaimStatus.BLOCKED
    }
    assert quoted == set(tailoring_case.get("expect_blocked_numbers", []))


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_nothing_unsupported_may_apply_automatically(tailoring_case: dict[str, Any]) -> None:
    reports = _reports(tailoring_case)

    if tailoring_case["expect_all_safe"]:
        assert all(report.status is ClaimStatus.SAFE for report in reports.values())
    else:
        assert any(not report.may_apply_automatically for report in reports.values())


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_a_high_risk_change_is_marked_for_review(tailoring_case: dict[str, Any]) -> None:
    reports = _reports(tailoring_case)

    high = sorted(
        item_id for item_id, report in reports.items() if report.risk is SuggestionRisk.HIGH
    )
    assert high == sorted(tailoring_case.get("expect_high_risk_items", []))


@pytest.mark.parametrize("tailoring_case", CASES, ids=IDS)
def test_the_supporting_facts_actually_reached_the_prompt(tailoring_case: dict[str, Any]) -> None:
    """A rewrite prompt without the evidence is a licence to invent, so what
    was sent matters as much as what came back."""
    prompt = get_prompt(RESUME_REWRITE_LATEST)
    rendered = prompt.render(
        job=tailoring_case["job_text"],
        strategy=tailoring_case["recorded_strategy"]["summary"],
        items="\n\n".join(
            f"id: {item['id']}\ntext: {item['text']}\nsupporting facts: {'; '.join(item['facts'])}"
            for item in tailoring_case["items"]
        ),
    )

    for item in tailoring_case["items"]:
        assert item["id"] in rendered
        for fact in item["facts"]:
            assert fact in rendered
