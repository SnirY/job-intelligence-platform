"""The tailoring pipeline.

```text
Selection -> Strategy -> Suggestions -> Truth Validation -> User Review -> Version
```

``docs/11-engineering-standards.md`` requires exactly that order, and
``docs/09-mvp-roadmap.md`` says tailoring is incomplete if one model call
rewrites the whole document. So there are two model calls, staged, with
deterministic work on both sides of them:

- **Before**: selection picks the evidence, without a model.
- **Between**: the strategy is persisted and shown before any line changes.
- **After**: every suggestion is validated against the career facts by
  :mod:`jip_api.application.resumes.truth`, which is also deterministic.

Neither model call can reach a resume on its own. The user accepts each
suggestion, and only then is a version written.

Both operations persist their ``AIRun`` traces **on the failure path as well as
the success path**, which is the shape DEV-016 records as missing elsewhere.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_ai import (
    AIError,
    AIFailureCode,
    AIOperation,
    AIRunTrace,
    LLMProvider,
    ModelRouter,
    StructuredRequest,
    compute_input_hash,
    run_with_retry,
    schema_failure_summary,
    timed,
)
from jip_api.application.errors import ApplicationError
from jip_api.application.matching import queries as match_queries
from jip_api.application.resumes.selection import SelectionResult, select_for_match, to_sections
from jip_api.application.resumes.tailoring_schema import (
    ResumeRewriteResult,
    ResumeStrategyResult,
    resume_rewrite_json_schema,
    resume_strategy_json_schema,
)
from jip_api.application.resumes.truth import validate_rewrite
from jip_api.domain.ai.models import AIRun, AIRunStatus
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import JobMatch
from jip_api.domain.resumes.models import ResumeItem, ResumeSection, ResumeVersion
from jip_api.domain.resumes.tailoring import (
    ClaimStatus,
    ResumeClaim,
    ResumeStrategy,
    ResumeSuggestion,
    SuggestionStatus,
    SuggestionType,
)
from jip_prompts import RESUME_REWRITE_LATEST, RESUME_STRATEGY_LATEST, get_prompt

logger = logging.getLogger(__name__)

ENTITY_TYPE = "resume_strategy"


class StrategyNotPossibleError(ApplicationError):
    """There is no match to tailor against."""


@dataclass(slots=True)
class StrategyOutcome:
    strategy: ResumeStrategy
    selection: SelectionResult
    warnings: list[str] = field(default_factory=list)


def create_strategy(
    session: Session,
    provider: LLMProvider | None,
    router: ModelRouter | None,
    *,
    user_id: uuid.UUID,
    job: Job,
    max_attempts: int = 2,
) -> StrategyOutcome:
    """Plan the tailoring for one job.

    Requires a match, not merely an analysis: ``docs/06-resume-engine.md`` makes
    a strategy answer "which real career gaps remain", and that is match data.
    Refused with a reason otherwise, mirroring how Phase 6 refuses to match a
    job with no analysis.

    ``provider`` may be ``None``. Selection is deterministic and useful on its
    own, so a strategy without AI is a real, if thinner, result rather than an
    error — which is what keeps AI failure from blocking manual use
    (``docs/02-user-flows.md``: AI failure must never block manual usage).
    """
    match = match_queries.latest_match(session, user_id, job.id)
    if match is None:
        raise StrategyNotPossibleError(
            "This job has not been matched against your profile yet, so there is "
            "nothing to tailor from."
        )

    selection = select_for_match(session, user_id, match)
    warnings: list[str] = []

    result = ResumeStrategyResult()
    provider_name = model_name = prompt_name = None
    traces: list[AIRunTrace] = []

    if provider is not None and router is not None:
        try:
            result, provider_name, model_name, prompt_name = _ask_for_strategy(
                provider,
                router,
                job=job,
                match=match,
                selection=selection,
                max_attempts=max_attempts,
                traces=traces,
            )
        except AIError as error:
            warnings.append(
                "A written plan could not be generated, so this strategy shows the "
                "selected evidence only. The selection itself is unaffected."
            )
            logger.info("Strategy generation failed", extra={"code": str(error.code)})

    # Persisted whether the call succeeded or failed. DEV-016 records that the
    # older pipelines write traces only on the success path, which loses every
    # trace of an operation that failed outright; this does not copy that.
    for trace in traces:
        session.add(_ai_run(trace, user_id=user_id, entity_id=job.id))

    next_version = (
        session.execute(
            select(func.coalesce(func.max(ResumeStrategy.version), 0)).where(
                ResumeStrategy.job_id == job.id
            )
        ).scalar_one()
        + 1
    )

    strategy = ResumeStrategy(
        user_id=user_id,
        job_id=job.id,
        match_id=match.id,
        version=next_version,
        summary=result.summary or None,
        emphasize=list(result.emphasize),
        reduce=list(result.reduce),
        reorder_note=result.reorder_note or None,
        priority_projects=list(result.priority_projects),
        missing_evidence=list(result.missing_evidence),
        career_gaps=list(result.career_gaps),
        selection=_selection_json(selection),
        provider=provider_name,
        model=model_name,
        prompt_version=prompt_name,
        warnings=warnings,
    )
    session.add(strategy)
    session.flush()

    logger.info(
        "Created resume strategy",
        extra={"job_id": str(job.id), "version": next_version, "ai": provider_name is not None},
    )
    return StrategyOutcome(strategy=strategy, selection=selection, warnings=warnings)


def _ask_for_strategy(
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: Job,
    match: JobMatch,
    selection: SelectionResult,
    max_attempts: int,
    traces: list[AIRunTrace],
) -> tuple[ResumeStrategyResult, str, str, str]:
    prompt = get_prompt(RESUME_STRATEGY_LATEST)
    route = router.route(AIOperation.RESUME_STRATEGY)

    rendered = prompt.render(
        job=f"{job.title}\n{(job.description or '')[:6000]}",
        match=_match_summary(match),
        selected="\n".join(f"- [{c.source_type}] {c.text}" for c in selection.all_selected[:40])
        or "(nothing selected)",
        unselected="\n".join(
            f"- [{c.source_type}] {c.text} (not confirmed by the user)"
            for c in selection.excluded_unverified[:15]
        )
        or "(nothing withheld)",
    )
    input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

    request = StructuredRequest(
        system=prompt.system,
        user=rendered,
        json_schema=resume_strategy_json_schema(),
        max_output_tokens=route.max_output_tokens,
        effort=route.effort,
    )

    def attempt(number: int) -> ResumeStrategyResult:
        trace = AIRunTrace(
            operation=str(AIOperation.RESUME_STRATEGY),
            provider=provider.name,
            model=route.model,
            prompt_version=prompt.name,
            input_hash=input_hash,
            attempt=number,
        )
        traces.append(trace)

        with timed(trace):
            try:
                response = provider.generate_structured(request, model=route.model)
            except AIError as error:
                trace.mark_failure(error.code, str(error))
                raise

            cost = route.pricing.estimate(response.usage) if route.pricing else None
            trace.mark_success(response.usage, cost=cost)

            try:
                return ResumeStrategyResult.model_validate(response.payload)
            except ValidationError as exc:
                trace.mark_failure(
                    AIFailureCode.INVALID_OUTPUT,
                    f"Output failed schema check: {schema_failure_summary(exc)}",
                )
                raise AIError(
                    AIFailureCode.INVALID_OUTPUT,
                    "The planner returned data in an unexpected shape.",
                    details=str(exc)[:500],
                ) from exc

    result = run_with_retry(attempt, max_attempts=max_attempts)
    return result, provider.name, route.model, prompt.name


@dataclass(slots=True)
class SuggestionOutcome:
    suggestions: list[ResumeSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def create_suggestions(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    user_id: uuid.UUID,
    strategy: ResumeStrategy,
    version: ResumeVersion,
    job: Job,
    max_attempts: int = 2,
) -> SuggestionOutcome:
    """Propose one change per line, then validate each against the evidence.

    The model's output is untrusted until :func:`validate_rewrite` has run over
    it, per ``docs/11-engineering-standards.md``. A suggestion that would
    introduce a number the profile does not contain is stored **BLOCKED** rather
    than discarded, because the user may know the figure is real — and
    ``docs/06`` wants the system to *ask* for a missing metric, never to invent
    one.
    """
    items = _items_with_sources(session, version.id)
    if not items:
        return SuggestionOutcome(warnings=["This version has no content to improve yet."])

    prompt = get_prompt(RESUME_REWRITE_LATEST)
    route = router.route(AIOperation.RESUME_REWRITE)

    rendered = prompt.render(
        job=f"{job.title}\n{(job.description or '')[:4000]}",
        strategy=_strategy_summary(strategy),
        items="\n\n".join(
            f"id: {item.id}\ntext: {item.text}\nsupporting facts: {'; '.join(facts) or '(none)'}"
            for item, facts in items
        ),
    )
    input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

    request = StructuredRequest(
        system=prompt.system,
        user=rendered,
        json_schema=resume_rewrite_json_schema(),
        max_output_tokens=route.max_output_tokens,
        effort=route.effort,
    )
    traces: list[AIRunTrace] = []

    def attempt(number: int) -> ResumeRewriteResult:
        trace = AIRunTrace(
            operation=str(AIOperation.RESUME_REWRITE),
            provider=provider.name,
            model=route.model,
            prompt_version=prompt.name,
            input_hash=input_hash,
            attempt=number,
        )
        traces.append(trace)

        with timed(trace):
            try:
                response = provider.generate_structured(request, model=route.model)
            except AIError as error:
                trace.mark_failure(error.code, str(error))
                raise

            cost = route.pricing.estimate(response.usage) if route.pricing else None
            trace.mark_success(response.usage, cost=cost)

            try:
                return ResumeRewriteResult.model_validate(response.payload)
            except ValidationError as exc:
                trace.mark_failure(
                    AIFailureCode.INVALID_OUTPUT,
                    f"Output failed schema check: {schema_failure_summary(exc)}",
                )
                raise AIError(
                    AIFailureCode.INVALID_OUTPUT,
                    "The rewriter returned data in an unexpected shape.",
                    details=str(exc)[:500],
                ) from exc

    outcome = SuggestionOutcome()
    try:
        result = run_with_retry(attempt, max_attempts=max_attempts)
    except AIError as error:
        for trace in traces:
            session.add(_ai_run(trace, user_id=user_id, entity_id=strategy.id))
        session.flush()
        outcome.warnings.append(
            "Suggestions could not be generated. Your resume is unchanged, and you can try again."
        )
        logger.info("Rewrite generation failed", extra={"code": str(error.code)})
        return outcome

    for trace in traces:
        session.add(_ai_run(trace, user_id=user_id, entity_id=strategy.id))

    by_id = {str(item.id): (item, facts) for item, facts in items}
    dropped = 0

    for order, candidate in enumerate(result.suggestions):
        entry = by_id.get(candidate.item_id)
        if entry is None:
            # An id we never sent. Silently ignored rather than trusted: it
            # would otherwise be a way to write to an item the user does not own.
            dropped += 1
            continue
        item, facts = entry

        report = validate_rewrite(
            original=item.text, suggested=candidate.suggested_text, source_facts=facts
        )

        suggestion = ResumeSuggestion(
            user_id=user_id,
            strategy_id=strategy.id,
            item_id=item.id,
            suggestion_type=SuggestionType(candidate.kind),
            status=SuggestionStatus.PENDING,
            risk=report.risk,
            original_text=item.text,
            suggested_text=candidate.suggested_text,
            rationale=candidate.rationale or None,
            display_order=order,
        )
        session.add(suggestion)
        session.flush()

        for claim in report.claims:
            session.add(
                ResumeClaim(
                    user_id=user_id,
                    suggestion_id=suggestion.id,
                    text=claim.text,
                    status=claim.status,
                    explanation=claim.explanation,
                    source_type=str(item.source_type),
                    source_entity_id=item.source_entity_id,
                    confidence=claim.confidence,
                )
            )

        outcome.suggestions.append(suggestion)

    if dropped:
        outcome.warnings.append(
            f"{dropped} suggestion{'s' if dropped != 1 else ''} referred to lines that are "
            "not in this resume and were ignored."
        )

    session.flush()
    logger.info(
        "Created resume suggestions",
        extra={"strategy_id": str(strategy.id), "suggestions": len(outcome.suggestions)},
    )
    return outcome


def blocked_count(session: Session, strategy_id: uuid.UUID) -> int:
    """How many suggestions carry a blocked claim.

    Surfaced on the review screen: a blocked suggestion is the one case where
    accepting would put something untrue on the page.
    """
    return int(
        session.execute(
            select(func.count(func.distinct(ResumeClaim.suggestion_id)))
            .join(ResumeSuggestion, ResumeSuggestion.id == ResumeClaim.suggestion_id)
            .where(
                ResumeSuggestion.strategy_id == strategy_id,
                ResumeClaim.status == ClaimStatus.BLOCKED,
            )
        ).scalar_one()
    )


# --- helpers ------------------------------------------------------------------


def _items_with_sources(
    session: Session, version_id: uuid.UUID
) -> list[tuple[ResumeItem, list[str]]]:
    """Every item, with the career text that supports it.

    The supporting facts are what the rewrite is allowed to draw on, and what
    truth validation checks the result against. For now that is the item's own
    text — the words the user already approved — which is the conservative
    reading: a rewrite may rephrase what is there and may not import anything
    new.
    """
    rows = list(
        session.execute(
            select(ResumeItem)
            .join(ResumeSection, ResumeSection.id == ResumeItem.section_id)
            .where(ResumeSection.version_id == version_id)
            .order_by(ResumeSection.display_order, ResumeItem.display_order)
        ).scalars()
    )
    return [(item, [item.text] + ([item.heading] if item.heading else [])) for item in rows]


def _match_summary(match: JobMatch) -> str:
    parts = [
        f"Alignment: {match.overall_score if match.overall_score is not None else 'not scored'}"
        f" ({match.alignment_label})",
        f"Recommendation: {match.recommendation}",
    ]
    parts.extend(f"- {reason}" for reason in match.recommendation_reasons)
    return "\n".join(parts)


def _strategy_summary(strategy: ResumeStrategy) -> str:
    lines = [strategy.summary or "(no written plan)"]
    if strategy.emphasize:
        lines.append("Emphasise: " + "; ".join(strategy.emphasize))
    if strategy.reduce:
        lines.append("Reduce: " + "; ".join(strategy.reduce))
    return "\n".join(lines)


def _selection_json(selection: SelectionResult) -> dict[str, object]:
    return {
        "sections": [
            {
                "kind": str(kind),
                "items": [
                    {
                        "source_type": str(c.source_type),
                        "entity_id": str(c.entity_id),
                        "text": c.text,
                        "heading": c.heading,
                        "score": c.score,
                        "reasons": list(c.reasons),
                    }
                    for c in candidates
                ],
            }
            for kind, candidates in to_sections(selection)
        ],
        "withheld_unverified": [
            {"text": c.text, "verification_status": c.verification_status}
            for c in selection.excluded_unverified
        ],
    }


def _ai_run(trace: AIRunTrace, *, user_id: uuid.UUID, entity_id: uuid.UUID) -> AIRun:
    return AIRun(
        user_id=user_id,
        operation=trace.operation,
        entity_type=ENTITY_TYPE,
        entity_id=entity_id,
        provider=trace.provider,
        model=trace.model,
        prompt_version=trace.prompt_version,
        input_hash=trace.input_hash,
        status=AIRunStatus.SUCCEEDED if trace.succeeded else AIRunStatus.FAILED,
        failure_code=str(trace.failure_code) if trace.failure_code else None,
        error_message=trace.error_message,
        latency_ms=trace.latency_ms,
        input_tokens=trace.usage.input_tokens,
        output_tokens=trace.usage.output_tokens,
        estimated_cost_usd=trace.estimated_cost_usd,
        attempt=trace.attempt,
    )


def selection_to_content(selection: SelectionResult) -> str:
    """The selection as JSON, for a client that wants to seed an editor."""
    return json.dumps(_selection_json(selection))
