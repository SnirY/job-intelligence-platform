"""``JobParsingService`` and ``JobAnalyzerService``.

The two internal interfaces ``docs/10-api-contracts.md`` names — ``JobParser``
and ``JobAnalyzer`` — each running the pipeline from
``docs/05-ai-and-matching.md``:

```text
Input validation -> Prompt construction -> Model call -> Structured output
-> Schema validation -> Business validation
```

Persistence is not on that list, here or in the resume services. They return
results; storing them is the pipeline's job, which keeps both testable without
a database and keeps the AI layer from ever writing to one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

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
    timed,
    truncate_for_prompt,
)
from jip_api.application.jobs.analysis_schema import (
    JobAnalysisResult,
    JobParseResult,
    job_analysis_json_schema,
    job_parse_json_schema,
)
from jip_api.application.jobs.analysis_validation import (
    ValidatedAnalysis,
    ValidatedParse,
    validate_analysis_result,
    validate_parse_result,
)
from jip_prompts import JOB_ANALYSIS_LATEST, JOB_PARSER_LATEST, get_prompt

logger = logging.getLogger(__name__)

MAX_REQUIREMENTS_IN_ANALYSIS_PROMPT = 60
"""How many requirements the analysis step is shown.

The analysis reads the posting too, so the requirement list is context rather
than the whole input. A posting with 120 requirements would otherwise spend most
of its token budget restating what the model is about to read anyway.
"""


@dataclass(slots=True)
class JobParseOutcome:
    """Everything one parse produced, including the failed attempts."""

    result: JobParseResult
    validated: ValidatedParse
    raw_payload: dict[str, object]
    prompt_version: str
    input_hash: str
    model: str
    provider: str
    traces: list[AIRunTrace] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JobAnalysisOutcome:
    """Everything one analysis produced."""

    result: JobAnalysisResult
    validated: ValidatedAnalysis
    raw_payload: dict[str, object]
    prompt_version: str
    model: str
    provider: str
    traces: list[AIRunTrace] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class JobParsingService:
    """Reads a posting into requirements and responsibilities.

    ``JobParser.parse(job_content) -> JobParseResult`` from
    ``docs/10-api-contracts.md``. One operation, per the no-god-services rule in
    ``docs/11-engineering-standards.md``.
    """

    def __init__(
        self,
        provider: LLMProvider,
        router: ModelRouter,
        *,
        max_input_chars: int,
        max_attempts: int = 3,
        prompt_name: str = JOB_PARSER_LATEST,
    ) -> None:
        self._provider = provider
        self._router = router
        self._max_input_chars = max_input_chars
        self._max_attempts = max_attempts
        self._prompt_name = prompt_name

    def parse(self, job_text: str, *, source_note: str = "") -> JobParseOutcome:
        """Parse ``job_text``.

        Raises :class:`AIError` when every attempt failed. The caller keeps the
        job either way — ``GOAL.md`` requires a failure to leave the underlying
        resource intact.
        """
        text = job_text.strip()
        if not text:
            raise AIError(
                AIFailureCode.CONTENT_UNAVAILABLE,
                "This job has no description to analyse yet.",
            )

        prompt = get_prompt(self._prompt_name)
        route = self._router.route(AIOperation.JOB_PARSE)

        prepared, truncated = truncate_for_prompt(text, max_chars=self._max_input_chars)
        warnings: list[str] = []
        if truncated:
            warnings.append(
                "This posting was longer than we send to the parser, so only the first "
                f"{self._max_input_chars:,} characters were read."
            )

        rendered = prompt.render(
            job_text=prepared,
            source_note=source_note or "This is the description as it was saved.",
        )
        input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

        request = StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=job_parse_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        )

        traces: list[AIRunTrace] = []

        def attempt(number: int) -> JobParseOutcome:
            trace = AIRunTrace(
                operation=str(AIOperation.JOB_PARSE),
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
                    result = JobParseResult.model_validate(response.payload)
                except ValidationError as exc:
                    # Well-formed JSON in the wrong shape. INVALID_OUTPUT rather
                    # than VALIDATION_FAILURE: nothing reached a business rule.
                    trace.mark_failure(AIFailureCode.INVALID_OUTPUT, "Output failed schema check")
                    raise AIError(
                        AIFailureCode.INVALID_OUTPUT,
                        "The parser returned data in an unexpected shape.",
                        details=str(exc)[:1000],
                    ) from exc

            # Validated against the *prepared* text, not the original: a
            # requirement quoting a passage that was truncated away cannot be
            # verified, and treating it as present would defeat the check.
            validated = validate_parse_result(result, job_text=prepared)

            return JobParseOutcome(
                result=result,
                validated=validated,
                raw_payload=dict(response.payload),
                prompt_version=prompt.name,
                input_hash=input_hash,
                model=response.model or route.model,
                provider=self._provider.name,
                traces=traces,
                warnings=[*warnings, *validated.warnings],
            )

        outcome = run_with_retry(attempt, max_attempts=self._max_attempts)
        logger.info(
            "Parsed job posting",
            extra={
                "prompt_version": outcome.prompt_version,
                "model": outcome.model,
                "attempts": len(outcome.traces),
                "requirements": len(outcome.validated.requirements),
            },
        )
        return outcome


class JobAnalyzerService:
    """Interprets a parsed posting: role family and seniority.

    ``JobAnalyzer.analyze(parsed_job) -> JobAnalysisResult`` from
    ``docs/10-api-contracts.md``.
    """

    def __init__(
        self,
        provider: LLMProvider,
        router: ModelRouter,
        *,
        max_input_chars: int,
        max_attempts: int = 3,
        prompt_name: str = JOB_ANALYSIS_LATEST,
    ) -> None:
        self._provider = provider
        self._router = router
        self._max_input_chars = max_input_chars
        self._max_attempts = max_attempts
        self._prompt_name = prompt_name

    def analyze(self, job_text: str, parse: ValidatedParse) -> JobAnalysisOutcome:
        """Interpret a posting whose requirements have already been extracted."""
        prompt = get_prompt(self._prompt_name)
        route = self._router.route(AIOperation.JOB_ANALYSIS)

        prepared, _ = truncate_for_prompt(job_text.strip(), max_chars=self._max_input_chars)
        rendered = prompt.render(
            job_text=prepared,
            requirements=_format_requirements(parse),
        )
        input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

        request = StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=job_analysis_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        )

        traces: list[AIRunTrace] = []

        def attempt(number: int) -> JobAnalysisOutcome:
            trace = AIRunTrace(
                operation=str(AIOperation.JOB_ANALYSIS),
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
                    result = JobAnalysisResult.model_validate(response.payload)
                except ValidationError as exc:
                    trace.mark_failure(AIFailureCode.INVALID_OUTPUT, "Output failed schema check")
                    raise AIError(
                        AIFailureCode.INVALID_OUTPUT,
                        "The analysis returned data in an unexpected shape.",
                        details=str(exc)[:1000],
                    ) from exc

            validated = validate_analysis_result(result, has_requirements=bool(parse.requirements))

            return JobAnalysisOutcome(
                result=result,
                validated=validated,
                raw_payload=dict(response.payload),
                prompt_version=prompt.name,
                model=response.model or route.model,
                provider=self._provider.name,
                traces=traces,
                warnings=list(validated.warnings),
            )

        outcome = run_with_retry(attempt, max_attempts=self._max_attempts)
        logger.info(
            "Analysed job posting",
            extra={
                "prompt_version": outcome.prompt_version,
                "model": outcome.model,
                "attempts": len(outcome.traces),
                "seniority": str(outcome.validated.seniority),
            },
        )
        return outcome


def _format_requirements(parse: ValidatedParse) -> str:
    """Render the parse as context for the analysis prompt.

    Plain lines rather than JSON: the model is reading this, not parsing it, and
    the importance is what matters for judging seniority — a posting full of
    PREFERRED items reads differently from one full of CORE ones.
    """
    if not parse.requirements:
        return "(nothing could be extracted from this posting)"

    lines = [
        f"- [{requirement.requirement_type}/{requirement.importance}] {requirement.normalized_text}"
        for requirement in parse.requirements[:MAX_REQUIREMENTS_IN_ANALYSIS_PROMPT]
    ]
    if len(parse.requirements) > MAX_REQUIREMENTS_IN_ANALYSIS_PROMPT:
        remaining = len(parse.requirements) - MAX_REQUIREMENTS_IN_ANALYSIS_PROMPT
        lines.append(f"- (and {remaining} more)")
    return "\n".join(lines)
