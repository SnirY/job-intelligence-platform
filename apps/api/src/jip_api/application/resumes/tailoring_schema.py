"""Typed output schemas for ``resume_strategy_v1`` and ``resume_rewrite_v1``.

**Both are deliberately flat.** DEV-017 recorded that Anthropic compiles a
response schema into a grammar and rejects one whose compiled form is too
large, and that the cost is nesting rather than length: ``resume_parse`` fails
at 6933 characters with four arrays of objects, two of which nest their own
arrays, while ``job_parse`` compiles at 2941 with one level.

So :class:`ResumeStrategyResult` uses arrays of **strings** — no objects at all
— and :class:`ResumeRewriteResult` uses a single array of objects whose fields
are all scalars. Neither nests. Both were checked against the live API before
being relied on, because the offline evaluations replay recorded responses
through a fake provider and can never catch a schema the API refuses.

Nothing in either schema can carry a score, a status, or a decision. The model
proposes words; validation in :mod:`truth` decides whether they are supported.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jip_ai import sanitize_json_schema


class ResumeStrategyResult(BaseModel):
    """What ``resume_strategy_v1`` returns.

    The six questions ``docs/06-resume-engine.md`` requires a strategy to
    answer, as six flat lists of short strings.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(default="", max_length=1500)
    emphasize: list[str] = Field(default_factory=list, max_length=8)
    reduce: list[str] = Field(default_factory=list, max_length=8)
    reorder_note: str = Field(default="", max_length=600)
    priority_projects: list[str] = Field(default_factory=list, max_length=5)

    missing_evidence: list[str] = Field(default_factory=list, max_length=8)
    """Evidence the profile has that this resume does not show — a *resume*
    gap, fixable by selection."""

    career_gaps: list[str] = Field(default_factory=list, max_length=8)
    """Evidence the user genuinely lacks — a *career* gap, which no amount of
    rewriting fixes. ``docs/06`` insists the two stay distinct."""


class RewriteCandidate(BaseModel):
    """One proposed change to one item. All fields scalar; nothing nests."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(max_length=64)
    suggested_text: str = Field(max_length=1000)
    """The replacement line. Empty is legitimate, and only for a removal.

    DEV-045. This carried `min_length=1`, and `sanitize_json_schema` strips
    `minLength` before the schema reaches the provider — so the constraint was
    invisible to the model and enforced only on the way back. The prompt offers
    `REMOVE` ("not relevant to this posting and the space is better spent"), a
    removal has no replacement text, the model returned `""`, and our own
    validation threw away all twenty-five suggestions because one of them was a
    cut. That is the ~50% failure rate.

    The pairing rule — empty only for REMOVE — is enforced in the service, where
    the item is in hand and a single bad candidate can be dropped instead of
    failing the batch.
    """
    rationale: str = Field(default="", max_length=500)
    kind: Literal["REWRITE", "SHORTEN", "EMPHASIZE", "REORDER", "REMOVE"] = "REWRITE"


class ResumeRewriteResult(BaseModel):
    """What ``resume_rewrite_v1`` returns.

    One array of flat objects — the shape that compiles. The model never sees
    or sets a risk level or a truth status: those are decided afterwards by
    :func:`jip_api.application.resumes.truth.validate_rewrite`, because a model
    grading its own output is not a check.
    """

    model_config = ConfigDict(extra="ignore")

    suggestions: list[RewriteCandidate] = Field(default_factory=list, max_length=25)


def resume_strategy_json_schema() -> dict[str, Any]:
    schema: dict[str, Any] = sanitize_json_schema(ResumeStrategyResult.model_json_schema())
    return schema


def resume_rewrite_json_schema() -> dict[str, Any]:
    schema: dict[str, Any] = sanitize_json_schema(ResumeRewriteResult.model_json_schema())
    return schema
