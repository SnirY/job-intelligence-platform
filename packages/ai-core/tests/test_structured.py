"""Structured output handling.

Everything a model returns is untrusted text until it has been through here.
"""

from __future__ import annotations

from typing import Any

import pytest

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.structured import parse_structured_output, sanitize_json_schema, truncate_for_prompt


def test_parses_a_json_object() -> None:
    assert parse_structured_output('{"skills": []}') == {"skills": []}


def test_tolerates_a_markdown_fence() -> None:
    """Asked for JSON, models still fence it sometimes.

    Failing here would cost a retry for a response whose content was correct.
    """
    assert parse_structured_output('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_rejects_an_empty_response(text: str) -> None:
    with pytest.raises(AIError) as caught:
        parse_structured_output(text)
    assert caught.value.code is AIFailureCode.INVALID_OUTPUT


def test_rejects_prose() -> None:
    with pytest.raises(AIError, match="not valid JSON"):
        parse_structured_output("Here is what I found in the resume:")


def test_rejects_a_top_level_array() -> None:
    """An array is not an object, and silently accepting one would mean the
    caller reads fields off something that has none."""
    with pytest.raises(AIError, match="not an object"):
        parse_structured_output("[1, 2, 3]")


def test_rejects_a_scalar() -> None:
    with pytest.raises(AIError, match="not an object"):
        parse_structured_output("42")


# --- schema sanitising --------------------------------------------------------


def test_strips_unsupported_constraints() -> None:
    """Constrained decoding rejects a schema carrying these keywords."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "name": {"type": "string", "minLength": 1, "maxLength": 120},
        },
    }

    cleaned = sanitize_json_schema(schema)

    assert "minimum" not in cleaned["properties"]["confidence"]
    assert "maxLength" not in cleaned["properties"]["name"]


def test_closes_objects_and_requires_every_property() -> None:
    cleaned = sanitize_json_schema(
        {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
    )

    assert cleaned["additionalProperties"] is False
    assert cleaned["required"] == ["a", "b"]


def test_recurses_through_nested_definitions() -> None:
    cleaned = sanitize_json_schema(
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {"n": {"type": "integer", "minimum": 1}},
                    },
                }
            },
        }
    )

    items = cleaned["properties"]["items"]
    assert "maxItems" not in items
    assert "minimum" not in items["items"]["properties"]["n"]
    assert items["items"]["additionalProperties"] is False


# --- truncation ---------------------------------------------------------------


def test_short_text_is_untouched() -> None:
    assert truncate_for_prompt("hello", max_chars=100) == ("hello", False)


def test_truncation_is_reported() -> None:
    """Reported rather than logged, so the user is told their document was cut."""
    text, truncated = truncate_for_prompt("abcdef", max_chars=3)

    assert text == "abc"
    assert truncated is True
