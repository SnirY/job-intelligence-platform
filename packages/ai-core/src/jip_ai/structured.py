"""Turning a model's text into a checked payload.

``docs/05-ai-and-matching.md`` puts schema validation between the model call and
persistence. This module is the first half of that step: get a JSON object out
of the response at all. Business validation is the caller's, and lives with the
rules it enforces.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jip_ai.failures import AIError, AIFailureCode

# Models asked for JSON sometimes wrap it in a fenced block anyway. Stripping
# the fence is not indulgence: the alternative is failing a response whose
# content was correct, and then paying for a retry of the same thing.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


def parse_structured_output(text: str) -> dict[str, Any]:
    """Parse ``text`` into a JSON object.

    Raises :class:`AIError` with ``INVALID_OUTPUT`` for anything else — empty
    responses, prose, arrays, scalars. Every one of those means the model did
    not answer the question, and treating it as an empty result would silently
    report "we found nothing in your resume".
    """
    if not text or not text.strip():
        raise AIError(AIFailureCode.INVALID_OUTPUT, "The model returned an empty response.")

    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced is not None:
        candidate = fenced.group("body")

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIError(
            AIFailureCode.INVALID_OUTPUT,
            "The model returned output that is not valid JSON.",
            details=f"{exc} | {_shape_of(candidate)}",
        ) from exc

    if not isinstance(parsed, dict):
        raise AIError(
            AIFailureCode.INVALID_OUTPUT,
            "The model returned JSON that is not an object.",
            details=f"top-level type was {type(parsed).__name__}",
        )

    return parsed


def schema_failure_summary(error: Any, *, limit: int = 5) -> str:
    """Which fields a payload got wrong, without saying what it put in them.

    DEV-045. `RESUME_REWRITE` was failing its own schema check about half the
    time, and every one of those runs recorded the same fixed string — "Output
    failed schema check". The Pydantic error naming the field went into
    ``AIError.details``, which is not persisted on the trace, so from
    ``ai_runs`` alone the failure was unreproducible: you could see that the
    shape was wrong and never which part of it.

    This is the same trade `_shape_of` makes one function below, and for the
    same reason. ``error.errors()`` carries ``loc`` and ``type`` — a field path
    and a category, both structural — alongside ``input``, which on a resume
    rewrite is the user's own words. Only the first two are used. A count of
    what was elided keeps a truncated summary from reading as a complete one.

    Typed against ``Any`` rather than ``ValidationError`` so this package keeps
    no pydantic import; the callers all have one already.
    """
    try:
        problems = list(error.errors())
    except Exception:  # not a ValidationError: say so rather than raising here
        return f"{type(error).__name__} with no field detail"

    if not problems:
        return "schema check failed with no field detail"

    described = [
        f"{'.'.join(str(part) for part in problem.get('loc', ())) or '<root>'}"
        f" ({problem.get('type', 'unknown')})"
        for problem in problems[:limit]
    ]
    remaining = len(problems) - len(described)
    if remaining > 0:
        described.append(f"and {remaining} more")

    return "; ".join(described)


def _shape_of(candidate: str) -> str:
    """What the response looked like, without saying what it said.

    This used to be ``first 200 chars: {candidate!r}``, and ``AIError.details``
    is logged by ``processing.jobs.mark_failed``. On a resume parse the model's
    output *is* the user's resume — name, employers, dates — so those two
    hundred characters put personal data into the application log, which
    ``docs/11-engineering-standards.md`` forbids twice over: no full resume
    text, no unnecessary personal details.

    Removing it outright was the wrong fix. DEV-015 is the case: a failure
    whose cause was "credit balance too low" and nothing recorded it. A
    malformed-JSON failure is diagnosed from *structure* — the decode error
    already carries the line, column and reason, and what it lacks is whether
    the response was truncated, empty-ish, or never an object at all. That is
    exactly what this reports, and none of it is content.
    """
    return f"{len(candidate)} chars, opens {candidate[:1]!r}, closes {candidate[-1:]!r}"


# Keywords a provider's constrained decoder does not implement. Sending them is
# not harmless — a schema carrying one is rejected outright — so they are
# stripped here and enforced by our own validation after the response arrives.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


def sanitize_json_schema(schema: Any) -> Any:
    """Reduce a JSON Schema to the subset constrained decoding accepts.

    Drops the numeric and length keywords listed above and pins
    ``additionalProperties: false`` on every object, which providers require.

    Nothing is lost: the schema generated from the Pydantic model keeps all of
    those constraints, and that model validates the response. This affects only
    what the model is *told*, never what we accept.
    """
    if isinstance(schema, list):
        return [sanitize_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned: dict[str, Any] = {
        key: sanitize_json_schema(value)
        for key, value in schema.items()
        if key not in _UNSUPPORTED_KEYWORDS
    }

    if cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False
        # Constrained decoding requires every declared property to be listed as
        # required. Optionality is expressed by allowing null in the type union,
        # which the Pydantic models already do.
        cleaned["required"] = sorted(cleaned["properties"])

    return cleaned


def truncate_for_prompt(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Bound the text sent to a model, reporting whether anything was dropped.

    Returned rather than logged so the caller can record the truncation as a
    warning the user sees. Silently sending half a resume and presenting the
    result as a full parse is exactly the kind of quiet incorrectness
    ``GOAL.md`` rules out.
    """
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
