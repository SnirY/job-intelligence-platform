"""Applying reviewed extraction candidates to the career profile.

This is the step ``docs/10-api-contracts.md`` is protecting when it says AI
extraction must not write verified profile data directly. Nothing in the parse
path touches a career table; everything arrives here, and only for items the
user explicitly accepted or edited.

Three properties the implementation exists to guarantee:

- **Ignored items change nothing.** They are recorded as decided and skipped.
- **Confirming twice creates nothing twice.** Each item remembers the record it
  produced; a repeat confirmation returns that record instead of a second one.
- **Every write goes through the career services.** Domain rules, ownership,
  and skill normalization are theirs, and bypassing them here would mean two
  places that decide what a valid experience looks like.
"""

from __future__ import annotations

import datetime as dt
import enum
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.career import history as history_uc
from jip_api.application.career import skills as skills_uc
from jip_api.application.errors import ApplicationError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.application.resumes.validation import parse_iso_date
from jip_api.domain.career.history import Experience, Project
from jip_api.domain.career.models import VerificationStatus
from jip_api.domain.career.skills import SkillCategory, SkillSource
from jip_api.domain.documents.models import (
    CandidateDecision,
    CandidateType,
    DocumentExtraction,
    DocumentExtractionItem,
    DocumentStatus,
    SourceDocument,
)

logger = logging.getLogger(__name__)


class ConfirmAction(enum.StrEnum):
    """What the user chose for one candidate."""

    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    IGNORE = "IGNORE"


class ConfirmOutcome(enum.StrEnum):
    """What actually happened to a candidate."""

    CREATED = "CREATED"
    """A new career record was written."""

    LINKED = "LINKED"
    """Matched a record that already existed. Nothing was duplicated."""

    ALREADY_APPLIED = "ALREADY_APPLIED"
    """This item had already been applied. The repeat did nothing."""

    IGNORED = "IGNORED"
    SKIPPED_PARENT_NOT_ACCEPTED = "SKIPPED_PARENT_NOT_ACCEPTED"
    """A child whose parent was not accepted. An achievement with no role has
    nowhere to go, and inventing a role for it would be fabricating data."""

    INVALID = "INVALID"
    """The edited payload could not be applied. Reported, never guessed at."""


class InvalidDecisionError(ApplicationError):
    """The request referred to an item that is not part of this extraction."""


@dataclass(frozen=True, slots=True)
class Decision:
    """One user choice."""

    item_id: uuid.UUID
    action: ConfirmAction
    payload: dict[str, Any] | None = None
    """Only for ``EDIT``. Merged over the extracted payload, so a caller sending
    one changed field does not have to resend the rest."""


@dataclass(frozen=True, slots=True)
class AppliedItem:
    """What became of one decision."""

    item_id: uuid.UUID
    candidate_type: CandidateType
    outcome: ConfirmOutcome
    target_entity_type: str | None = None
    target_entity_id: uuid.UUID | None = None
    detail: str | None = None


@dataclass(slots=True)
class ConfirmationResult:
    """The whole confirmation."""

    applied: list[AppliedItem] = field(default_factory=list)
    remaining_pending: int = 0

    @property
    def created_count(self) -> int:
        return sum(1 for item in self.applied if item.outcome is ConfirmOutcome.CREATED)


# Parents before children, because a child's target depends on its parent's.
# Skills come first so a project technology can resolve against a canonical
# skill the same run already created.
_APPLY_ORDER: dict[CandidateType, int] = {
    CandidateType.SKILL: 0,
    CandidateType.EXPERIENCE: 1,
    CandidateType.EXPERIENCE_ACHIEVEMENT: 2,
    CandidateType.PROJECT: 3,
    CandidateType.PROJECT_SKILL: 4,
    CandidateType.EDUCATION: 5,
}


def confirm_extraction(
    session: Session,
    *,
    user_id: uuid.UUID,
    extraction: DocumentExtraction,
    decisions: list[Decision],
) -> ConfirmationResult:
    """Apply ``decisions`` to the user's career profile.

    One transaction, committed by the caller: a half-applied confirmation would
    leave the extraction claiming items were accepted that produced nothing.
    """
    items = {
        item.id: item
        for item in session.execute(
            owned(DocumentExtractionItem, user_id).where(
                DocumentExtractionItem.extraction_id == extraction.id
            )
        ).scalars()
    }

    unknown = [d.item_id for d in decisions if d.item_id not in items]
    if unknown:
        # A 404-shaped failure rather than skipping silently: an id that is not
        # in this extraction means the caller is confused about which review
        # they are submitting, and applying the rest would be worse.
        raise InvalidDecisionError(
            f"{len(unknown)} of the submitted items do not belong to this extraction."
        )

    ordered = sorted(decisions, key=lambda d: _APPLY_ORDER[items[d.item_id].candidate_type])

    result = ConfirmationResult()
    for decision in ordered:
        result.applied.append(_apply(session, user_id, items[decision.item_id], decision))

    session.flush()
    result.remaining_pending = _pending_count(session, extraction.id)
    if result.remaining_pending == 0:
        extraction.confirmed_at = dt.datetime.now(tz=dt.UTC)
        _mark_document_confirmed(session, extraction)

    logger.info(
        "Applied extraction decisions",
        extra={
            "extraction_id": str(extraction.id),
            "decided": len(ordered),
            "created": result.created_count,
            "pending": result.remaining_pending,
        },
    )
    return result


def _apply(
    session: Session,
    user_id: uuid.UUID,
    item: DocumentExtractionItem,
    decision: Decision,
) -> AppliedItem:
    """Apply one decision, recording it on the item."""
    if decision.action is ConfirmAction.IGNORE:
        _record(item, CandidateDecision.IGNORED)
        return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.IGNORED)

    if item.target_entity_id is not None:
        # Already applied. Returning the existing target rather than writing
        # again is what makes repeated confirmation a no-op.
        return AppliedItem(
            item.id,
            item.candidate_type,
            ConfirmOutcome.ALREADY_APPLIED,
            item.target_entity_type,
            item.target_entity_id,
        )

    if decision.action is ConfirmAction.EDIT and decision.payload is not None:
        item.edited_payload = {**item.payload, **decision.payload}

    payload = item.effective_payload

    try:
        applied = _write(session, user_id, item, payload)
    except InvalidDecisionError as exc:
        return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.INVALID, detail=str(exc))

    if applied.outcome is ConfirmOutcome.SKIPPED_PARENT_NOT_ACCEPTED:
        return applied

    item.target_entity_type = applied.target_entity_type
    item.target_entity_id = applied.target_entity_id
    _record(
        item,
        CandidateDecision.EDITED
        if decision.action is ConfirmAction.EDIT
        else CandidateDecision.ACCEPTED,
    )
    return applied


def _write(
    session: Session,
    user_id: uuid.UUID,
    item: DocumentExtractionItem,
    payload: dict[str, Any],
) -> AppliedItem:
    """Dispatch to the career service for this candidate type."""
    match item.candidate_type:
        case CandidateType.SKILL:
            return _write_skill(session, user_id, item, payload)
        case CandidateType.EXPERIENCE:
            return _write_experience(session, user_id, item, payload)
        case CandidateType.EXPERIENCE_ACHIEVEMENT:
            return _write_achievement(session, user_id, item, payload)
        case CandidateType.PROJECT:
            return _write_project(session, user_id, item, payload)
        case CandidateType.PROJECT_SKILL:
            return _write_project_skill(session, user_id, item, payload)
        case CandidateType.EDUCATION:
            return _write_education(session, user_id, item, payload)


def _write_skill(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    name = _required_text(payload, "name")
    user_skill, _, created = skills_uc.ensure_user_skill(
        session,
        user_id,
        skills_uc.UserSkillInput(
            name=name,
            category=_enum(SkillCategory, payload.get("category"), SkillCategory.OTHER),
            years_of_experience=_optional_int(payload.get("years_of_experience")),
            last_used_year=_optional_int(payload.get("last_used_year")),
            source=SkillSource.RESUME_IMPORT,
            # The user read this item and accepted it, which is explicit
            # confirmation (docs/06-resume-engine.md). Source keeps the
            # provenance: confirmed by a person, but originally from a resume.
            verification_status=VerificationStatus.USER_CONFIRMED,
        ),
    )
    return AppliedItem(
        item.id,
        item.candidate_type,
        ConfirmOutcome.CREATED if created else ConfirmOutcome.LINKED,
        "user_skill",
        user_skill.id,
    )


def _write_experience(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    company = _required_text(payload, "company")
    title = _required_text(payload, "title")
    start_date = parse_iso_date(payload.get("start_date"))
    end_date = parse_iso_date(payload.get("end_date"))
    is_current = bool(payload.get("is_current")) and end_date is None

    existing = history_uc.find_experience(
        session, user_id, company=company, title=title, start_date=start_date
    )
    if existing is not None:
        return AppliedItem(
            item.id, item.candidate_type, ConfirmOutcome.LINKED, "experience", existing.id
        )

    record = history_uc.create_experience(
        session,
        user_id,
        history_uc.ExperienceInput(
            company=company,
            title=title,
            employment_type=payload.get("employment_type"),
            location=_optional_text(payload.get("location")),
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            description=_optional_text(payload.get("description")),
        ),
    )
    return AppliedItem(
        item.id, item.candidate_type, ConfirmOutcome.CREATED, "experience", record.id
    )


def _write_achievement(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    experience = _parent_target(session, user_id, item, Experience, "experience")
    if experience is None:
        return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.SKIPPED_PARENT_NOT_ACCEPTED)

    achievement = history_uc.add_achievement(
        session,
        experience,
        text=_required_text(payload, "text"),
        display_order=item.display_order,
    )
    return AppliedItem(
        item.id,
        item.candidate_type,
        ConfirmOutcome.CREATED,
        "experience_achievement",
        achievement.id,
    )


def _write_project(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    name = _required_text(payload, "name")

    existing = history_uc.find_project(session, user_id, name=name)
    if existing is not None:
        return AppliedItem(
            item.id, item.candidate_type, ConfirmOutcome.LINKED, "project", existing.id
        )

    record = history_uc.create_project(
        session,
        user_id,
        history_uc.ProjectInput(
            name=name,
            project_type=payload.get("project_type"),
            status=payload.get("status"),
            summary=_optional_text(payload.get("summary")),
            description=_optional_text(payload.get("description")),
            start_date=parse_iso_date(payload.get("start_date")),
            end_date=parse_iso_date(payload.get("end_date")),
            repository_url=_optional_text(payload.get("repository_url")),
            demo_url=_optional_text(payload.get("demo_url")),
        ),
    )
    return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.CREATED, "project", record.id)


def _write_project_skill(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    project = _parent_target(session, user_id, item, Project, "project")
    if project is None:
        return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.SKIPPED_PARENT_NOT_ACCEPTED)

    # Resolved through the canonical catalogue, so "React.js" on a project links
    # to the same skill a job requirement for "React" will look for.
    skill = skills_uc.resolve_skill(session, _required_text(payload, "name"), SkillCategory.OTHER)
    history_uc.link_project_skill(session, project, skill.id)
    return AppliedItem(
        item.id, item.candidate_type, ConfirmOutcome.CREATED, "project_skill", skill.id
    )


def _write_education(
    session: Session, user_id: uuid.UUID, item: DocumentExtractionItem, payload: dict[str, Any]
) -> AppliedItem:
    institution = _required_text(payload, "institution")
    degree = _optional_text(payload.get("degree"))
    start_date = parse_iso_date(payload.get("start_date"))
    end_date = parse_iso_date(payload.get("end_date"))

    existing = history_uc.find_education(
        session, user_id, institution=institution, degree=degree, start_date=start_date
    )
    if existing is not None:
        return AppliedItem(
            item.id, item.candidate_type, ConfirmOutcome.LINKED, "education", existing.id
        )

    record = history_uc.create_education(
        session,
        user_id,
        history_uc.EducationInput(
            institution=institution,
            degree=degree,
            field_of_study=_optional_text(payload.get("field_of_study")),
            location=_optional_text(payload.get("location")),
            start_date=start_date,
            end_date=end_date,
            is_current=bool(payload.get("is_current")) and end_date is None,
            grade=_optional_text(payload.get("grade")),
        ),
    )
    return AppliedItem(item.id, item.candidate_type, ConfirmOutcome.CREATED, "education", record.id)


# --- helpers ------------------------------------------------------------------


def _parent_target[T](
    session: Session,
    user_id: uuid.UUID,
    item: DocumentExtractionItem,
    model: type[T],
    entity_type: str,
) -> T | None:
    """Resolve the career record a child item should attach to.

    Returns ``None`` when the parent has not been applied, which the caller
    turns into a skip. Scoped by user even though the parent item already was:
    the target id is stored data, and a stored id is not a capability.
    """
    if item.parent_item_id is None:
        return None

    parent = session.get(DocumentExtractionItem, item.parent_item_id)
    if parent is None or parent.user_id != user_id:
        return None
    if parent.target_entity_id is None or parent.target_entity_type != entity_type:
        return None

    record = session.get(model, parent.target_entity_id)
    if record is None or getattr(record, "user_id", None) != user_id:
        return None
    return record


def _record(item: DocumentExtractionItem, decision: CandidateDecision) -> None:
    item.decision = decision
    item.decided_at = dt.datetime.now(tz=dt.UTC)


def _pending_count(session: Session, extraction_id: uuid.UUID) -> int:
    statement = select(DocumentExtractionItem.id).where(
        DocumentExtractionItem.extraction_id == extraction_id,
        DocumentExtractionItem.decision == CandidateDecision.PENDING,
    )
    return len(list(session.execute(statement).scalars()))


def _mark_document_confirmed(session: Session, extraction: DocumentExtraction) -> None:
    document = session.get(SourceDocument, extraction.source_document_id)
    if document is not None:
        document.status = DocumentStatus.CONFIRMED


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidDecisionError(f"{key} is required and must not be blank.")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _enum[E: enum.StrEnum](enum_type: type[E], value: Any, default: E) -> E:
    """Read an enum from a payload, falling back rather than raising.

    An unexpected category is a presentation detail, not a reason to refuse a
    skill the user just accepted.
    """
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            return default
    return default


def load_extraction(
    session: Session, user_id: uuid.UUID, extraction_id: uuid.UUID
) -> DocumentExtraction:
    """Return one of the user's extractions, or raise."""
    extraction = session.execute(
        owned(DocumentExtraction, user_id).where(DocumentExtraction.id == extraction_id)
    ).scalar_one_or_none()
    if extraction is None:
        raise ResourceNotFoundError("Extraction not found.")
    return extraction
