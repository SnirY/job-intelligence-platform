"""Tailoring and rendering endpoints.

The routes from ``docs/10-api-contracts.md``: create a strategy for a job,
generate suggestions from it, accept / reject / edit each one, finalise into a
version, and render.

Each stage is its own request on purpose. ``docs/09-mvp-roadmap.md`` forbids one
call that rewrites a document, and an API that produced a finished resume from
a single POST would be that call wearing a REST costume.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_ai import AIError, AIOperation
from jip_api.api.dependencies import CurrentUser
from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.jobs import queries as job_queries
from jip_api.application.ownership import owned
from jip_api.application.resumes import authoring, rendering
from jip_api.application.resumes import tailoring_service as tailoring
from jip_api.core.errors import ServiceUnavailableError
from jip_api.core.responses import DataResponse
from jip_api.domain.ai.models import AIRun
from jip_api.domain.career.models import CareerProfile
from jip_api.domain.resumes.tailoring import (
    ClaimStatus,
    ResumeClaim,
    ResumeStrategy,
    ResumeSuggestion,
    SuggestionRisk,
    SuggestionStatus,
    SuggestionType,
)
from jip_api.infrastructure.ai import get_ai_provider, get_model_router
from jip_api.infrastructure.db.session import get_session
from jip_config import get_settings

router = APIRouter(tags=["resumes"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class ClaimPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    status: ClaimStatus
    explanation: str
    confidence: int


class SuggestionPayload(BaseModel):
    """One proposed change, with everything needed to judge it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID | None
    suggestion_type: SuggestionType
    status: SuggestionStatus
    risk: SuggestionRisk
    original_text: str | None
    suggested_text: str
    final_text: str | None
    rationale: str | None
    display_order: int
    claims: list[ClaimPayload] = []
    requires_review: bool = False
    """True for medium and high risk. ``docs/06-resume-engine.md`` requires
    those to be reviewed, and serving the answer keeps the rule in one place."""

    is_blocked: bool = False
    """A claim this suggestion makes is not supported by the profile. Accepting
    it would put something untrue on the page."""


class StrategyPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    match_id: uuid.UUID
    version: int
    version_id: uuid.UUID | None
    summary: str | None
    emphasize: list[str]
    reduce: list[str]
    reorder_note: str | None
    priority_projects: list[str]
    missing_evidence: list[str]
    career_gaps: list[str]
    selection: dict[str, object]
    model: str | None
    prompt_version: str | None
    warnings: list[str]
    created_at: dt.datetime


class StrategyView(BaseModel):
    """A strategy with its suggestions."""

    strategy: StrategyPayload | None
    suggestions: list[SuggestionPayload] = []
    blocked_count: int = 0
    can_create: bool = True
    blocking_reason: str | None = None
    suggestions_generated: bool = False
    """Whether the rewriter has run for this strategy, regardless of what it found.

    An empty list means two different things and the screen could not tell them
    apart: *you have not asked yet*, and *we asked and there was nothing worth
    changing*. Both rendered as "No suggestions yet", so a completed run that
    proposed nothing looked exactly like a button that had not been pressed.

    Found in Stage 2.8.6 against a resume of placeholder lines with no
    supporting facts. The rewriter is told it may only say what those facts
    support and that an empty list is the right answer when nothing needs
    changing, so it correctly returned none — and the screen reported that as
    though nothing had happened.

    Read from `ai_runs` rather than stored on the strategy: the run record is
    already written on both the success and failure paths, so this cannot
    disagree with what actually happened.
    """


class EditRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class FinalizeResult(BaseModel):
    """What finalising produced."""

    version_id: uuid.UUID
    version: int
    applied: int


class FinalizeRequest(BaseModel):
    resume_id: uuid.UUID
    """The resume family the tailored version belongs to."""

    label: str | None = Field(default=None, max_length=200)


# --- strategy -----------------------------------------------------------------


@router.get(
    "/jobs/{job_id}/resume-strategies",
    response_model=DataResponse[StrategyView],
    summary="Get the tailoring strategy for a job",
)
def read_strategy(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[StrategyView]:
    """The newest strategy, or a null one with the reason it cannot be made."""
    job_queries.get_job(session, user.id, job_id)

    strategy = _latest_strategy(session, user.id, job_id)
    can_create, reason = _can_create_strategy(session, user.id, job_id)

    if strategy is None:
        return DataResponse(
            data=StrategyView(strategy=None, can_create=can_create, blocking_reason=reason)
        )

    return DataResponse(
        data=StrategyView(
            strategy=StrategyPayload.model_validate(strategy),
            suggestions=_suggestions(session, strategy.id),
            blocked_count=tailoring.blocked_count(session, strategy.id),
            can_create=can_create,
            blocking_reason=reason,
            suggestions_generated=_has_generated(session, strategy.id),
        )
    )


@router.post(
    "/jobs/{job_id}/resume-strategies",
    response_model=DataResponse[StrategyView],
    status_code=status.HTTP_201_CREATED,
    summary="Plan how to tailor a resume for this job",
)
def post_strategy(
    user: CurrentUser, session: SessionDep, job_id: uuid.UUID
) -> DataResponse[StrategyView]:
    """Select the evidence and plan the tailoring.

    Selection is deterministic and happens whether or not AI is available; the
    written plan is the only part that needs a model. If it fails, the strategy
    still exists with its selection intact, because ``docs/02-user-flows.md``
    says AI failure must never block manual usage.
    """
    job = job_queries.get_job(session, user.id, job_id)

    provider = router_ = None
    settings = get_settings()
    if settings.ai_configured:
        try:
            provider, router_ = get_ai_provider(), get_model_router()
        except Exception:
            provider = router_ = None

    outcome = tailoring.create_strategy(
        session,
        provider,
        router_,
        user_id=user.id,
        job=job,
        max_attempts=settings.ai_max_attempts,
    )
    session.commit()

    return DataResponse(
        data=StrategyView(
            strategy=StrategyPayload.model_validate(outcome.strategy),
            suggestions=[],
            can_create=True,
        )
    )


@router.post(
    "/resume-strategies/{strategy_id}/suggestions",
    response_model=DataResponse[StrategyView],
    summary="Generate rewrite suggestions",
)
def post_suggestions(
    user: CurrentUser,
    session: SessionDep,
    strategy_id: uuid.UUID,
    version_id: uuid.UUID,
) -> DataResponse[StrategyView]:
    """Propose one change per line, each validated against the evidence.

    ``version_id`` names the draft being tailored. A used or archived version
    is refused, because its content cannot change and suggestions against it
    could never be applied.
    """
    strategy = _get_strategy(session, user.id, strategy_id)
    version = authoring.editable_version(session, user.id, version_id)
    job = job_queries.get_job(session, user.id, strategy.job_id)

    # Unlike the strategy, rewriting has no deterministic half to fall back on:
    # without a model there is nothing to propose. 503 says the server cannot
    # do this right now, which is true; a 500 would say it broke, which is not.
    try:
        provider, model_router = get_ai_provider(), get_model_router()
    except AIError as error:
        raise ServiceUnavailableError(
            "Rewrite suggestions need AI, which is not available on this server."
        ) from error

    settings = get_settings()
    outcome = tailoring.create_suggestions(
        session,
        provider,
        model_router,
        user_id=user.id,
        strategy=strategy,
        version=version,
        job=job,
        max_attempts=settings.ai_max_attempts,
    )
    strategy.version_id = version.id
    if outcome.warnings:
        strategy.warnings = [*strategy.warnings, *outcome.warnings]
    session.commit()

    return DataResponse(
        data=StrategyView(
            strategy=StrategyPayload.model_validate(strategy),
            suggestions=_suggestions(session, strategy.id),
            blocked_count=tailoring.blocked_count(session, strategy.id),
            suggestions_generated=True,
        )
    )


# --- review -------------------------------------------------------------------


@router.post(
    "/resume-suggestions/{suggestion_id}/accept",
    response_model=DataResponse[SuggestionPayload],
    summary="Accept a suggestion",
)
def post_accept(
    user: CurrentUser, session: SessionDep, suggestion_id: uuid.UUID
) -> DataResponse[SuggestionPayload]:
    """Take the rewrite as proposed.

    Allowed even when a claim is blocked. The user may know the figure is real,
    and ``docs/06-resume-engine.md`` wants the system to *ask* rather than to
    overrule — the block is shown to them, prominently, and the decision is
    theirs. What the system will not do is apply it without asking.
    """
    return DataResponse(data=_decide(session, user.id, suggestion_id, SuggestionStatus.ACCEPTED))


@router.post(
    "/resume-suggestions/{suggestion_id}/reject",
    response_model=DataResponse[SuggestionPayload],
    summary="Reject a suggestion",
)
def post_reject(
    user: CurrentUser, session: SessionDep, suggestion_id: uuid.UUID
) -> DataResponse[SuggestionPayload]:
    return DataResponse(data=_decide(session, user.id, suggestion_id, SuggestionStatus.REJECTED))


@router.post(
    "/resume-suggestions/{suggestion_id}/edit",
    response_model=DataResponse[SuggestionPayload],
    summary="Accept a suggestion with your own wording",
)
def post_edit(
    user: CurrentUser, session: SessionDep, suggestion_id: uuid.UUID, body: EditRequest
) -> DataResponse[SuggestionPayload]:
    """The user's own words win.

    Stored in ``final_text`` rather than overwriting ``suggested_text``, so the
    record still shows what was proposed alongside what was taken.
    """
    return DataResponse(
        data=_decide(session, user.id, suggestion_id, SuggestionStatus.EDITED, text=body.text)
    )


@router.post(
    "/resume-strategies/{strategy_id}/finalize",
    response_model=DataResponse[FinalizeResult],
    summary="Apply accepted suggestions to a new version",
)
def post_finalize(
    user: CurrentUser, session: SessionDep, strategy_id: uuid.UUID, body: FinalizeRequest
) -> DataResponse[FinalizeResult]:
    """Write the reviewed result as a new version.

    A new version rather than an edit in place: the draft that was reviewed
    stays readable, and ``docs/06-resume-engine.md`` requires every
    job-specific version to preserve its parent.

    Only ACCEPTED and EDITED suggestions are applied. Pending ones are ignored
    — silence is not consent — and rejected ones leave the original line alone.
    """
    strategy = _get_strategy(session, user.id, strategy_id)
    if strategy.version_id is None:
        raise ResourceNotFoundError("This strategy has no draft to finalise.")

    source = authoring.get_version(session, user.id, strategy.version_id)

    applied = {
        suggestion.item_id: suggestion.applied_text
        for suggestion in session.execute(
            owned(ResumeSuggestion, user.id).where(
                ResumeSuggestion.strategy_id == strategy.id,
                ResumeSuggestion.status.in_([SuggestionStatus.ACCEPTED, SuggestionStatus.EDITED]),
            )
        ).scalars()
        if suggestion.item_id is not None
    }

    new_version = authoring.create_version(
        session,
        user.id,
        body.resume_id,
        parent_version_id=source.id,
        label=body.label or "Tailored",
    )

    sections = [
        authoring.SectionInput(
            kind=section.kind,
            title=section.title,
            display_order=section.display_order,
            items=[
                authoring.ItemInput(
                    text=applied.get(item.id, item.text),
                    source_type=item.source_type,
                    source_entity_id=item.source_entity_id,
                    heading=item.heading,
                    display_order=item.display_order,
                )
                for item in items
            ],
        )
        for section, items in authoring.load_content(session, source.id)
    ]
    authoring.replace_content(session, user.id, new_version.id, sections)
    session.commit()

    return DataResponse(
        data=FinalizeResult(
            version_id=new_version.id, version=new_version.version, applied=len(applied)
        )
    )


# --- rendering ----------------------------------------------------------------


@router.get(
    "/resume-versions/{version_id}/render",
    response_class=Response,
    summary="Render a version as printable HTML",
)
def get_render(user: CurrentUser, session: SessionDep, version_id: uuid.UUID) -> Response:
    """A self-contained document the browser can print to PDF.

    See ADR-0006. Ownership is checked before anything is rendered, which is
    the "User A cannot download User B resume" test
    ``docs/11-engineering-standards.md`` requires.
    """
    version = authoring.get_version(session, user.id, version_id)
    profile = session.execute(
        select(CareerProfile).where(CareerProfile.user_id == user.id)
    ).scalar_one_or_none()

    rendered = rendering.render_version(session, version, profile=profile)
    return Response(
        content=rendered.html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{rendered.filename}"'},
    )


# --- helpers ------------------------------------------------------------------


def _latest_strategy(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> ResumeStrategy | None:
    return session.execute(
        owned(ResumeStrategy, user_id)
        .where(ResumeStrategy.job_id == job_id)
        .order_by(ResumeStrategy.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def _get_strategy(session: Session, user_id: uuid.UUID, strategy_id: uuid.UUID) -> ResumeStrategy:
    strategy = session.execute(
        owned(ResumeStrategy, user_id).where(ResumeStrategy.id == strategy_id)
    ).scalar_one_or_none()
    if strategy is None:
        raise ResourceNotFoundError("Strategy not found.")
    return strategy


def _can_create_strategy(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Whether a strategy could be created, and why not when it could not.

    Mirrors the refusal in ``tailoring_service.create_strategy`` so the button
    and the endpoint agree, the same pattern as ``can_match`` in Phase 6.
    """
    from jip_api.application.matching import queries as match_queries

    if match_queries.latest_match(session, user_id, job_id) is None:
        return False, (
            "This job has not been matched against your profile yet, so there is "
            "nothing to tailor from."
        )
    return True, None


def _has_generated(session: Session, strategy_id: uuid.UUID) -> bool:
    """Whether a rewrite run exists for this strategy.

    `create_suggestions` persists its traces on both paths, so the presence of a
    run is the honest answer to "has this been asked for", independent of how
    many suggestions came back.
    """
    return (
        session.execute(
            select(AIRun.id)
            .where(
                AIRun.operation == str(AIOperation.RESUME_REWRITE),
                AIRun.entity_id == strategy_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _suggestions(session: Session, strategy_id: uuid.UUID) -> list[SuggestionPayload]:
    rows = list(
        session.execute(
            select(ResumeSuggestion)
            .where(ResumeSuggestion.strategy_id == strategy_id)
            .order_by(ResumeSuggestion.display_order, ResumeSuggestion.id)
        ).scalars()
    )
    if not rows:
        return []

    claims: dict[uuid.UUID, list[ResumeClaim]] = {}
    for claim in session.execute(
        select(ResumeClaim).where(ResumeClaim.suggestion_id.in_([row.id for row in rows]))
    ).scalars():
        claims.setdefault(claim.suggestion_id, []).append(claim)

    payloads: list[SuggestionPayload] = []
    for row in rows:
        payload = SuggestionPayload.model_validate(row)
        row_claims = claims.get(row.id, [])
        payload.claims = [ClaimPayload.model_validate(claim) for claim in row_claims]
        payload.requires_review = row.risk.requires_review
        payload.is_blocked = any(claim.status is ClaimStatus.BLOCKED for claim in row_claims)
        payloads.append(payload)
    return payloads


def _decide(
    session: Session,
    user_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    status_: SuggestionStatus,
    *,
    text: str | None = None,
) -> SuggestionPayload:
    suggestion = session.execute(
        owned(ResumeSuggestion, user_id).where(ResumeSuggestion.id == suggestion_id)
    ).scalar_one_or_none()
    if suggestion is None:
        raise ResourceNotFoundError("Suggestion not found.")

    suggestion.status = status_
    suggestion.decided_at = dt.datetime.now(tz=dt.UTC)
    if text is not None:
        suggestion.final_text = text.strip()
    session.commit()

    return _suggestion_payload(session, suggestion)


def _suggestion_payload(session: Session, suggestion: ResumeSuggestion) -> SuggestionPayload:
    payload = SuggestionPayload.model_validate(suggestion)
    rows = list(
        session.execute(
            select(ResumeClaim).where(ResumeClaim.suggestion_id == suggestion.id)
        ).scalars()
    )
    payload.claims = [ClaimPayload.model_validate(claim) for claim in rows]
    payload.requires_review = suggestion.risk.requires_review
    payload.is_blocked = any(claim.status is ClaimStatus.BLOCKED for claim in rows)
    return payload
