"""Business validation of parsed job output.

``docs/05-ai-and-matching.md`` puts business validation after schema validation
and before persistence. Schema validation answers "is this the right shape";
this answers "is this something we are willing to present as what the posting
said".

Three checks carry the weight, and each exists because the failure it catches
is silent:

- **Quoted provenance must be real.** A requirement whose ``source_text`` does
  not appear in the description is reporting a passage that was not there. The
  requirement is dropped, not flagged — unlike a resume candidate, nobody
  reviews these one by one, so a fabricated requirement would go straight into
  a matcher.
- **A preference must not arrive as a demand.** ``docs/05-ai-and-matching.md``
  is explicit that "nice to have" must not become "required". The check reads
  the requirement's own quoted text: if the posting hedged, the importance is
  demoted regardless of what the model returned.
- **A judgement needs grounds.** A seniority other than UNKNOWN with no
  reasoning is an assertion. It is demoted to UNKNOWN rather than shown.

Nothing here rewrites the posting. Demotion changes our *classification* of a
requirement; ``source_text`` is untouched, so the user can always see what was
actually written.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from jip_api.application.jobs.analysis_schema import (
    JobAnalysisResult,
    JobParseResult,
    RequirementCandidate,
    ResponsibilityCandidate,
)
from jip_api.domain.jobs.analysis import (
    AnalyzedSeniority,
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
    RoleFamily,
)

logger = logging.getLogger(__name__)

MINIMUM_CONFIDENCE = 30
"""Below this an item is dropped. The prompt asks for the same floor; enforcing
it here means a model that ignores the instruction cannot fill the screen with
guesses."""

UNVERIFIED_CONFIDENCE_CAP = 40
"""Ceiling applied to an item whose importance had to be corrected."""

_WHITESPACE = re.compile(r"\s+")

HEDGE_PHRASES = (
    "nice to have",
    "nice-to-have",
    "a plus",
    "a big plus",
    "plus if",
    "bonus",
    "bonus points",
    "preferred",
    "preferable",
    "preferably",
    "desirable",
    "desired",
    "advantageous",
    "an advantage",
    "would be great",
    "would be nice",
    "ideally",
    "not required",
    "not mandatory",
    "optional",
    "familiarity with",
    "exposure to",
    "willingness to learn",
)
"""Phrases that mark a preference rather than a demand.

Chosen to be one-directional: every entry, when present, can only *lower* an
item's importance. There is no list of phrases that raise it, deliberately —
promoting on a keyword is exactly the error this guard exists to prevent, and a
one-way rule cannot be misapplied in the damaging direction.

"familiarity with" and "exposure to" are here because they describe acquaintance
rather than capability, and a matcher treating them as REQUIRED would report a
gap against someone perfectly qualified.
"""

_HEDGE_PATTERN = re.compile(
    "|".join(re.escape(phrase) for phrase in HEDGE_PHRASES),
    re.IGNORECASE,
)


@dataclass(slots=True)
class RequirementDraft:
    """One validated requirement, ready to persist."""

    requirement_type: RequirementType
    importance: RequirementImportance
    explicitness: RequirementExplicitness
    source_text: str
    normalized_text: str
    confidence: int
    source_order: int
    skill_name: str | None = None
    years_min: int | None = None


@dataclass(slots=True)
class ResponsibilityDraft:
    """One validated responsibility, ready to persist."""

    text: str
    source_text: str | None
    confidence: int
    source_order: int


@dataclass(slots=True)
class ValidatedParse:
    """What survived validation, and what the user should be told."""

    requirements: list[RequirementDraft] = field(default_factory=list)
    responsibilities: list[ResponsibilityDraft] = field(default_factory=list)
    summary: str | None = None
    years_experience_min: int | None = None
    years_experience_max: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.requirements or self.responsibilities)


@dataclass(slots=True)
class ValidatedAnalysis:
    """The interpretation, after its own rules."""

    role_family: RoleFamily
    secondary_role_family: RoleFamily | None
    role_family_confidence: int
    role_family_reasoning: str | None
    seniority: AnalyzedSeniority
    seniority_confidence: int
    seniority_reasoning: str | None
    domain: str | None
    summary: str | None
    warnings: list[str] = field(default_factory=list)


# --- parse validation ---------------------------------------------------------


def validate_parse_result(result: JobParseResult, *, job_text: str) -> ValidatedParse:
    """Apply business rules to a parse and return what may be persisted."""
    haystack = _searchable(job_text)
    validated = ValidatedParse(
        summary=_clean(result.summary),
        years_experience_min=result.years_experience_min,
        years_experience_max=result.years_experience_max,
    )

    if (
        validated.years_experience_min is not None
        and validated.years_experience_max is not None
        and validated.years_experience_min > validated.years_experience_max
    ):
        # A reversed range is a reading error, not a fact about the posting.
        # Dropping both is better than presenting a range that says nothing.
        validated.warnings.append(
            "The years of experience came back as an impossible range, so they were left out."
        )
        validated.years_experience_min = None
        validated.years_experience_max = None

    _add_requirements(result.requirements, validated, haystack=haystack)
    _add_responsibilities(result.responsibilities, validated, haystack=haystack)

    return validated


def _add_requirements(
    candidates: list[RequirementCandidate],
    out: ValidatedParse,
    *,
    haystack: str,
) -> None:
    unverified = 0
    demoted = 0
    seen: set[tuple[str, str]] = set()

    for order, candidate in enumerate(candidates):
        if candidate.confidence < MINIMUM_CONFIDENCE:
            continue

        if not _appears_in(candidate.source_text, haystack):
            unverified += 1
            continue

        requirement_type = RequirementType(candidate.requirement_type)
        importance = RequirementImportance(candidate.importance)
        confidence = candidate.confidence

        corrected = _demote_if_hedged(importance, candidate.source_text)
        if corrected is not importance:
            demoted += 1
            importance = corrected
            confidence = min(confidence, UNVERIFIED_CONFIDENCE_CAP)

        # The same requirement extracted twice — common when a posting repeats
        # itself between a summary and a bullet list. Keyed on meaning rather
        # than on source text, since two spans can say the same thing.
        key = (requirement_type.value, _searchable(candidate.normalized_text))
        if key in seen:
            continue
        seen.add(key)

        out.requirements.append(
            RequirementDraft(
                requirement_type=requirement_type,
                importance=importance,
                explicitness=RequirementExplicitness(candidate.explicitness),
                source_text=candidate.source_text.strip(),
                normalized_text=candidate.normalized_text.strip(),
                confidence=confidence,
                source_order=order,
                skill_name=_skill_name_for(requirement_type, candidate.skill_name),
                years_min=candidate.years_min,
            )
        )

    if unverified:
        out.warnings.append(
            f"{unverified} requirement{'s' if unverified != 1 else ''} quoted text that is not "
            "in this posting, so they were left out."
        )
    if demoted:
        out.warnings.append(
            f"{demoted} requirement{'s were' if demoted != 1 else ' was'} listed as required but "
            "worded as a preference in the posting, so they were recorded as preferred."
        )


def _add_responsibilities(
    candidates: list[ResponsibilityCandidate],
    out: ValidatedParse,
    *,
    haystack: str,
) -> None:
    seen: set[str] = set()

    for order, candidate in enumerate(candidates):
        if candidate.confidence < MINIMUM_CONFIDENCE:
            continue
        if not _appears_in(candidate.source_text, haystack):
            continue

        key = _searchable(candidate.text)
        if key in seen:
            continue
        seen.add(key)

        out.responsibilities.append(
            ResponsibilityDraft(
                text=candidate.text.strip(),
                source_text=candidate.source_text.strip(),
                confidence=candidate.confidence,
                source_order=order,
            )
        )


def _demote_if_hedged(importance: RequirementImportance, source_text: str) -> RequirementImportance:
    """Lower a mandatory importance when the posting hedged.

    One direction only. A requirement the model called PREFERRED stays
    PREFERRED even if the source text reads like a demand — the model saw the
    whole posting and this function sees one sentence, so it is trusted to be
    stricter than us but never more lenient.
    """
    if not importance.is_mandatory:
        return importance
    if _HEDGE_PATTERN.search(source_text) is None:
        return importance
    return RequirementImportance.PREFERRED


def _skill_name_for(requirement_type: RequirementType, skill_name: str | None) -> str | None:
    """Keep a skill name only where it means something.

    A ``skill_name`` on a LOCATION requirement is a model slip, and carrying it
    forward would put "Berlin" into skill resolution.
    """
    if requirement_type is not RequirementType.TECHNICAL_SKILL:
        return None
    cleaned = _clean(skill_name)
    return cleaned[:120] if cleaned else None


# --- analysis validation ------------------------------------------------------


MINIMUM_REASONING_CHARS = 20
"""Below this, "reasoning" is a label rather than an argument.

Twenty characters is enough for "Title says Senior" and not enough for "n/a",
"see above", or an empty-ish string that satisfies a null check while saying
nothing.
"""


def validate_analysis_result(
    result: JobAnalysisResult, *, has_requirements: bool
) -> ValidatedAnalysis:
    """Apply business rules to an interpretation.

    ``has_requirements`` gates seniority: a posting nothing could be extracted
    from cannot support a level, whatever the title suggested. Without this a
    two-line posting reading "Senior Engineer, apply within" would come back
    SENIOR with high confidence, which is the failure mode
    ``docs/05-ai-and-matching.md`` warns about when it says not to read the
    title and stop.
    """
    warnings: list[str] = []

    seniority = AnalyzedSeniority(result.seniority)
    seniority_reasoning = _clean(result.seniority_reasoning)
    seniority_confidence = result.seniority_confidence

    if seniority is not AnalyzedSeniority.UNKNOWN and not _is_real_reasoning(seniority_reasoning):
        warnings.append(
            "The seniority came back without any reasoning behind it, so it is shown as unknown."
        )
        seniority = AnalyzedSeniority.UNKNOWN
        seniority_confidence = 0
        seniority_reasoning = None

    if seniority is not AnalyzedSeniority.UNKNOWN and not has_requirements:
        warnings.append(
            "Nothing could be read out of this posting, so its seniority is shown as unknown "
            "rather than guessed from the title."
        )
        seniority = AnalyzedSeniority.UNKNOWN
        seniority_confidence = 0
        seniority_reasoning = None

    role_family = RoleFamily(result.role_family)
    secondary = RoleFamily(result.secondary_role_family) if result.secondary_role_family else None
    if secondary is role_family:
        # Saying "backend, and also backend" is noise, not a second family.
        secondary = None

    return ValidatedAnalysis(
        role_family=role_family,
        secondary_role_family=secondary,
        role_family_confidence=result.role_family_confidence,
        role_family_reasoning=_clean(result.role_family_reasoning),
        seniority=seniority,
        seniority_confidence=seniority_confidence,
        seniority_reasoning=seniority_reasoning,
        domain=_clean(result.domain),
        summary=_clean(result.summary),
        warnings=warnings,
    )


def _is_real_reasoning(text: str | None) -> bool:
    return bool(text) and len(text or "") >= MINIMUM_REASONING_CHARS


# --- helpers ------------------------------------------------------------------


def _searchable(text: str) -> str:
    """Collapse case and whitespace for comparison.

    Whitespace has to go: extraction from HTML rewraps lines, so a quote that
    is genuinely present often differs from the description by a newline.
    """
    return _WHITESPACE.sub(" ", text).strip().lower()


def _appears_in(quoted: str, haystack: str) -> bool:
    """Whether a quoted span really occurs in the posting."""
    needle = _searchable(quoted)
    return bool(needle) and needle in haystack


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
