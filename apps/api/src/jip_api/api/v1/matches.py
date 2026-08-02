"""Job match endpoints.

The three routes in ``docs/10-api-contracts.md``: read a match, compute one,
and read its items. Mounted under ``/jobs`` so they sit with the resource they
describe.

Matching is synchronous, unlike analysis. It is arithmetic over data already in
the database — no network call, no model on the critical path — so the 202
polling contract would add a round trip and a status to watch in exchange for
nothing. The optional AI summary runs after the match is persisted and cannot
delay or fail it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from jip_api.api.dependencies import CurrentUser
from jip_api.application.career import preference_fit
from jip_api.application.career.preference_fit import FitVerdict
from jip_api.application.career.preferences import get_or_create_preferences
from jip_api.application.jobs import analysis_uc
from jip_api.application.jobs import queries as job_queries
from jip_api.application.matching import queries as match_queries
from jip_api.application.matching.pipeline import run_match
from jip_api.core.responses import CollectionResponse, DataResponse, PaginationMeta
from jip_api.domain.jobs.analysis import JobAnalysis
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import (
    EvidenceType,
    JobMatchItem,
    MatchCategory,
    MatchStatus,
    Recommendation,
)
from jip_api.infrastructure.db.session import get_session

router = APIRouter(prefix="/jobs", tags=["matching"])

SessionDep = Annotated[Session, Depends(get_session)]


# --- payloads -----------------------------------------------------------------


class EvidencePayload(BaseModel):
    """One career fact behind a verdict.

    ``docs/08-ui-ux.md`` asks that a user be able to ask "why does the system
    think I match this?" and see the exact evidence. ``entity_id`` is what makes
    the answer openable rather than merely readable.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evidence_type: EvidenceType
    entity_id: uuid.UUID
    label: str
    detail: str | None
    verification_status: str
    relevance: int


class MatchItemPayload(BaseModel):
    """The verdict on one requirement, with its evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    status: MatchStatus
    category: MatchCategory
    score: int
    weight: float
    confidence: int
    explanation: str
    is_blocker: bool
    source_order: int
    evidence: list[EvidencePayload] = []


class MatchPayload(BaseModel):
    """A scored match.

    ``overall_score`` is nullable on purpose: a profile with nothing relevant
    produces no number rather than a zero, because zero is a claim about the
    candidate and null is a claim about our information.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    version: int
    overall_score: int | None
    alignment_label: str | None
    score_cap: int | None
    score_cap_reason: str | None
    recommendation: Recommendation
    recommendation_reasons: list[str]
    confidence: int
    summary: str | None
    category_scores: dict[str, object]
    status_counts: dict[str, int]
    has_blockers: bool
    scored_requirements: int
    total_requirements: int
    warnings: list[str]
    analysis_version: int
    engine_version: str
    computed_at: dt.datetime | None
    created_at: dt.datetime


class PreferenceFitPayload(BaseModel):
    """How one stated preference stands against this posting."""

    dimension: str
    verdict: FitVerdict
    detail: str


class MatchView(BaseModel):
    """Everything the Job Detail match panel needs, in one call."""

    job_id: uuid.UUID
    match: MatchPayload | None
    items: list[MatchItemPayload]
    is_stale: bool
    stale_reasons: list[str]
    available_versions: list[int]
    can_match: bool
    """Whether ``POST /match`` would be accepted. Keeps the button's enabled
    state and the endpoint's refusal in one place."""

    blocking_reason: str | None
    """Why it would not be, when it would not."""

    preference_fit: list[PreferenceFitPayload]
    """What the user said they want, against what this posting says.

    Computed on read and deliberately outside the match. Alignment is about
    evidence — whether the profile answers what the posting asked for — and a
    job in the wrong city does not fit your skills any less. Folding preference
    into the score would move a number when nothing about the fit moved, and
    `job_matches.recommendation` is written once at match time, so a preference
    changed tomorrow would leave every stored recommendation quietly stale.

    Present even when there is no match and even when the user has set nothing:
    every dimension is always returned, because a short list of satisfied
    preferences reads as a clean bill of health when it is really a list of
    things nobody checked. DEV-035.
    """


# --- routes -------------------------------------------------------------------


@router.get(
    "/{job_id}/match",
    response_model=DataResponse[MatchView],
    summary="Get a job's match",
)
def read_match(
    user: CurrentUser,
    session: SessionDep,
    job_id: uuid.UUID,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> DataResponse[MatchView]:
    """The newest match, or a specific version.

    Answers 200 with a null match for a job that has never been matched, rather
    than 404. The job exists; a 404 would report a different problem.
    """
    job = job_queries.get_job(session, user.id, job_id)
    analysis = analysis_uc.latest_analysis(session, user.id, job_id)

    match = (
        match_queries.get_match_version(session, user.id, job_id, version)
        if version is not None
        else match_queries.latest_match(session, user.id, job_id)
    )

    staleness = match_queries.assess_staleness(
        session,
        user.id,
        match,
        current_analysis_version=analysis.version if analysis else None,
    )

    can_match, blocking_reason = _can_match(analysis)

    return DataResponse(
        data=MatchView(
            job_id=job.id,
            match=MatchPayload.model_validate(match) if match else None,
            items=_items(session, match.id) if match else [],
            is_stale=staleness.is_stale,
            stale_reasons=staleness.reasons,
            available_versions=match_queries.match_versions(session, user.id, job_id),
            can_match=can_match,
            blocking_reason=blocking_reason,
            preference_fit=_preference_fit(session, user.id, job, analysis),
        )
    )


@router.post(
    "/{job_id}/match",
    response_model=DataResponse[MatchView],
    summary="Match a job against the career profile",
)
def post_match(
    user: CurrentUser,
    session: SessionDep,
    job_id: uuid.UUID,
) -> DataResponse[MatchView]:
    """Compute a match, or recompute one.

    The same endpoint for both: a recalculation is the same operation run
    again, and the result is a new version rather than a replacement.
    """
    job = job_queries.get_job(session, user.id, job_id)
    analysis = analysis_uc.latest_analysis(session, user.id, job_id)

    can_match, blocking_reason = _can_match(analysis)
    if not can_match or analysis is None:
        raise _conflict(blocking_reason or "This job cannot be matched yet.")

    requirements = analysis_uc.requirements_for(session, analysis.id)
    outcome = run_match(
        session,
        user_id=user.id,
        job=job,
        analysis=analysis,
        requirements=requirements,
    )
    session.commit()

    return DataResponse(
        data=MatchView(
            job_id=job.id,
            match=MatchPayload.model_validate(outcome.match),
            items=_items(session, outcome.match.id),
            is_stale=False,
            stale_reasons=[],
            available_versions=match_queries.match_versions(session, user.id, job_id),
            can_match=True,
            blocking_reason=None,
            preference_fit=_preference_fit(session, user.id, job, analysis),
        )
    )


def _preference_fit(
    session: Session, user_id: uuid.UUID, job: Job, analysis: JobAnalysis | None
) -> list[PreferenceFitPayload]:
    """Read the user's preferences against this posting.

    `get_or_create_preferences` rather than a plain lookup, so a first visit
    behaves the same as every later one: an empty row means no constraints, and
    every dimension reports that plainly instead of the endpoint branching on
    whether a row happens to exist.
    """
    preferences = get_or_create_preferences(session, user_id)
    return [
        PreferenceFitPayload(dimension=fit.dimension, verdict=fit.verdict, detail=fit.detail)
        for fit in preference_fit.assess(job=job, analysis=analysis, preferences=preferences)
    ]


@router.get(
    "/{job_id}/match/items",
    response_model=CollectionResponse[MatchItemPayload],
    summary="Get a job match's requirement-level items",
)
def read_match_items(
    user: CurrentUser,
    session: SessionDep,
    job_id: uuid.UUID,
    status: MatchStatus | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> CollectionResponse[MatchItemPayload]:
    """The requirement-by-requirement verdicts, optionally filtered.

    Separate from the match because "show me only the gaps" is a common read
    and should not require shipping every item to answer.
    """
    job_queries.get_job(session, user.id, job_id)

    match = (
        match_queries.get_match_version(session, user.id, job_id, version)
        if version is not None
        else match_queries.latest_match(session, user.id, job_id)
    )

    items = _items(session, match.id) if match else []
    if status is not None:
        items = [item for item in items if item.status is status]

    return CollectionResponse(
        data=items,
        meta=PaginationMeta(
            page=1,
            page_size=len(items),
            total=len(items),
            total_pages=1 if items else 0,
        ),
    )


# --- helpers ------------------------------------------------------------------


def _items(session: Session, match_id: uuid.UUID) -> list[MatchItemPayload]:
    """Items with their evidence attached, in one extra query rather than N."""
    rows: list[JobMatchItem] = match_queries.match_items(session, match_id)
    evidence = match_queries.evidence_for(session, [row.id for row in rows])

    payloads: list[MatchItemPayload] = []
    for row in rows:
        payload = MatchItemPayload.model_validate(row)
        payload.evidence = [EvidencePayload.model_validate(ref) for ref in evidence.get(row.id, [])]
        payloads.append(payload)
    return payloads


def _can_match(analysis: object | None) -> tuple[bool, str | None]:
    """Whether a match can be computed, and why not when it cannot.

    One reason only: there is nothing to match against until the posting has
    been analysed. An empty career profile is deliberately *not* a refusal —
    the goal is explicit that an incomplete profile must not be penalised, and
    a match full of NO_EVIDENCE is a useful thing to show someone. It tells
    them exactly what to fill in.
    """
    if analysis is None:
        return False, "This job has not been analysed yet, so there is nothing to match against."
    return True, None


def _conflict(message: str) -> Exception:
    from jip_api.core.errors import ConflictError

    return ConflictError(message)
