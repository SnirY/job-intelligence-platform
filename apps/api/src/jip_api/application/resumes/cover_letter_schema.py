"""The typed shape a cover letter draft has to come back in.

Structured output rather than free prose, for the same reason every other AI
operation here is: an unparseable answer must be a schema failure the retry
classifier understands, not a paragraph someone has to read to discover it went
wrong.

The fields are deliberately few. A letter is one piece of text, and every extra
field is somewhere for the model to put something that then has to be checked.
`angle_warning` exists only because the alternative is worse — a model asked for
an angle it cannot support will otherwise write toward it anyway.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from jip_ai.structured import sanitize_json_schema


class CoverLetterResult(BaseModel):
    """One drafted letter."""

    body: str = Field(
        min_length=1,
        max_length=6000,
        description=(
            "The letter itself. Three to five short paragraphs, no greeting line and no sign-off."
        ),
    )

    angle_warning: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Set only when the requested angle cannot be supported by the supplied "
            "facts. Says what is missing, in one sentence."
        ),
    )
    """A model told to argue something the evidence does not carry will argue it
    anyway unless given somewhere else to put the objection. This is that
    somewhere, and it reaches the user rather than being logged."""


def cover_letter_json_schema() -> dict[str, Any]:
    schema: dict[str, Any] = sanitize_json_schema(CoverLetterResult.model_json_schema())
    return schema
