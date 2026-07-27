"""Business validation of parsed resume output.

``docs/05-ai-and-matching.md`` puts business validation after schema validation
and before persistence. Schema validation answers "is this the right shape";
this answers "is this something we are willing to show the user as a fact from
their document".

Two checks carry the weight, and both compare the model's claims against the
document itself rather than trusting them:

- **Quoted provenance must be real.** An item whose ``source_text`` does not
  appear in the resume is reporting a passage that was not there.
- **Numbers must be in the document.** ``docs/06-resume-engine.md`` is
  categorical about never inventing metrics, and a digit sequence that appears
  in a candidate but nowhere in the resume is the machine-checkable form of
  exactly that.

Neither check deletes the item. It is flagged, its confidence is capped, and
the reviewer is told why — the user is the one who knows whether their resume
said "40%".
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from jip_api.application.resumes.schema import (
    AchievementCandidate,
    EducationCandidate,
    ExperienceCandidate,
    PartialDate,
    ProjectCandidate,
    ResumeParseResult,
    SkillCandidate,
)
from jip_api.domain.career.skills import normalize_skill_name
from jip_api.domain.documents.models import CandidateType

logger = logging.getLogger(__name__)

MINIMUM_CONFIDENCE = 30
"""Below this an item is dropped entirely.

The prompt already asks for the same floor. Enforcing it here as well means a
model that ignores the instruction cannot fill the review screen with guesses.
"""

UNVERIFIED_CONFIDENCE_CAP = 40
"""Ceiling applied to an item whose provenance or numbers did not check out."""

_DIGIT_RUN = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(slots=True)
class CandidateDraft:
    """One reviewable item, ready to persist.

    Children ride along with their parent because an achievement cannot be
    stored before the experience it belongs to has an id.
    """

    candidate_type: CandidateType
    payload: dict[str, Any]
    confidence: int | None = None
    source_text: str | None = None
    display_order: int = 0
    children: list[CandidateDraft] = field(default_factory=list)


@dataclass(slots=True)
class ValidatedExtraction:
    """What survived validation, and what the user should be told."""

    candidates: list[CandidateDraft] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.candidates


def validate_parse_result(result: ResumeParseResult, *, document_text: str) -> ValidatedExtraction:
    """Apply business rules and return the reviewable candidates."""
    haystack = _searchable(document_text)
    document_digits = set(_DIGIT_RUN.findall(document_text))
    validated = ValidatedExtraction()

    _add_skills(result.skills, validated, haystack=haystack, digits=document_digits)
    _add_experiences(result.experiences, validated, haystack=haystack, digits=document_digits)
    _add_projects(result.projects, validated, haystack=haystack, digits=document_digits)
    _add_education(result.education, validated, haystack=haystack, digits=document_digits)

    return validated


# --- per-type rules -----------------------------------------------------------


def _add_skills(
    skills: list[SkillCandidate],
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
) -> None:
    """Skills, de-duplicated against the canonical normalization.

    Two spellings of one skill must not both become candidates: accepting both
    would create one ``UserSkill`` and leave the second silently doing nothing,
    which reads to the user as an accepted item that never appeared.
    """
    seen: set[str] = set()
    order = 0

    for skill in skills:
        if skill.confidence < MINIMUM_CONFIDENCE:
            continue

        normalized = normalize_skill_name(skill.name)
        if not normalized:
            out.warnings.append(f"Ignored a skill with no usable name: {skill.name!r}.")
            continue
        if normalized in seen:
            continue
        seen.add(normalized)

        payload: dict[str, Any] = {
            "name": skill.name.strip(),
            "category": skill.category or "OTHER",
            "years_of_experience": skill.years_of_experience,
            "last_used_year": skill.last_used_year,
        }
        out.candidates.append(
            _draft(
                CandidateType.SKILL,
                payload,
                skill.confidence,
                skill.source_text,
                order,
                out,
                haystack=haystack,
                digits=digits,
            )
        )
        order += 1


def _add_experiences(
    experiences: list[ExperienceCandidate],
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
) -> None:
    order = 0
    for experience in experiences:
        if experience.confidence < MINIMUM_CONFIDENCE:
            continue

        start, end, is_current = _dates(
            experience.start_date,
            experience.end_date,
            experience.is_current,
            label=f"{experience.title} at {experience.company}",
            out=out,
        )

        payload: dict[str, Any] = {
            "company": experience.company.strip(),
            "title": experience.title.strip(),
            "employment_type": experience.employment_type,
            "location": experience.location,
            "is_current": is_current,
            "description": experience.description,
            **_date_fields(start, end),
        }

        draft = _draft(
            CandidateType.EXPERIENCE,
            payload,
            experience.confidence,
            experience.source_text,
            order,
            out,
            haystack=haystack,
            digits=digits,
        )

        for index, achievement in enumerate(experience.achievements):
            child = _achievement(achievement, index, out, haystack=haystack, digits=digits)
            if child is not None:
                draft.children.append(child)

        out.candidates.append(draft)
        order += 1


def _achievement(
    achievement: AchievementCandidate,
    index: int,
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
) -> CandidateDraft | None:
    if achievement.confidence < MINIMUM_CONFIDENCE:
        return None
    text = achievement.text.strip()
    if not text:
        return None
    return _draft(
        CandidateType.EXPERIENCE_ACHIEVEMENT,
        {"text": text},
        achievement.confidence,
        achievement.source_text,
        index,
        out,
        haystack=haystack,
        digits=digits,
        # The bullet's own text is checked for invented numbers, not just its
        # quoted provenance — this is where a fabricated metric would appear.
        number_source=text,
    )


def _add_projects(
    projects: list[ProjectCandidate],
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
) -> None:
    order = 0
    seen_names: set[str] = set()

    for project in projects:
        if project.confidence < MINIMUM_CONFIDENCE:
            continue

        key = project.name.strip().casefold()
        if key in seen_names:
            continue
        seen_names.add(key)

        start, end, _ = _dates(
            project.start_date, project.end_date, False, label=project.name, out=out
        )

        payload: dict[str, Any] = {
            "name": project.name.strip(),
            "project_type": project.project_type,
            "status": project.status,
            "summary": project.summary,
            "description": project.description,
            "repository_url": _safe_url(project.repository_url, project.name, out),
            "demo_url": _safe_url(project.demo_url, project.name, out),
            **_date_fields(start, end),
        }

        draft = _draft(
            CandidateType.PROJECT,
            payload,
            project.confidence,
            project.source_text,
            order,
            out,
            haystack=haystack,
            digits=digits,
        )

        seen_tech: set[str] = set()
        for index, technology in enumerate(project.technologies):
            normalized = normalize_skill_name(technology.name)
            if not normalized or normalized in seen_tech:
                continue
            if technology.confidence < MINIMUM_CONFIDENCE:
                continue
            seen_tech.add(normalized)
            draft.children.append(
                CandidateDraft(
                    candidate_type=CandidateType.PROJECT_SKILL,
                    payload={"name": technology.name.strip()},
                    confidence=technology.confidence,
                    display_order=index,
                )
            )

        out.candidates.append(draft)
        order += 1


def _add_education(
    education: list[EducationCandidate],
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
) -> None:
    order = 0
    for entry in education:
        if entry.confidence < MINIMUM_CONFIDENCE:
            continue

        start, end, is_current = _dates(
            entry.start_date, entry.end_date, entry.is_current, label=entry.institution, out=out
        )

        payload: dict[str, Any] = {
            "institution": entry.institution.strip(),
            "degree": entry.degree,
            "field_of_study": entry.field_of_study,
            "location": entry.location,
            "grade": entry.grade,
            "is_current": is_current,
            **_date_fields(start, end),
        }
        out.candidates.append(
            _draft(
                CandidateType.EDUCATION,
                payload,
                entry.confidence,
                entry.source_text,
                order,
                out,
                haystack=haystack,
                digits=digits,
            )
        )
        order += 1


# --- shared rules -------------------------------------------------------------


def _draft(
    candidate_type: CandidateType,
    payload: dict[str, Any],
    confidence: int,
    source_text: str | None,
    order: int,
    out: ValidatedExtraction,
    *,
    haystack: str,
    digits: set[str],
    number_source: str | None = None,
) -> CandidateDraft:
    """Build one draft, applying the two anti-fabrication checks."""
    label = _label(candidate_type, payload)
    flags: list[str] = []

    if source_text and _searchable(source_text) not in haystack:
        # The quote is not in the document. The item may still be right, but its
        # stated evidence is not, so the evidence is removed rather than shown.
        flags.append("QUOTE_NOT_FOUND")
        out.warnings.append(
            f"{label}: the quoted source text does not appear in the document, "
            "so it was removed. Check this item before accepting it."
        )
        source_text = None

    invented = _unsupported_numbers(number_source or "", digits)
    if invented:
        flags.append("UNSUPPORTED_NUMBERS")
        out.warnings.append(
            f"{label}: contains {', '.join(sorted(invented))}, which does not appear "
            "anywhere in the document. Verify before accepting."
        )

    if flags:
        confidence = min(confidence, UNVERIFIED_CONFIDENCE_CAP)
        payload = {**payload, "flags": flags}
        logger.info("Flagged extraction candidate", extra={"flags": flags, "type": candidate_type})

    return CandidateDraft(
        candidate_type=candidate_type,
        payload=payload,
        confidence=confidence,
        source_text=source_text,
        display_order=order,
    )


def _unsupported_numbers(text: str, document_digits: set[str]) -> set[str]:
    """Digit sequences in ``text`` that appear nowhere in the document.

    Compared as bare digit runs so "40%", "40 %", and "40 percent" all match a
    document containing "40" — the check is for invented *quantities*, and
    flagging a formatting difference as a fabrication would train the reviewer
    to ignore the warning.

    One- and two-digit runs are skipped: they are almost always ordinary text
    ("2 years", "top 5"), and a check that fires constantly is a check nobody
    reads.
    """
    return {run for run in _DIGIT_RUN.findall(text) if len(run) > 2 and run not in document_digits}


def _dates(
    start_raw: str | None,
    end_raw: str | None,
    is_current: bool,
    *,
    label: str,
    out: ValidatedExtraction,
) -> tuple[PartialDate | None, PartialDate | None, bool]:
    """Read both dates and reconcile them with ``is_current``."""
    start = PartialDate.parse(start_raw)
    end = PartialDate.parse(end_raw)

    if start_raw and start is None:
        out.warnings.append(f"{label}: the start date {start_raw!r} could not be read.")
    if end_raw and end is None:
        out.warnings.append(f"{label}: the end date {end_raw!r} could not be read.")

    if is_current and end is not None:
        # The database refuses this combination, and it is a contradiction
        # either way. The end date is the more specific claim, so it wins and
        # "current" is dropped.
        out.warnings.append(f"{label}: marked as current but has an end date. Treated as ended.")
        is_current = False

    if start is not None and end is not None and end.to_date() < start.to_date():
        out.warnings.append(
            f"{label}: the end date is before the start date, so both were kept but need checking."
        )

    return start, end, is_current


def _date_fields(start: PartialDate | None, end: PartialDate | None) -> dict[str, Any]:
    """Serialise dates plus the precision they were given at."""
    fields: dict[str, Any] = {
        "start_date": _iso(start),
        "end_date": _iso(end),
        "start_date_precision": start.precision if start else None,
        "end_date_precision": end.precision if end else None,
    }
    return fields


def _iso(value: PartialDate | None) -> str | None:
    return value.to_date().isoformat() if value else None


def parse_iso_date(value: Any) -> dt.date | None:
    """Read a stored ISO date back out of a candidate payload."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _safe_url(url: str | None, label: str, out: ValidatedExtraction) -> str | None:
    """Keep only http(s) URLs.

    These render as links on the profile, so a ``javascript:`` value extracted
    from a document would be stored XSS supplied by an uploaded file.
    """
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url.strip()
    out.warnings.append(f"{label}: dropped a link that is not a web address ({url!r}).")
    return None


def _label(candidate_type: CandidateType, payload: dict[str, Any]) -> str:
    """A human-readable name for a candidate, for use in warnings."""
    for key in ("name", "title", "company", "institution", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return str(candidate_type).replace("_", " ").title()


def _searchable(text: str) -> str:
    """Collapse whitespace and case so a quote can be located in the document."""
    return _WHITESPACE.sub(" ", text).strip().casefold()
