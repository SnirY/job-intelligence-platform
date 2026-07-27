"""Reading matches back, and deciding whether one is stale.

Staleness is the interesting part. ``docs/02-user-flows.md`` Flow 12 says a
profile change makes affected matches stale and recalculable, and there are
three independent ways that can happen — the posting was re-read, the profile
changed, or the rules changed. All three are recorded on the match, so this
module compares rather than guesses, and can say *which* one moved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.matching.evidence import load_profile_snapshot
from jip_api.application.ownership import owned
from jip_api.domain.matching.models import JobMatch, JobMatchEvidence, JobMatchItem
from jip_api.domain.matching.rules import MATCHING_ENGINE_VERSION


@dataclass(frozen=True, slots=True)
class Staleness:
    """Whether a match still reflects its inputs, and what moved if not."""

    is_stale: bool
    reasons: list[str]

    @property
    def analysis_changed(self) -> bool:
        return any("posting" in reason for reason in self.reasons)


def latest_match(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> JobMatch | None:
    """The newest match for a job."""
    return session.execute(
        owned(JobMatch, user_id)
        .where(JobMatch.job_id == job_id)
        .order_by(desc(JobMatch.version))
        .limit(1)
    ).scalar_one_or_none()


def get_match_version(
    session: Session, user_id: uuid.UUID, job_id: uuid.UUID, version: int
) -> JobMatch:
    """One specific version, or raise.

    Exists so a user reading an older match keeps reading it after a
    recalculation lands — versions are kept precisely so they stay reachable.
    """
    match = session.execute(
        owned(JobMatch, user_id).where(JobMatch.job_id == job_id, JobMatch.version == version)
    ).scalar_one_or_none()
    if match is None:
        raise ResourceNotFoundError("Match not found.")
    return match


def match_versions(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> list[int]:
    """Every version number for a job, newest first."""
    statement = (
        owned(JobMatch, user_id)
        .where(JobMatch.job_id == job_id)
        .order_by(desc(JobMatch.version))
        .with_only_columns(JobMatch.version)
    )
    return [int(row) for row in session.execute(statement).scalars()]


def match_items(session: Session, match_id: uuid.UUID) -> list[JobMatchItem]:
    """Every item in a match, in the posting's own order.

    Not scoped by user: the caller resolved the match through an
    ownership-checked query, and the match owns its items.
    """
    return list(
        session.execute(
            select(JobMatchItem)
            .where(JobMatchItem.match_id == match_id)
            .order_by(JobMatchItem.source_order, JobMatchItem.id)
        ).scalars()
    )


def evidence_for(
    session: Session, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[JobMatchEvidence]]:
    """Evidence for many items at once, keyed by item.

    Batched because a match has as many items as the posting has requirements,
    and one query per item would make reading a match O(requirements) round
    trips.
    """
    if not item_ids:
        return {}

    grouped: dict[uuid.UUID, list[JobMatchEvidence]] = {}
    rows = session.execute(
        select(JobMatchEvidence)
        .where(JobMatchEvidence.match_item_id.in_(item_ids))
        .order_by(desc(JobMatchEvidence.relevance), JobMatchEvidence.label)
    ).scalars()
    for row in rows:
        grouped.setdefault(row.match_item_id, []).append(row)
    return grouped


def assess_staleness(
    session: Session,
    user_id: uuid.UUID,
    match: JobMatch | None,
    *,
    current_analysis_version: int | None,
) -> Staleness:
    """Whether ``match`` still reflects the world it was computed from.

    Recomputes the profile fingerprint rather than trusting a flag: a flag
    would need every career write path to remember to set it, and the one that
    forgets is the one that leaves a wrong number on screen.
    """
    if match is None:
        return Staleness(is_stale=False, reasons=[])

    reasons: list[str] = []

    if current_analysis_version is not None and current_analysis_version != match.analysis_version:
        reasons.append(
            f"The posting has been re-read since this match "
            f"(analysis v{match.analysis_version} → v{current_analysis_version})."
        )

    snapshot = load_profile_snapshot(session, user_id)
    if snapshot.fingerprint() != match.profile_fingerprint:
        reasons.append("Your career profile has changed since this match.")

    if match.engine_version != MATCHING_ENGINE_VERSION:
        reasons.append(
            f"The matching rules have changed since this match "
            f"(engine {match.engine_version} → {MATCHING_ENGINE_VERSION})."
        )

    return Staleness(is_stale=bool(reasons), reasons=reasons)
