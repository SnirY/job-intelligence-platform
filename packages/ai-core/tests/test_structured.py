"""Structured output handling.

Everything a model returns is untrusted text until it has been through here.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from jip_ai.failures import AIError, AIFailureCode
from jip_ai.structured import (
    parse_structured_output,
    sanitize_json_schema,
    schema_failure_summary,
    truncate_for_prompt,
)


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


def test_repairs_an_escape_the_model_double_escaped() -> None:
    r"""Seen in production: `±0.5cm` arrived as the six characters `\u00b1`.

    The model wrote the backslash escaped, so `json.loads` produced the spelling
    instead of the character.
    """
    payload = parse_structured_output(r'{"text": "achieving \\u00b10.5cm accuracy"}')

    assert payload == {"text": "achieving ±0.5cm accuracy"}


def test_repairs_escapes_at_every_depth() -> None:
    """Nested, because the rewrite that hit this returns a list of objects."""
    payload = parse_structured_output(
        r'{"suggestions": [{"text": "\\u00b10.5cm"}], "note": "\\u2014"}'
    )

    assert payload == {"suggestions": [{"text": "±0.5cm"}], "note": "—"}


def test_a_properly_escaped_character_is_untouched() -> None:
    """The ordinary path. `json.loads` already decoded it, and there is no
    surviving escape for the repair to find."""
    assert parse_structured_output(r'{"text": "\u00b10.5cm"}') == {"text": "±0.5cm"}


BACKSLASH = chr(92)
"""Built rather than written, so no layer between here and the file can eat it.

Every attempt to write these cases as literals lost a backslash somewhere.
"""


def _response(text: str) -> str:
    """A JSON document whose one string value is exactly ``text``."""
    return '{"t": "' + text.replace(BACKSLASH, BACKSLASH * 2) + '"}'


def test_a_double_escaped_surrogate_pair_becomes_one_character() -> None:
    """An emoji arrives as two escapes that mean one character.

    Decoding them separately yields two lone surrogates, and PostgreSQL refuses
    those — which would turn a cosmetic defect into a failed write.
    """
    emoji = BACKSLASH + "ud83d" + BACKSLASH + "ude00"
    payload = parse_structured_output(_response(emoji + " hi"))

    assert payload == {"t": "😀 hi"}
    payload["t"].encode("utf-8")


def test_a_surrogate_with_no_partner_is_left_as_it_arrived() -> None:
    """Half of a character is not a character. The spelling is ugly and
    storable; the decoded half is neither."""
    lone = BACKSLASH + "ud83d"
    payload = parse_structured_output(_response(lone + " alone"))

    assert payload == {"t": lone + " alone"}
    payload["t"].encode("utf-8")


def test_a_lone_backslash_is_left_alone() -> None:
    r"""Only `\uXXXX` is repaired. A Windows path in a resume keeps its
    backslashes, and `\n` keeps its honest meaning in text about code."""
    payload = parse_structured_output(r'{"text": "C:\\Users\\dev and a \\n literal"}')

    assert payload == {"text": r"C:\Users\dev and a \n literal"}


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


# --- naming the field that failed, without quoting it (DEV-045) ----------------


class _Change(BaseModel):
    item_id: str
    proposed_text: str
    rationale: str


class _Rewrite(BaseModel):
    changes: list[_Change]


def _rejects(payload: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _Rewrite.model_validate(payload)
    return caught.value


def test_the_summary_names_the_field_and_the_kind_of_error() -> None:
    """The whole point of DEV-045: `ai_runs` recorded "Output failed schema
    check" and nothing else, so a failure that happened half the time could not
    be reproduced from the log."""
    error = _rejects({"changes": [{"item_id": "a"}]})

    summary = schema_failure_summary(error)

    assert "changes.0.proposed_text" in summary
    assert "missing" in summary


def test_the_summary_never_quotes_what_the_model_wrote() -> None:
    """`errors()` carries the offending value in `input`, and on a resume
    rewrite that value is the user's own words. DEV-033 is the same rule from
    the other side."""
    error = _rejects(
        {
            "changes": [
                {"item_id": "a", "proposed_text": "Led the NICU trial at Sheba", "rationale": 5}
            ]
        }
    )

    summary = schema_failure_summary(error)

    assert "NICU" not in summary
    assert "Sheba" not in summary
    assert "changes.0.rationale" in summary


def test_a_long_list_of_problems_says_how_many_it_left_out() -> None:
    """A truncated summary that does not admit it is truncated reads as a
    complete one."""
    error = _rejects({"changes": [{} for _ in range(9)]})

    summary = schema_failure_summary(error, limit=3)

    assert summary.count(";") == 3
    assert "and 24 more" in summary


def test_something_that_is_not_a_validation_error_says_so() -> None:
    """Called from an `except` clause, so it must never raise on the way to
    reporting a failure."""
    assert schema_failure_summary(RuntimeError("boom")) == "RuntimeError with no field detail"
