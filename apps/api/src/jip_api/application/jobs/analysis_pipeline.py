"""The job analysis pipeline, as run by the worker.

```text
Parse -> Validate -> Analyse -> Validate -> Resolve skills -> Persist
```

Three properties shape the code:

- **A failure never destroys work** (``GOAL.md``). The job, its description,
  its original description, its import records, and every previous analysis are
  all untouched by a failure. The only thing that changes is the job's status
  and the processing job's error.
- **AI never overwrites what a person typed.** The analysis lands in
  ``job_analyses`` and stops there. ``jobs.role_family`` and ``jobs.seniority``
  are the *user's* answers and are not written here, even though this phase now
  has better ones.
- **Interpretation cannot edit facts.** The analysis step is given the parse and
  returns judgements; its schema has no field through which a requirement could
  be added or changed.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_ai import AIError, AIFailureCode, AIRunTrace, LLMProvider, ModelRouter
from jip_api.application.jobs.analysis_services import (
    JobAnalysisOutcome,
    JobAnalyzerService,
    JobParseOutcome,
    JobParsingService,
)
from jip_api.application.jobs.analysis_uc import analysis_source_hash
from jip_api.application.jobs.requirement_skills import resolve_known_skills
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.ai.models import AIRun, AIRunStatus
from jip_api.domain.jobs.analysis import (
    JobAnalysis,
    JobRequirement,
    JobResponsibility,
)
from jip_api.domain.jobs.models import Job, JobImportMethod, JobProcessingStatus
from jip_api.domain.processing.models import ProcessingJob, ProcessingStep

logger = logging.getLogger(__name__)

ENTITY_TYPE = "job"


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """What one run produced."""

    job_id: uuid.UUID
    analysis_id: uuid.UUID
    version: int
    requirement_count: int
    responsibility_count: int


def run_analysis(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: ProcessingJob,
    max_input_chars: int,
    max_attempts: int,
) -> AnalysisResult:
    """Take a job from queued to analysed.

    Commits between steps rather than wrapping the run in one transaction, for
    the same reason the resume pipeline does: the status the user is polling
    has to be visible while the work is still going.
    """
    target = session.get(Job, job.entity_id)
    if target is None:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "The job for this analysis no longer exists.",
        )

    text = (target.description or "").strip()
    if not text:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "This job has no description to analyse yet.",
        )

    parse = _parse(
        session,
        provider,
        router,
        job=job,
        target=target,
        text=text,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    analysis = _analyze(
        session,
        provider,
        router,
        job=job,
        target=target,
        text=text,
        parse=parse,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    stored = _persist(session, target=target, parse=parse, analysis=analysis)

    target.status = JobProcessingStatus.ANALYZED
    jobs_uc.mark_completed(session, job)
    session.commit()

    return AnalysisResult(
        job_id=target.id,
        analysis_id=stored.id,
        version=stored.version,
        requirement_count=len(parse.validated.requirements),
        responsibility_count=len(parse.validated.responsibilities),
    )


def _parse(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: ProcessingJob,
    target: Job,
    text: str,
    max_input_chars: int,
    max_attempts: int,
) -> JobParseOutcome:
    """Run the parser, recording every attempt as an ``AIRun``."""
    jobs_uc.mark_running(session, job, ProcessingStep.PARSING)
    target.status = JobProcessingStatus.PARSING
    session.commit()

    service = JobParsingService(
        provider,
        router,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    try:
        outcome = service.parse(text, source_note=_source_note(target))
    except AIError:
        _mark_analysis_failed(session, target)
        raise

    for trace in outcome.traces:
        session.add(_ai_run(trace, user_id=target.user_id, job_id=target.id))
    session.flush()
    return outcome


def _analyze(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: ProcessingJob,
    target: Job,
    text: str,
    parse: JobParseOutcome,
    max_input_chars: int,
    max_attempts: int,
) -> JobAnalysisOutcome:
    """Run the analyser over the parse."""
    jobs_uc.advance(session, job, ProcessingStep.ANALYZING)
    target.status = JobProcessingStatus.ANALYZING
    session.commit()

    service = JobAnalyzerService(
        provider,
        router,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    try:
        outcome = service.analyze(text, parse.validated)
    except AIError:
        _mark_analysis_failed(session, target)
        raise

    for trace in outcome.traces:
        session.add(_ai_run(trace, user_id=target.user_id, job_id=target.id))
    session.flush()
    return outcome


def _mark_analysis_failed(session: Session, target: Job) -> None:
    """Record the failure on the job without touching anything else.

    ANALYSIS_FAILED rather than FAILED: the description is fine, and FAILED is
    what the UI reads to offer a paste box. Telling someone to re-enter text
    that is already there would be the wrong recovery for this failure.
    """
    target.status = JobProcessingStatus.ANALYSIS_FAILED
    session.commit()


def _source_note(target: Job) -> str:
    """One line telling the parser where this text came from.

    Extraction from a web page leaves navigation and boilerplate behind that a
    pasted description does not have, and a parser that knows this reads a
    stray "Apply now" as chrome rather than as a requirement.
    """
    if target.import_method is JobImportMethod.URL:
        return (
            "This text was extracted from a web page, so navigation, cookie "
            "notices, and other site furniture may be mixed in. Ignore anything "
            "that is not part of the posting."
        )
    return "This is the description as the user saved it."


def _ai_run(trace: AIRunTrace, *, user_id: uuid.UUID, job_id: uuid.UUID) -> AIRun:
    """Map a trace onto the ``ai_runs`` row."""
    return AIRun(
        user_id=user_id,
        operation=trace.operation,
        entity_type=ENTITY_TYPE,
        entity_id=job_id,
        provider=trace.provider,
        model=trace.model,
        prompt_version=trace.prompt_version,
        input_hash=trace.input_hash,
        status=AIRunStatus.SUCCEEDED if trace.succeeded else AIRunStatus.FAILED,
        failure_code=str(trace.failure_code) if trace.failure_code else None,
        error_message=trace.error_message,
        latency_ms=trace.latency_ms,
        input_tokens=trace.usage.input_tokens,
        output_tokens=trace.usage.output_tokens,
        estimated_cost_usd=trace.estimated_cost_usd,
        attempt=trace.attempt,
    )


def _persist(
    session: Session,
    *,
    target: Job,
    parse: JobParseOutcome,
    analysis: JobAnalysisOutcome,
) -> JobAnalysis:
    """Store the analysis and its rows as a new version."""
    next_version = (
        session.execute(
            select(func.coalesce(func.max(JobAnalysis.version), 0)).where(
                JobAnalysis.job_id == target.id
            )
        ).scalar_one()
        + 1
    )

    validated = analysis.validated
    stored = JobAnalysis(
        user_id=target.user_id,
        job_id=target.id,
        version=next_version,
        summary=validated.summary or parse.validated.summary,
        role_family=validated.role_family,
        secondary_role_family=validated.secondary_role_family,
        role_family_confidence=validated.role_family_confidence,
        role_family_reasoning=validated.role_family_reasoning,
        seniority=validated.seniority,
        seniority_confidence=validated.seniority_confidence,
        seniority_reasoning=validated.seniority_reasoning,
        domain=validated.domain,
        years_experience_min=parse.validated.years_experience_min,
        years_experience_max=parse.validated.years_experience_max,
        provider=parse.provider,
        model=parse.model,
        parse_prompt_version=parse.prompt_version,
        analysis_prompt_version=analysis.prompt_version,
        input_hash=parse.input_hash,
        source_content_hash=analysis_source_hash(target.description),
        payload={"parse": parse.raw_payload, "analysis": analysis.raw_payload},
        warnings=[*parse.warnings, *analysis.warnings],
        analyzed_at=dt.datetime.now(tz=dt.UTC),
    )
    session.add(stored)
    session.flush()

    _persist_requirements(session, target=target, analysis=stored, parse=parse)

    for draft in parse.validated.responsibilities:
        session.add(
            JobResponsibility(
                user_id=target.user_id,
                analysis_id=stored.id,
                job_id=target.id,
                text=draft.text,
                source_text=draft.source_text,
                confidence=draft.confidence,
                source_order=draft.source_order,
            )
        )

    session.flush()

    logger.info(
        "Stored job analysis",
        extra={
            "job_id": str(target.id),
            "version": next_version,
            "requirements": len(parse.validated.requirements),
            "responsibilities": len(parse.validated.responsibilities),
        },
    )
    return stored


def _persist_requirements(
    session: Session,
    *,
    target: Job,
    analysis: JobAnalysis,
    parse: JobParseOutcome,
) -> None:
    """Store requirements, resolving named technologies in one batch."""
    names = [
        draft.skill_name for draft in parse.validated.requirements if draft.skill_name is not None
    ]
    resolved = resolve_known_skills(session, names) if names else {}

    for draft in parse.validated.requirements:
        skill = resolved.get(draft.skill_name) if draft.skill_name else None
        session.add(
            JobRequirement(
                user_id=target.user_id,
                analysis_id=analysis.id,
                job_id=target.id,
                requirement_type=draft.requirement_type,
                importance=draft.importance,
                explicitness=draft.explicitness,
                source_text=draft.source_text,
                normalized_text=draft.normalized_text,
                confidence=draft.confidence,
                source_order=draft.source_order,
                skill_id=skill.id if skill else None,
                skill_name=draft.skill_name,
                years_min=draft.years_min,
            )
        )
