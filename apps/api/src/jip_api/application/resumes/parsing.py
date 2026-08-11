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

import hashlib
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

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
    truncate_for_prompt,
)
from jip_api.application.resumes.schema import (
    SECTION_MODELS,
    ResumeParseResult,
    combine_sections,
    section_json_schema,
)
from jip_api.application.resumes.validation import ValidatedExtraction, validate_parse_result
from jip_prompts import RESUME_SECTION_PROMPTS, SECTION_LABELS, get_prompt

logger = logging.getLogger(__name__)

RESUME_SECTION_SET = "resume_sections_v1"
"""What a `DocumentExtraction` records for a parse made of four calls.

Not a registered prompt: no single template produced the row. Each `ai_runs`
row carries the section prompt that produced *it*, so nothing about the
provenance is lost — this names which pipeline read the document, which is the
question the extraction row is asked.

Bumped when the set changes: adding a fifth section, or re-versioning any of the
four, makes this `resume_sections_v2`. `docs/05` requires a recorded version to
keep meaning what it meant, and a set is a version like any other.
"""

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
    ) -> None:
        self._provider = provider
        self._router = router
        self._max_input_chars = max_input_chars
        self._max_attempts = max_attempts

    def parse(
        self,
        document_text: str,
        *,
        content_type: str,
        traces: list[AIRunTrace] | None = None,
    ) -> ResumeParseOutcome:
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

        route = self._router.route(AIOperation.RESUME_PARSE)

        prepared, truncated = truncate_for_prompt(text, max_chars=self._max_input_chars)
        warnings: list[str] = []
        if truncated:
            warnings.append(
                "This document was longer than we send to the parser, so only the "
                f"first {self._max_input_chars:,} characters were read."
            )

        document_format = _FORMAT_LABELS.get(content_type, "document")
        collected: list[AIRunTrace] = traces if traces is not None else []

        # One call per section (DEV-017). Each schema compiles, so constrained
        # decoding is on for all four — the workaround that pasted the schema
        # into the prompt is gone with the combined call it existed for.
        #
        # Retried per section rather than across the set. A flaky projects call
        # used to re-run skills, experiences and education with it, at three
        # wasted requests per attempt, and re-rolled answers that were already
        # correct.
        parts: dict[str, BaseModel] = {}
        payloads: dict[str, object] = {}
        hashes: list[str] = []
        last_model: str | None = None

        for prompt_name in RESUME_SECTION_PROMPTS:
            section = get_prompt(prompt_name)
            rendered = section.render(
                resume_text=prepared,
                document_format=document_format,
                section_label=SECTION_LABELS[prompt_name],
            )
            schema = section_json_schema(prompt_name)
            input_hash = compute_input_hash(prompt_name, route.model, section.system, rendered)
            hashes.append(input_hash)

            request = StructuredRequest(
                system=section.system,
                user=rendered,
                json_schema=schema,
                max_output_tokens=route.max_output_tokens,
                effort=route.effort,
                constrain_output=True,
            )
            model_for_section = SECTION_MODELS[prompt_name]

            def attempt_section(
                number: int,
                *,
                _name: str = prompt_name,
                _hash: str = input_hash,
                _request: StructuredRequest = request,
                _model: type[BaseModel] = model_for_section,
            ) -> tuple[BaseModel, dict[str, object], str]:
                trace = AIRunTrace(
                    operation=str(AIOperation.RESUME_PARSE),
                    provider=self._provider.name,
                    model=route.model,
                    prompt_version=_name,
                    input_hash=_hash,
                    attempt=number,
                )
                collected.append(trace)

                with timed(trace):
                    try:
                        response = self._provider.generate_structured(_request, model=route.model)
                    except AIError as error:
                        trace.mark_failure(error.code, str(error))
                        raise

                    cost = route.pricing.estimate(response.usage) if route.pricing else None
                    trace.mark_success(response.usage, cost=cost)

                    try:
                        parsed = _model.model_validate(response.payload)
                    except ValidationError as exc:
                        # Well-formed JSON that is not the agreed shape.
                        # INVALID_OUTPUT rather than VALIDATION_FAILURE: nothing
                        # got as far as a business rule.
                        trace.mark_failure(
                            AIFailureCode.INVALID_OUTPUT,
                            f"Output failed schema check: {schema_failure_summary(exc)}",
                        )
                        raise AIError(
                            AIFailureCode.INVALID_OUTPUT,
                            "The parser returned data in an unexpected shape.",
                            details=str(exc)[:1000],
                        ) from exc

                return parsed, dict(response.payload), response.model or route.model

            parsed, payload, used_model = run_with_retry(
                attempt_section, max_attempts=self._max_attempts
            )
            parts[prompt_name] = parsed
            payloads[prompt_name] = payload
            last_model = used_model

        result = combine_sections(parts)
        validated = validate_parse_result(result, document_text=text)

        outcome = ResumeParseOutcome(
            result=result,
            validated=validated,
            raw_payload=payloads,
            # The set, not any one of its members. Every `ai_runs` row carries
            # the section prompt that produced it, so the detail is not lost —
            # what this names is which pipeline read the document.
            prompt_version=RESUME_SECTION_SET,
            # One hash over the four, so two imports of the same document are
            # still comparable and no single section's hash stands in for all.
            input_hash=hashlib.sha256("".join(hashes).encode()).hexdigest(),
            model=last_model or route.model,
            provider=self._provider.name,
            traces=collected,
            warnings=[*warnings, *validated.warnings],
        )
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
