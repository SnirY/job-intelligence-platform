"""Optional AI enrichment for a finished match.

Runs *after* scoring, and can only add a sentence. The goal permits AI two
bounded jobs — semantic transferability and natural-language explanation — and
this is the second. The first is deliberately not implemented: the explicit
transfer table in :mod:`jip_api.domain.matching.transferable` already covers it
deterministically, and adding a model-proposed transferability path would mean
a score that changes depending on whether an API key was configured.

The contract with the caller is one line: **this may fail, and the match is
already complete.** Every failure is caught and returned as a warning, so a
provider outage costs a paragraph rather than a verdict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    sanitize_json_schema,
    schema_failure_summary,
    timed,
)
from jip_api.application.matching.matcher import Verdict
from jip_api.application.matching.scoring import MatchResult
from jip_api.domain.jobs.analysis import JobRequirement
from jip_prompts import MATCH_EXPLAINER_LATEST, get_prompt

logger = logging.getLogger(__name__)

MAX_VERDICTS_IN_PROMPT = 40
"""Enough to characterise a match. A posting with 120 requirements does not
need every one restated to be summarised, and the items are already on screen."""


class MatchExplanation(BaseModel):
    """What ``match_explainer_v1`` returns.

    One field. There is deliberately nothing here that could carry a score, a
    status, or a recommendation — the model cannot move a number it has no way
    to express.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=1200)


def match_explanation_json_schema() -> dict[str, Any]:
    schema: dict[str, Any] = sanitize_json_schema(MatchExplanation.model_json_schema())
    return schema


@dataclass(slots=True)
class ExplanationOutcome:
    """The summary, or the reason there isn't one."""

    summary: str | None = None
    traces: list[AIRunTrace] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MatchExplainerService:
    """Writes the natural-language summary for a scored match."""

    def __init__(
        self,
        provider: LLMProvider,
        router: ModelRouter,
        *,
        max_attempts: int = 2,
        prompt_name: str = MATCH_EXPLAINER_LATEST,
    ) -> None:
        self._provider = provider
        self._router = router
        self._max_attempts = max_attempts
        self._prompt_name = prompt_name

    def explain(
        self,
        *,
        result: MatchResult,
        verdicts: list[Verdict],
        requirements: dict[Any, JobRequirement],
    ) -> ExplanationOutcome:
        """Summarise a match. Never raises.

        The one method in the AI layer with that guarantee, and it is the whole
        point: the caller has a complete, persisted match by the time this
        runs, so an exception escaping here would turn a cosmetic failure into
        a lost verdict.
        """
        prompt = get_prompt(self._prompt_name)
        route = self._router.route(AIOperation.MATCH_EXPLAIN)

        rendered = prompt.render(
            score=(
                f"{result.overall_score} out of 100 ({result.alignment_label})"
                if result.overall_score is not None
                else f"not scored ({result.alignment_label})"
            ),
            recommendation=str(result.recommendation),
            verdicts=_format_verdicts(verdicts, requirements),
        )
        input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

        request = StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=match_explanation_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        )

        traces: list[AIRunTrace] = []

        def attempt(number: int) -> str:
            trace = AIRunTrace(
                operation=str(AIOperation.MATCH_EXPLAIN),
                provider=self._provider.name,
                model=route.model,
                prompt_version=prompt.name,
                input_hash=input_hash,
                attempt=number,
            )
            traces.append(trace)

            with timed(trace):
                try:
                    response = self._provider.generate_structured(request, model=route.model)
                except AIError as error:
                    trace.mark_failure(error.code, str(error))
                    raise

                cost = route.pricing.estimate(response.usage) if route.pricing else None
                trace.mark_success(response.usage, cost=cost)

                try:
                    parsed = MatchExplanation.model_validate(response.payload)
                except ValidationError as exc:
                    trace.mark_failure(
                        AIFailureCode.INVALID_OUTPUT,
                        f"Output failed schema check: {schema_failure_summary(exc)}",
                    )
                    raise AIError(
                        AIFailureCode.INVALID_OUTPUT,
                        "The explainer returned data in an unexpected shape.",
                        details=str(exc)[:500],
                    ) from exc

            return parsed.summary.strip()

        try:
            summary = run_with_retry(attempt, max_attempts=self._max_attempts)
        except AIError as error:
            logger.info("Match explanation unavailable", extra={"code": str(error.code)})
            return ExplanationOutcome(
                summary=None,
                traces=traces,
                warnings=[
                    "A written summary could not be generated. The match itself is complete."
                ],
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Match explainer raised unexpectedly", exc_info=exc)
            return ExplanationOutcome(
                summary=None,
                traces=traces,
                warnings=[
                    "A written summary could not be generated. The match itself is complete."
                ],
            )

        return ExplanationOutcome(summary=summary, traces=traces)


def _format_verdicts(verdicts: list[Verdict], requirements: dict[Any, JobRequirement]) -> str:
    """Render the verdicts as lines for the prompt.

    Ordered by weight then by the posting's order, so the model reads the
    requirements that matter first and a truncated list keeps the important
    ones.
    """
    ordered = sorted(verdicts, key=lambda v: (-float(v.weight), v.source_order))

    lines: list[str] = []
    for verdict in ordered[:MAX_VERDICTS_IN_PROMPT]:
        requirement = requirements.get(verdict.requirement_id)
        label = requirement.normalized_text if requirement else "(requirement)"
        blocker = " [BLOCKER]" if verdict.is_blocker else ""
        lines.append(f"- {label}: {verdict.status}{blocker} — {verdict.explanation}")

    remaining = len(ordered) - len(lines)
    if remaining > 0:
        lines.append(f"- (and {remaining} lower-weighted requirements)")
    return "\n".join(lines)
