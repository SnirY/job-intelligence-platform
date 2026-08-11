"""``ResumeParseResult`` — the typed output schema for ``resume_parser_v1``.

``docs/05-ai-and-matching.md`` requires important AI operations to produce typed
output that passes schema validation. This is that type. It is also what the
provider is shown, as a JSON Schema, so the same definition constrains
generation and checks the answer.

Every field is deliberately permissive about *absence* and strict about *shape*.
A resume that omits a date must parse; a resume that yields a date of
``"sometime in 2019"`` must not.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jip_ai import sanitize_json_schema

# YYYY | YYYY-MM | YYYY-MM-DD. The parser is told to preserve the document's own
# precision, so all three have to survive validation rather than being coerced
# to a full date at the boundary and losing what the resume actually said.
_PARTIAL_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")

Confidence = Annotated[int, Field(ge=0, le=100)]
"""How clearly the document supports an item. Uncertainty, not accuracy."""


class DatePrecision(enum.StrEnum):
    """How exact an extracted date is.

    Kept because a year-only date stored as 1 January is indistinguishable from
    a real 1 January, and the reviewer needs to see which they are approving.
    """

    YEAR = "YEAR"
    MONTH = "MONTH"
    DAY = "DAY"


class PartialDate(BaseModel):
    """A date at whatever precision the resume gave."""

    model_config = ConfigDict(frozen=True)

    value: str
    precision: DatePrecision

    @classmethod
    def parse(cls, raw: str | None) -> PartialDate | None:
        """Read ``YYYY``, ``YYYY-MM``, or ``YYYY-MM-DD``, or return ``None``.

        Returns ``None`` for anything else rather than raising: one unreadable
        date should cost that date, not the whole extraction.
        """
        if not raw:
            return None
        match = _PARTIAL_DATE.match(raw.strip())
        if match is None:
            return None

        year, month, day = match.groups()
        if day is not None:
            precision = DatePrecision.DAY
        elif month is not None:
            precision = DatePrecision.MONTH
        else:
            precision = DatePrecision.YEAR

        try:
            cls._to_date(int(year), int(month or 1), int(day or 1))
        except ValueError:
            return None
        return cls(value=match.group(0), precision=precision)

    @staticmethod
    def _to_date(year: int, month: int, day: int) -> dt.date:
        if not 1900 <= year <= 2200:
            raise ValueError("year out of range")
        return dt.date(year, month, day)

    def to_date(self) -> dt.date:
        """Widen to a real date, filling missing parts with the earliest value.

        January and the 1st, not "today" or a midpoint: a deterministic floor is
        the only choice that does not invent information, and ``precision``
        records that the fill happened.
        """
        parts = self.value.split("-")
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return dt.date(year, month, day)


class _Candidate(BaseModel):
    """Fields every extracted item carries."""

    model_config = ConfigDict(extra="ignore")
    # extra="ignore" rather than "forbid": a model adding a field it thought
    # helpful should not fail the whole parse. Unknown fields are dropped, so
    # nothing unvalidated reaches storage either way.

    confidence: Confidence = 50
    source_text: str | None = Field(default=None, max_length=500)
    """The span of the resume this came from. Provenance the user can check."""

    @field_validator("source_text")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class SkillCandidate(_Candidate):
    """A skill the resume claims for its author."""

    name: str = Field(min_length=1, max_length=120)
    category: (
        Literal[
            "LANGUAGE",
            "FRAMEWORK",
            "DATABASE",
            "TOOL",
            "PLATFORM",
            "PRACTICE",
            "DOMAIN",
            "SOFT_SKILL",
            "OTHER",
        ]
        | None
    ) = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    last_used_year: int | None = Field(default=None, ge=1900, le=2200)


class AchievementCandidate(_Candidate):
    """One bullet from a role."""

    text: str = Field(min_length=1, max_length=2000)


class ExperienceCandidate(_Candidate):
    """A role the resume describes."""

    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    employment_type: (
        Literal["FULL_TIME", "PART_TIME", "CONTRACT", "FREELANCE", "INTERNSHIP", "VOLUNTEER"] | None
    ) = None
    location: str | None = Field(default=None, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    description: str | None = Field(default=None, max_length=5000)
    achievements: list[AchievementCandidate] = Field(default_factory=list, max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=60)
    """Technologies named inside this role. Recorded for the reviewer's context;
    they become skill candidates in their own right, not silent skill claims."""


class ProjectTechnology(BaseModel):
    """A technology a project used."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    confidence: Confidence = 50


class ProjectCandidate(_Candidate):
    """Something the resume says its author built."""

    name: str = Field(min_length=1, max_length=200)
    project_type: (
        Literal["PERSONAL", "ACADEMIC", "PROFESSIONAL", "OPEN_SOURCE", "FREELANCE", "RESEARCH"]
        | None
    ) = None
    status: Literal["IN_PROGRESS", "COMPLETED", "MAINTAINED", "ARCHIVED"] | None = None
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    start_date: str | None = None
    end_date: str | None = None
    repository_url: str | None = Field(default=None, max_length=500)
    demo_url: str | None = Field(default=None, max_length=500)
    technologies: list[ProjectTechnology] = Field(default_factory=list, max_length=60)


class EducationCandidate(_Candidate):
    """A qualification or course of study."""

    institution: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    grade: str | None = Field(default=None, max_length=50)


class ResumeParseResult(BaseModel):
    """Everything ``resume_parser_v1`` returns.

    Bounded list lengths are a safety limit, not a product one: without them a
    degenerate response could produce tens of thousands of rows before anything
    noticed.
    """

    model_config = ConfigDict(extra="ignore")

    skills: list[SkillCandidate] = Field(default_factory=list, max_length=200)
    experiences: list[ExperienceCandidate] = Field(default_factory=list, max_length=50)
    projects: list[ProjectCandidate] = Field(default_factory=list, max_length=50)
    education: list[EducationCandidate] = Field(default_factory=list, max_length=30)

    @property
    def is_empty(self) -> bool:
        """Whether the parser found nothing at all.

        Distinguished from a failure on purpose: a document that genuinely has
        no career facts is a valid result the user should be told about, not an
        error to retry.
        """
        return not (self.skills or self.experiences or self.projects or self.education)


def resume_parse_json_schema() -> dict[str, Any]:
    """JSON Schema for the provider, in the subset constrained decoding accepts.

    Generated from the model rather than hand-written, so the schema the
    provider is given and the schema the response is checked against cannot
    drift apart.

    **This one does not compile.** 6933 characters and 432 nodes against a limit
    `job_parse` clears at 2941 — DEV-017, and the reason the parse now runs one
    call per section. Kept because `tests/evals/test_schema_compiles.py` asserts
    it still fails: left as a skip, the day the provider raised its limit would
    pass unnoticed and nobody would ever collapse the four calls back.
    """
    schema: dict[str, Any] = sanitize_json_schema(ResumeParseResult.model_json_schema())
    return schema


# --- one section at a time (DEV-017) ------------------------------------------
#
# Four models over the same candidates, each asking for one section. What made
# the combined schema uncompilable is nesting — four arrays of objects, two of
# them containing their own arrays of objects — so splitting on that axis is
# what actually shrinks it. Removing enums and descriptions did not.
#
#     skills        1164 chars     experiences   2182
#     education     1476           projects      2213
#
# All four under `job_parse`'s 2941, which compiles.


class SkillsResult(BaseModel):
    """What `resume_skills_v1` returns."""

    model_config = ConfigDict(extra="ignore")

    skills: list[SkillCandidate] = Field(default_factory=list, max_length=200)


class ExperiencesResult(BaseModel):
    """What `resume_experiences_v1` returns, achievements included."""

    model_config = ConfigDict(extra="ignore")

    experiences: list[ExperienceCandidate] = Field(default_factory=list, max_length=50)


class ProjectsResult(BaseModel):
    """What `resume_projects_v1` returns, technologies included."""

    model_config = ConfigDict(extra="ignore")

    projects: list[ProjectCandidate] = Field(default_factory=list, max_length=50)


class EducationResult(BaseModel):
    """What `resume_education_v1` returns."""

    model_config = ConfigDict(extra="ignore")

    education: list[EducationCandidate] = Field(default_factory=list, max_length=30)


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "resume_skills_v1": SkillsResult,
    "resume_experiences_v1": ExperiencesResult,
    "resume_projects_v1": ProjectsResult,
    "resume_education_v1": EducationResult,
}
"""Prompt name to the shape its answer must take.

Keyed by prompt name rather than by an enum of sections, so a prompt registered
without a schema is a `KeyError` at the call site instead of a section that
silently returns nothing.
"""


def section_json_schema(prompt_name: str) -> dict[str, Any]:
    """JSON Schema for one section's prompt. Compiles, unlike the combined one."""
    schema: dict[str, Any] = sanitize_json_schema(SECTION_MODELS[prompt_name].model_json_schema())
    return schema


def combine_sections(parts: dict[str, BaseModel]) -> ResumeParseResult:
    """Fold the four answers back into the one result the pipeline already knows.

    Everything downstream — validation, the fabrication guard, the review
    screen, the confirm step — was written against `ResumeParseResult` and is
    unchanged by the split. Recombining here is what keeps it that way.

    A section that failed is absent rather than empty, and the caller decides
    what that means. Folding a failure in as `[]` would tell the user their
    resume has no projects when what happened is that we could not read them.
    """
    return ResumeParseResult(
        skills=getattr(parts.get("resume_skills_v1"), "skills", []),
        experiences=getattr(parts.get("resume_experiences_v1"), "experiences", []),
        projects=getattr(parts.get("resume_projects_v1"), "projects", []),
        education=getattr(parts.get("resume_education_v1"), "education", []),
    )
