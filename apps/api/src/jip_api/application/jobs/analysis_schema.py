"""Typed output schemas for ``job_parser_v1`` and ``job_analysis_v1``.

``docs/05-ai-and-matching.md`` names ``JobParseResult`` and
``JobAnalysisResult`` as structured outputs that must pass schema validation.
These are those types, and they are also what the provider is shown as JSON
Schema — one definition constrains generation and checks the answer, so the two
cannot drift.

The split between them is the phase's central discipline:

- :class:`JobParseResult` is what the posting *says*. Every item carries the
  verbatim span it came from, and the validation layer checks that span against
  the description.
- :class:`JobAnalysisResult` is what the posting *means*. Every judgement
  carries reasoning and a confidence, and none of it can add or edit a
  requirement.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jip_ai import sanitize_json_schema

Confidence = int
"""0-100, how clearly the posting supports an item. Uncertainty, not accuracy."""

RequirementTypeLiteral = Literal[
    "TECHNICAL_SKILL",
    "EXPERIENCE",
    "EDUCATION",
    "CERTIFICATION",
    "LANGUAGE",
    "DOMAIN_KNOWLEDGE",
    "SOFT_SKILL",
    "LOCATION",
    "WORK_AUTHORIZATION",
    "OTHER",
]

ImportanceLiteral = Literal["CORE", "REQUIRED", "PREFERRED", "OPTIONAL", "UNKNOWN"]

RoleFamilyLiteral = Literal[
    "BACKEND",
    "FRONTEND",
    "FULL_STACK",
    "SOFTWARE",
    "AI_ML",
    "DATA_ENGINEERING",
    "COMPUTER_VISION",
    "DEVOPS",
    "CYBERSECURITY",
    "OTHER",
]

SeniorityLiteral = Literal[
    "INTERN",
    "ENTRY_LEVEL",
    "JUNIOR",
    "MID",
    "SENIOR",
    "STAFF_PLUS",
    "UNKNOWN",
]

# The literals repeat the domain enums rather than being generated from them.
# Deliberate: these are the wire contract with a model, and a value must not
# silently appear in a prompt's schema because someone added an enum member
# without writing the instructions that explain when to use it.


class _Item(BaseModel):
    """Fields every extracted item carries."""

    model_config = ConfigDict(extra="ignore")
    # extra="ignore" rather than "forbid": a model adding a field it thought
    # helpful should not fail the whole parse. Unknown fields are dropped, so
    # nothing unvalidated reaches storage either way.

    confidence: Confidence = Field(default=50, ge=0, le=100)
    source_text: str = Field(min_length=1, max_length=1000)
    """The posting's own words. Not optional, unlike the resume parser's
    equivalent: a requirement without its source text cannot be checked against
    the description, and an unverifiable requirement is the thing this phase
    exists to avoid producing."""

    @field_validator("source_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class RequirementCandidate(_Item):
    """One thing the posting asks for."""

    normalized_text: str = Field(min_length=1, max_length=300)
    """The requirement in a short canonical phrase — "3+ years backend
    engineering". What a human scans; ``source_text`` is what they check."""

    requirement_type: RequirementTypeLiteral
    importance: ImportanceLiteral = "UNKNOWN"
    explicitness: Literal["EXPLICIT", "IMPLIED"] = "EXPLICIT"

    skill_name: str | None = Field(default=None, max_length=120)
    """The technology named, for a TECHNICAL_SKILL requirement. Resolved
    against the canonical catalogue after validation, never here."""

    years_min: int | None = Field(default=None, ge=0, le=80)


class ResponsibilityCandidate(_Item):
    """One thing the role does."""

    text: str = Field(min_length=1, max_length=1000)


class JobParseResult(BaseModel):
    """Everything ``job_parser_v1`` returns.

    Bounded list lengths are a safety limit rather than a product one: without
    them a degenerate response could produce thousands of rows before anything
    noticed.
    """

    model_config = ConfigDict(extra="ignore")

    summary: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)

    requirements: list[RequirementCandidate] = Field(default_factory=list, max_length=120)
    responsibilities: list[ResponsibilityCandidate] = Field(default_factory=list, max_length=60)

    years_experience_min: int | None = Field(default=None, ge=0, le=80)
    years_experience_max: int | None = Field(default=None, ge=0, le=80)

    @property
    def is_empty(self) -> bool:
        """Whether the parse found nothing structural.

        Distinguished from a failure: a three-line posting that genuinely lists
        nothing is a valid result the user should see, not an error to retry.
        """
        return not (self.requirements or self.responsibilities)


class JobAnalysisResult(BaseModel):
    """Everything ``job_analysis_v1`` returns.

    Interpretation only. It reads the parse and the posting and answers the two
    questions Phase 6 needs — what kind of role, and at what level — with the
    grounds for each. It returns no requirements, which is what makes "analysis
    cannot edit facts" a property of the schema rather than a rule someone has
    to follow.
    """

    model_config = ConfigDict(extra="ignore")

    role_family: RoleFamilyLiteral = "OTHER"
    secondary_role_family: RoleFamilyLiteral | None = None
    role_family_confidence: Confidence = Field(default=50, ge=0, le=100)
    role_family_reasoning: str | None = Field(default=None, max_length=1000)

    seniority: SeniorityLiteral = "UNKNOWN"
    seniority_confidence: Confidence = Field(default=50, ge=0, le=100)
    seniority_reasoning: str | None = Field(default=None, max_length=1000)
    """Which signals produced the level.

    ``docs/05-ai-and-matching.md`` lists six — title, years, responsibility
    scope, architecture ownership, leadership, mentoring — and the prompt asks
    for the ones that actually applied. Validation refuses a non-UNKNOWN level
    with no reasoning at all.
    """

    domain: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, max_length=2000)


def job_parse_json_schema() -> dict[str, Any]:
    """JSON Schema for the provider, in the subset constrained decoding accepts."""
    schema: dict[str, Any] = sanitize_json_schema(JobParseResult.model_json_schema())
    return schema


def job_analysis_json_schema() -> dict[str, Any]:
    """JSON Schema for the provider, in the subset constrained decoding accepts."""
    schema: dict[str, Any] = sanitize_json_schema(JobAnalysisResult.model_json_schema())
    return schema
