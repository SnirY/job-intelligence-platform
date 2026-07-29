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

import json
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

# ---------------------------------------------------------------------------
# DEV-017. Flip to True to restore provider-side schema enforcement.
#
# This is the only one of the platform's four schemas Anthropic refuses to
# compile into a grammar: 6933 chars, 125 nodes, four arrays of objects, two of
# which nest their own arrays of objects. `job_parse` (2941), `job_analysis`
# (1962), and `match_explain` (396) all compile and are untouched by this flag.
#
# The cost is structural rather than textual — measured against claude-sonnet-5,
# dropping every enum (6579), every description (4895), and both together (4541)
# all still failed, while a flattened equivalent covering the same four sections
# compiled at 1739. Shortening the schema text cannot fix it; only removing
# nesting can.
#
# With the constraint off, a malformed answer becomes *possible* rather than
# impossible. Everything that decides whether data is trustworthy is unchanged:
# the schema is sent in the prompt, `ResumeParseResult` validates the reply, the
# fabrication guard still requires `source_text` on every claim, and
# `run_with_retry` still gets its attempts. What moved is only *when* a bad
# answer is caught.
#
# The better long-term fix is one call per section — it keeps the constraint and
# every field, at four calls instead of one. That is a pipeline change; this is
# one boolean, and it unblocks seeing what the model actually produces first.
# ---------------------------------------------------------------------------
_CONSTRAIN_OUTPUT = False

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

        schema = resume_parse_json_schema()

        # The prompt tells the model to return "one JSON object matching the
        # provided schema", and the schema used to be provided out of band by
        # `output_config.format`. With that constraint off (DEV-017), the
        # sentence would point at nothing and the model would infer the shape
        # from prose — which it gets wrong in exactly the places prose is
        # weakest: it returned `technologies: ["Python"]` where the schema wants
        # `[{"name": "Python", ...}]`.
        #
        # So the schema moves into the prompt. It is appended to the system text
        # *before* the input hash is computed, so the hash still describes what
        # was actually sent and two runs remain comparable.
        system = prompt.system
        if not _CONSTRAIN_OUTPUT:
            system = f"{system}\n\n## Schema\n\n```json\n{json.dumps(schema, indent=2)}\n```"

        input_hash = compute_input_hash(prompt.name, route.model, system, rendered)

        request = StructuredRequest(
            system=system,
            user=rendered,
            json_schema=schema,
            max_output_tokens=route.max_output_tokens,
            effort=route.effort,
            constrain_output=_CONSTRAIN_OUTPUT,
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
