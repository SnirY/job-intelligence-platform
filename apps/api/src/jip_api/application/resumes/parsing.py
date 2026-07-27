"""``ResumeParsingService`` — document text in, reviewable candidates out.

This is the AI pipeline from ``docs/05-ai-and-matching.md``, in order:

```text
Input validation -> Prompt construction -> Model call -> Structured output
-> Schema validation -> Business validation
```

Persistence is deliberately not in that list here. The service returns a result;
storing it is the pipeline's job, which keeps this testable without a database
and keeps the AI layer from ever writing to one directly.
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
from jip_api.application.resumes.schema import ResumeParseResult, resume_parse_json_schema
from jip_api.application.resumes.validation import ValidatedExtraction, validate_parse_result
from jip_prompts import RESUME_PARSER_LATEST, get_prompt

logger = logging.getLogger(__name__)

_FORMAT_LABELS = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (DOCX)",
}


@dataclass(slots=True)
class ResumeParseOutcome:
    """Everything one parse produced, including the failed attempts.

    Traces are returned rather than written here because ``AIRun`` rows have to
    be persisted whether the parse succeeded or failed, and the caller owns the
    transaction.
    """

    result: ResumeParseResult
    validated: ValidatedExtraction
    raw_payload: dict[str, object]
    prompt_version: str
    input_hash: str
    model: str
    provider: str
    traces: list[AIRunTrace] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ResumeParsingService:
    """Parses resume text into structured candidates.

    Matches the ``ResumeParsingService`` interface in
    ``docs/10-api-contracts.md``. Focused on one operation, per the no-god-
    services rule in ``docs/11-engineering-standards.md``.
    """

    def __init__(
        self,
        provider: LLMProvider,
        router: ModelRouter,
        *,
        max_input_chars: int,
        max_attempts: int = 3,
        prompt_name: str = RESUME_PARSER_LATEST,
    ) -> None:
        self._provider = provider
        self._router = router
        self._max_input_chars = max_input_chars
        self._max_attempts = max_attempts
        self._prompt_name = prompt_name

    def parse(self, document_text: str, *, content_type: str) -> ResumeParseOutcome:
        """Parse ``document_text``.

        Raises :class:`AIError` when every attempt failed. The caller preserves
        the document either way — ``GOAL.md`` requires a failure to leave the
        underlying resource intact and recoverable.
        """
        text = document_text.strip()
        if not text:
            raise AIError(
                AIFailureCode.CONTENT_UNAVAILABLE,
                "There is no text to parse in this document.",
            )

        prompt = get_prompt(self._prompt_name)
        route = self._router.route(AIOperation.RESUME_PARSE)

        prepared, truncated = truncate_for_prompt(text, max_chars=self._max_input_chars)
        warnings: list[str] = []
        if truncated:
            warnings.append(
                "This document was longer than we send to the parser, so only the "
                f"first {self._max_input_chars:,} characters were read."
            )

        rendered = prompt.render(
            resume_text=prepared,
            document_format=_FORMAT_LABELS.get(content_type, "document"),
        )
        input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

        request = StructuredRequest(
            system=prompt.system,
            user=rendered,
            json_schema=resume_parse_json_schema(),
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
        )

        traces: list[AIRunTrace] = []

        def attempt(number: int) -> ResumeParseOutcome:
            trace = AIRunTrace(
                operation=str(AIOperation.RESUME_PARSE),
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
                    result = ResumeParseResult.model_validate(response.payload)
                except ValidationError as exc:
                    # Well-formed JSON that is not the agreed shape. Classified
                    # as INVALID_OUTPUT rather than VALIDATION_FAILURE: nothing
                    # got as far as a business rule.
                    trace.mark_failure(AIFailureCode.INVALID_OUTPUT, "Output failed schema check")
                    raise AIError(
                        AIFailureCode.INVALID_OUTPUT,
                        "The parser returned data in an unexpected shape.",
                        details=str(exc)[:1000],
                    ) from exc

            validated = validate_parse_result(result, document_text=text)

            return ResumeParseOutcome(
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
            "Parsed resume",
            extra={
                "prompt_version": outcome.prompt_version,
                "model": outcome.model,
                "attempts": len(outcome.traces),
                "candidates": len(outcome.validated.candidates),
            },
        )
        return outcome

    @staticmethod
    def traces_from_failure(
        provider: str, model: str, prompt_version: str, input_hash: str, error: AIError
    ) -> AIRunTrace:
        """Build a trace for a failure that happened before any call was made."""
        trace = AIRunTrace(
            operation=str(AIOperation.RESUME_PARSE),
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            input_hash=input_hash,
        )
        trace.mark_failure(error.code, str(error))
        return trace
