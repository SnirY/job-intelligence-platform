"""Running a match and storing it.

```text
Load profile -> Load analysis -> Match -> Score -> (optional AI) -> Persist
```

Two properties shape this module:

- **Deterministic first, AI last.** The score exists before any model is
  consulted, and the AI step can only add a summary. If it fails, the match is
  already complete and the failure becomes a warning on the row.
- **History is never overwritten.** Recalculation appends a version. A user who
  disagrees with today's reading can still see the one they read last week, and
  Phase 10's insights need the series rather than the latest value.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_api.application.errors import ApplicationError
from jip_api.application.matching.evidence import ProfileSnapshot, load_profile_snapshot
from jip_api.application.matching.matcher import Verdict, match_requirements
from jip_api.application.matching.scoring import MatchResult, score_match
from jip_api.domain.jobs.analysis import JobAnalysis, JobRequirement
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import (
    JobMatch,
    JobMatchEvidence,
    JobMatchItem,
)
from jip_api.domain.matching.rules import MATCHING_ENGINE_VERSION

logger = logging.getLogger(__name__)


class JobNotMatchableError(ApplicationError):
    """The job cannot be matched: it has no analysis to match against."""


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """What one run produced."""

    match: JobMatch
    verdicts: list[Verdict]
    result: MatchResult


def run_match(
    session: Session,
    *,
    user_id: uuid.UUID,
    job: Job,
    analysis: JobAnalysis,
    requirements: list[JobRequirement],
    snapshot: ProfileSnapshot | None = None,
) -> MatchOutcome:
    """Match one job, and store the result as a new version.

    ``snapshot`` is injectable so the determinism test can run the same inputs
    twice without a database in between.
    """
    profile = snapshot if snapshot is not None else load_profile_snapshot(session, user_id)

    verdicts = match_requirements(requirements, profile)
    result = score_match(verdicts)

    match = _persist(
        session,
        user_id=user_id,
        job=job,
        analysis=analysis,
        verdicts=verdicts,
        result=result,
        fingerprint=profile.fingerprint(),
    )

    logger.info(
        "Matched job",
        extra={
            "job_id": str(job.id),
            "version": match.version,
            "score": result.overall_score,
            "recommendation": str(result.recommendation),
        },
    )
    return MatchOutcome(match=match, verdicts=verdicts, result=result)


def _persist(
    session: Session,
    *,
    user_id: uuid.UUID,
    job: Job,
    analysis: JobAnalysis,
    verdicts: list[Verdict],
    result: MatchResult,
    fingerprint: str,
) -> JobMatch:
    next_version = (
        session.execute(
            select(func.coalesce(func.max(JobMatch.version), 0)).where(JobMatch.job_id == job.id)
        ).scalar_one()
        + 1
    )

    match = JobMatch(
        user_id=user_id,
        job_id=job.id,
        analysis_id=analysis.id,
        version=next_version,
        analysis_version=analysis.version,
        profile_fingerprint=fingerprint,
        engine_version=MATCHING_ENGINE_VERSION,
        overall_score=result.overall_score,
        alignment_label=result.alignment_label,
        score_cap=result.score_cap,
        score_cap_reason=result.score_cap_reason,
        recommendation=result.recommendation,
        recommendation_reasons=list(result.recommendation_reasons),
        confidence=result.confidence,
        summary=None,
        category_scores=result.category_scores_json(),
        status_counts=dict(result.status_counts),
        has_blockers=result.has_blockers,
        scored_requirements=result.scored_requirements,
        total_requirements=result.total_requirements,
        warnings=list(result.warnings),
        computed_at=dt.datetime.now(tz=dt.UTC),
    )
    session.add(match)
    session.flush()

    for verdict in verdicts:
        item = JobMatchItem(
            user_id=user_id,
            match_id=match.id,
            job_id=job.id,
            requirement_id=verdict.requirement_id,
            status=verdict.status,
            category=verdict.category,
            score=verdict.score,
            weight=verdict.weight,
            confidence=verdict.confidence,
            explanation=verdict.explanation,
            is_blocker=verdict.is_blocker,
            source_order=verdict.source_order,
        )
        session.add(item)
        session.flush()

        for ref in verdict.evidence:
            session.add(
                JobMatchEvidence(
                    user_id=user_id,
                    match_item_id=item.id,
                    evidence_type=ref.evidence_type,
                    entity_id=ref.entity_id,
                    label=ref.label[:300],
                    # Copied rather than joined at read time: a historical match
                    # must still read correctly after the career row is edited,
                    # which is the point of keeping history at all.
                    detail=ref.detail,
                    verification_status=ref.verification_status,
                    relevance=ref.relevance,
                )
            )

    session.flush()
    return match
