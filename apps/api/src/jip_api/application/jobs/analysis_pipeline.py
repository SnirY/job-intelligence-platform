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
from dataclasses import dataclass, replace

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
from jip_api.application.jobs.analysis_validation import RequirementDraft
from jip_api.application.jobs.requirement_skills import resolve_known_skills
from jip_api.application.processing import jobs as jobs_uc
from jip_api.domain.ai.models import AIRun, AIRunStatus
from jip_api.domain.jobs.analysis import (
    JobAnalysis,
    JobRequirement,
    JobResponsibility,
    RequirementImportance,
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
    _fill_blank_location(target, parse)

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

    # Owned here rather than inside the service so the attempts survive a
    # failure. DEV-016: a wholly failed operation used to leave no ai_runs row
    # at all, so the only evidence of what happened was a generic message on
    # processing_jobs — which is exactly the case you most need the trace for.
    traces: list[AIRunTrace] = []
    try:
        outcome = service.parse(text, source_note=_source_note(target), traces=traces)
    except AIError:
        _persist_traces(session, target, traces)
        _mark_analysis_failed(session, target)
        raise

    _persist_traces(session, target, outcome.traces)
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

    traces: list[AIRunTrace] = []
    try:
        outcome = service.analyze(text, parse.validated, traces=traces)
    except AIError:
        _persist_traces(session, target, traces)
        _mark_analysis_failed(session, target)
        raise

    _persist_traces(session, target, outcome.traces)
    return outcome


def _persist_traces(session: Session, target: Job, traces: list[AIRunTrace]) -> None:
    """Write one ``ai_runs`` row per attempt, on both paths.

    Called from the ``except`` as well as the success path, which is the whole
    point of DEV-016: the failed operation is the one whose cost and cause
    nobody can reconstruct afterwards.

    **Flushes rather than commits, and the order it is called in matters.** On
    the failure path it must run *before* ``_mark_analysis_failed``, whose
    commit is what actually persists these rows — the worker's handler opens
    with ``session.rollback()``, so anything merely flushed by the time the
    exception reaches it is discarded.
    """
    for trace in traces:
        session.add(_ai_run(trace, user_id=target.user_id, job_id=target.id))
    session.flush()


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


def _fill_blank_location(target: Job, parse: JobParseOutcome) -> None:
    """Copy the read location onto the job when the job has none.

    The parse has extracted a location all along and nothing ever used it. It
    sat in `job_analyses.payload` while `jobs.location` stayed null on every
    real posting, so the jobs list, its location filter, and any comparison
    against a stated preference all saw an empty column — a field that looked
    unfilled rather than discarded.

    Only fills a blank. A location the user typed is theirs and outranks a
    reading of the posting, and re-analysing must not overwrite a correction
    they made after the first pass.
    """
    if target.location or not parse.result.location:
        return
    target.location = parse.result.location[:200]


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


STRENGTH_ORDER: dict[RequirementImportance, int] = {
    RequirementImportance.CORE: 4,
    RequirementImportance.REQUIRED: 3,
    RequirementImportance.UNKNOWN: 2,
    RequirementImportance.PREFERRED: 1,
    RequirementImportance.OPTIONAL: 0,
}
"""Which importance wins when one skill is asked for twice.

Must agree with ``IMPORTANCE_WEIGHTS`` in the matching rules — a strength
ordering that disagrees with the scoring weights would resolve a duplicate in
favour of the one that counts for less. A test asserts they rank identically
rather than a comment asking someone to remember.
"""


def _named_in_title(needle: str, title: str) -> bool:
    """Whether ``needle`` appears in ``title`` as a whole word.

    Boundary-checked rather than a plain substring test, so "Go" does not match
    "Google". Not a regex, because skill names contain characters a pattern
    would have to escape — C++, C#, .NET, F#.
    """
    hay = title.casefold()
    needle = needle.casefold().strip()
    if not needle:
        return False

    found = hay.find(needle)
    while found != -1:
        before = hay[found - 1] if found > 0 else " "
        end = found + len(needle)
        after = hay[end] if end < len(hay) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        found = hay.find(needle, found + 1)
    return False


def _promote_title_skills(drafts: list[RequirementDraft], title: str) -> list[RequirementDraft]:
    """A requirement the job title names is CORE, whatever the model said.

    DEV-028. Across 31 requirements from two analyses of a real posting the
    model assigned CORE **zero** times. The prompt asked it to "use sparingly",
    which is a statement about frequency and not a test it could apply, so it
    applied the only reading that always satisfies the instruction.

    Two mechanisms depend on CORE and both were therefore dead: the 3.00
    weight, the highest there is, and ``BLOCKER_CAP``, which
    ``rules.can_block`` gates on CORE alone. Neither had ever applied to a real
    match.

    The prompt now gives a test instead of a frequency. This is the part that
    does not depend on the model following it: a posting titled *Junior
    Software Engineer C++* is defined by C++, and a candidate without it is not
    a candidate for that job — which is exactly the case ``BLOCKER_CAP``
    exists to catch.

    Only promotes. A requirement the model already called CORE stays CORE, and
    nothing is ever moved down here.
    """
    if not title.strip():
        return drafts

    promoted: list[RequirementDraft] = []
    for draft in drafts:
        name = draft.skill_name
        if (
            name
            and draft.importance is not RequirementImportance.CORE
            and _named_in_title(name, title)
        ):
            promoted.append(replace(draft, importance=RequirementImportance.CORE))
            continue
        promoted.append(draft)

    return promoted


def _strongest_per_skill(
    drafts: list[tuple[RequirementDraft, uuid.UUID | None]],
) -> list[RequirementDraft]:
    """Drop repeats of the same catalogued skill, keeping the strongest.

    DEV-025. A posting that names a technology twice — once in its opening
    prose and once in its requirement list, at different strengths — produces
    two requirements for it. Both are faithful readings of the text taken
    alone, and nothing reconciled them.

    They are duplicates in the sense that matters: the matcher resolves both
    against the same profile skill and reaches the same verdict for both, so
    keeping the pair counts one piece of evidence twice, on both sides. The
    network-analytics posting's "C++ expertise on Linux" and "Linux environment, an
    Advantage" scored MATCH twice, adding 2.50 of weight for one skill against
    C++'s 2.00 in a C++ role.

    Requirements with no resolved skill are never merged. Two unmatched phrases
    that happen to read alike are not known to be the same thing, and the
    matcher treats them separately too.
    """
    strongest: dict[uuid.UUID, int] = {}
    for draft, skill_id in drafts:
        if skill_id is None:
            continue
        rank = STRENGTH_ORDER[draft.importance]
        if skill_id not in strongest or rank > strongest[skill_id]:
            strongest[skill_id] = rank

    kept: list[RequirementDraft] = []
    seen: set[uuid.UUID] = set()
    for draft, skill_id in drafts:
        if skill_id is None:
            kept.append(draft)
            continue
        # Ties go to the earlier mention: the drafts arrive in the posting's
        # own order, and the first time it asks for something is the one whose
        # wording the user will recognise.
        if skill_id in seen or STRENGTH_ORDER[draft.importance] < strongest[skill_id]:
            continue
        seen.add(skill_id)
        kept.append(draft)

    return kept


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

    # Promote before merging, so a mention the title makes core wins the merge
    # rather than being dropped in favour of whichever came first.
    promoted = _promote_title_skills(parse.validated.requirements, target.title)

    paired: list[tuple[RequirementDraft, uuid.UUID | None]] = []
    for draft in promoted:
        resolved_skill = resolved.get(draft.skill_name) if draft.skill_name else None
        paired.append((draft, resolved_skill.id if resolved_skill else None))

    kept = _strongest_per_skill(paired)

    if len(kept) < len(paired):
        logger.info(
            "Merged repeated skills in a reading",
            extra={
                "job_id": str(target.id),
                "dropped": len(paired) - len(kept),
                "kept_count": len(kept),
            },
        )

    for draft in kept:
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
