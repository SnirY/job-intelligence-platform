"""Assemble the dashboard from what the other phases already produced.

``docs/10-api-contracts.md``: *"The endpoint aggregates existing domain
outputs. It must not duplicate business logic."* That is the whole design
constraint, and it is load-bearing rather than tidiness — a dashboard that
recomputes a score, or decides for itself which application stages count as
live, becomes a second implementation of a rule that has to agree with the
first, and the one that drifts is the one on the front page.

So: the pipeline groups by ``ApplicationStatus`` and asks the enum which stages
are live. Opportunities read ``job_matches.overall_score`` as stored, and
staleness comes from ``assess_staleness``, the same call the match panel makes.
Skill gaps count requirement rows against ``user_skills`` by ``skill_id`` — the
canonical id both sides already resolved to, never by comparing names.

Nothing here scores, weights, or predicts. Where a number would have to be
invented, the field is null and the frontend says why.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from jip_api.application.dashboard.actions import (
    GOOD_MATCH_SCORE,
    ActionKind,
    NextAction,
    is_stale_application,
    rank,
)
from jip_api.application.matching.queries import assess_staleness
from jip_api.application.ownership import owned
from jip_api.domain.applications.models import Application, ApplicationEvent, ApplicationStatus
from jip_api.domain.career.skills import Skill, UserSkill
from jip_api.domain.jobs.analysis import JobRequirement
from jip_api.domain.jobs.models import Job, JobProcessingStatus
from jip_api.domain.matching.models import JobMatch

TOP_OPPORTUNITIES = 5
"""Enough to choose between, few enough to read."""

RECENT_ACTIVITY = 8
SKILL_GAPS = 6


@dataclass(frozen=True, slots=True)
class CurrentState:
    """The one-line answer to "where am I".

    Counts only. Every one of these is a row the user can go and look at, which
    is what keeps the top of the dashboard from being a mood.
    """

    jobs_saved: int = 0
    jobs_analysed: int = 0
    jobs_matched: int = 0
    applications_live: int = 0
    profile_skills: int = 0


@dataclass(frozen=True, slots=True)
class PipelineStage:
    status: ApplicationStatus
    count: int
    before_applying: bool
    """Preparation rather than a real outcome — the funnel divides here."""


@dataclass(frozen=True, slots=True)
class Opportunity:
    job_id: uuid.UUID
    title: str
    company: str | None
    score: int | None
    alignment_label: str | None
    is_stale: bool
    has_application: bool


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    at: dt.datetime
    kind: str
    subject: str
    job_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SkillGap:
    """A skill saved jobs ask for and the profile does not claim."""

    skill_id: uuid.UUID
    name: str
    asked_by_jobs: int


@dataclass(frozen=True, slots=True)
class DashboardView:
    state: CurrentState = field(default_factory=CurrentState)
    pipeline: list[PipelineStage] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    actions: list[NextAction] = field(default_factory=list)
    activity: list[ActivityEntry] = field(default_factory=list)
    skill_gaps: list[SkillGap] = field(default_factory=list)


def build_dashboard(
    session: Session, user_id: uuid.UUID, *, now: dt.datetime | None = None
) -> DashboardView:
    """Everything the home screen shows, in one pass.

    ``now`` is injectable so the follow-up rule can be tested without waiting
    two weeks.
    """
    moment = now or dt.datetime.now(tz=dt.UTC)

    jobs = list(session.scalars(_live_jobs(user_id)))
    applications = list(session.scalars(owned(Application, user_id)))
    matches = _latest_matches(session, user_id)
    skills_held = set(
        session.scalars(select(UserSkill.skill_id).where(UserSkill.user_id == user_id))
    )

    return DashboardView(
        state=_state(jobs, applications, matches, skills_held),
        pipeline=_pipeline(applications),
        opportunities=_opportunities(session, user_id, jobs, matches, applications),
        actions=_actions(session, user_id, jobs, matches, applications, skills_held, moment),
        activity=_activity(session, user_id, jobs),
        skill_gaps=_skill_gaps(session, user_id, skills_held),
    )


def _live_jobs(user_id: uuid.UUID) -> Select[tuple[Job]]:
    """Archived jobs are excluded everywhere on this screen.

    Archiving is the user saying "stop showing me this", and a dashboard is
    entirely a list of things being shown.
    """
    return owned(Job, user_id).where(Job.archived_at.is_(None)).order_by(Job.created_at.desc())


def _latest_matches(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, JobMatch]:
    """The newest match per job.

    Recalculation appends versions, so a job with three matches must count
    once, at its latest — reading them all would weight a job by how often it
    was recalculated.
    """
    newest: dict[uuid.UUID, JobMatch] = {}
    for match in session.scalars(owned(JobMatch, user_id).order_by(JobMatch.version)):
        newest[match.job_id] = match
    return newest


def _state(
    jobs: list[Job],
    applications: list[Application],
    matches: dict[uuid.UUID, JobMatch],
    skills_held: set[uuid.UUID],
) -> CurrentState:
    return CurrentState(
        jobs_saved=len(jobs),
        jobs_analysed=sum(1 for job in jobs if job.status is JobProcessingStatus.ANALYZED),
        jobs_matched=len(matches),
        applications_live=sum(1 for app in applications if app.status.is_active),
        profile_skills=len(skills_held),
    )


def _pipeline(applications: list[Application]) -> list[PipelineStage]:
    """Applications by stage, in lifecycle order, empty stages omitted.

    Order comes from the declaration order of ``ApplicationStatus``, which is
    the lifecycle — writing the sequence out again here is exactly the
    duplication the contract forbids.

    Empty stages are dropped rather than shown as zeros: fourteen columns of
    which two have anything in them reads as a system with thirteen problems.
    """
    counts: dict[ApplicationStatus, int] = {}
    for application in applications:
        counts[application.status] = counts.get(application.status, 0) + 1

    return [
        PipelineStage(
            status=status,
            count=counts[status],
            before_applying=status.is_before_applying,
        )
        for status in ApplicationStatus
        if counts.get(status)
    ]


def _opportunities(
    session: Session,
    user_id: uuid.UUID,
    jobs: list[Job],
    matches: dict[uuid.UUID, JobMatch],
    applications: list[Application],
) -> list[Opportunity]:
    """The best-scoring matched jobs, worst-case first for staleness.

    A job with no score is left out entirely rather than sorted as a zero. It
    has not been measured, and the whole section is a ranking — an unmeasured
    job placed last would read as a verdict.
    """
    applied_to = {application.job_id for application in applications}
    by_id = {job.id: job for job in jobs}

    scored: list[tuple[int, Opportunity]] = []
    for job_id, match in matches.items():
        job = by_id.get(job_id)
        if job is None or match.overall_score is None:
            continue

        staleness = assess_staleness(
            session,
            user_id,
            match,
            current_analysis_version=match.analysis_version,
        )
        scored.append(
            (
                match.overall_score,
                Opportunity(
                    job_id=job.id,
                    title=job.title,
                    company=job.company,
                    score=match.overall_score,
                    alignment_label=match.alignment_label,
                    is_stale=staleness.is_stale,
                    has_application=job.id in applied_to,
                ),
            )
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [opportunity for _, opportunity in scored[:TOP_OPPORTUNITIES]]


def _actions(
    session: Session,
    user_id: uuid.UUID,
    jobs: list[Job],
    matches: dict[uuid.UUID, JobMatch],
    applications: list[Application],
    skills_held: set[uuid.UUID],
    now: dt.datetime,
) -> list[NextAction]:
    """Every rule fires, then :func:`rank` keeps the top few.

    Collecting all of them and cutting afterwards, rather than stopping early,
    so priority is decided in one place by ``ACTION_ORDER`` instead of by the
    order the checks happen to be written in.
    """
    found: list[NextAction] = []

    if not skills_held:
        found.append(
            NextAction(
                kind=ActionKind.BUILD_PROFILE,
                subject="Your career profile",
                reason=(
                    "There are no skills on your profile yet, so nothing can be matched "
                    "against a posting."
                ),
            )
        )

    applied_to = {application.job_id: application for application in applications}

    for job in jobs:
        if job.status is JobProcessingStatus.ANALYSIS_FAILED:
            found.append(
                NextAction(
                    kind=ActionKind.RETRY_ANALYSIS,
                    subject=job.title,
                    reason="Reading this posting did not work. Your description is unchanged.",
                    job_id=job.id,
                )
            )
            continue

        if job.status is JobProcessingStatus.RAW:
            found.append(
                NextAction(
                    kind=ActionKind.ANALYSE_JOB,
                    subject=job.title,
                    reason="Saved, and not yet read into requirements.",
                    job_id=job.id,
                )
            )
            continue

        if job.status is not JobProcessingStatus.ANALYZED:
            continue

        match = matches.get(job.id)
        if match is None:
            found.append(
                NextAction(
                    kind=ActionKind.MATCH_JOB,
                    subject=job.title,
                    reason="Read, and never compared against your profile.",
                    job_id=job.id,
                )
            )
            continue

        staleness = assess_staleness(
            session, user_id, match, current_analysis_version=match.analysis_version
        )
        if staleness.is_stale:
            found.append(
                NextAction(
                    kind=ActionKind.REFRESH_MATCH,
                    subject=job.title,
                    reason=staleness.reasons[0],
                    job_id=job.id,
                )
            )
            continue

        if (
            match.overall_score is not None
            and match.overall_score >= GOOD_MATCH_SCORE
            and job.id not in applied_to
        ):
            found.append(
                NextAction(
                    kind=ActionKind.PREPARE_APPLICATION,
                    subject=job.title,
                    reason=(
                        f"{match.overall_score}% alignment, and no application started. "
                        f"{match.alignment_label}."
                    ),
                    job_id=job.id,
                )
            )

    titles = {job.id: job.title for job in jobs}
    for application in applications:
        if application.status.is_terminal or application.status.is_before_applying:
            continue
        if is_stale_application(application.applied_at, now):
            found.append(
                NextAction(
                    kind=ActionKind.FOLLOW_UP,
                    subject=titles.get(application.job_id, "An application"),
                    reason="Sent more than two weeks ago with nothing recorded since.",
                    job_id=application.job_id,
                    application_id=application.id,
                )
            )

    return rank(found)


def _activity(session: Session, user_id: uuid.UUID, jobs: list[Job]) -> list[ActivityEntry]:
    """Recent application events and job saves, newest first.

    Application events are the record Phase 8 writes on every status change, so
    this reads history rather than reconstructing it from current state.
    """
    titles = {job.id: job.title for job in jobs}
    entries: list[ActivityEntry] = []

    events = session.scalars(
        owned(ApplicationEvent, user_id)
        .order_by(ApplicationEvent.created_at.desc())
        .limit(RECENT_ACTIVITY)
    )
    application_jobs = {
        application.id: application.job_id
        for application in session.scalars(owned(Application, user_id))
    }
    for event in events:
        job_id = application_jobs.get(event.application_id)
        entries.append(
            ActivityEntry(
                at=event.created_at,
                kind=str(event.event_type),
                subject=titles.get(job_id, "An application") if job_id else "An application",
                job_id=job_id,
            )
        )

    for job in jobs[:RECENT_ACTIVITY]:
        entries.append(
            ActivityEntry(at=job.created_at, kind="JOB_SAVED", subject=job.title, job_id=job.id)
        )

    entries.sort(key=lambda entry: _aware(entry.at), reverse=True)
    return entries[:RECENT_ACTIVITY]


def _skill_gaps(
    session: Session, user_id: uuid.UUID, skills_held: set[uuid.UUID]
) -> list[SkillGap]:
    """Skills the user's own saved jobs ask for and the profile does not claim.

    Counted by distinct job, not by requirement row: a posting that names Linux
    twice asks for it once, and DEV-025 is only the deduplication that reached
    the reading. Counting rows here would reintroduce the same double count in
    a different column.

    Joined on ``skill_id``, so this compares catalogued skills rather than
    strings — "Postgres" in a posting and "PostgreSQL" on a profile are the
    same skill, and a name comparison would report a gap that is not there.
    """
    counts = (
        select(
            JobRequirement.skill_id,
            Skill.canonical_name,
            func.count(func.distinct(JobRequirement.job_id)).label("jobs"),
        )
        .join(Skill, Skill.id == JobRequirement.skill_id)
        .join(Job, Job.id == JobRequirement.job_id)
        .where(
            JobRequirement.user_id == user_id,
            JobRequirement.skill_id.is_not(None),
            Job.archived_at.is_(None),
        )
        .group_by(JobRequirement.skill_id, Skill.canonical_name)
        .order_by(func.count(func.distinct(JobRequirement.job_id)).desc(), Skill.canonical_name)
    )

    gaps: list[SkillGap] = []
    for skill_id, name, jobs in session.execute(counts):
        if skill_id in skills_held:
            continue
        gaps.append(SkillGap(skill_id=skill_id, name=name, asked_by_jobs=jobs))
        if len(gaps) == SKILL_GAPS:
            break
    return gaps


def _aware(value: dt.datetime) -> dt.datetime:
    """Treat a naive timestamp as UTC, so sorting cannot raise.

    Same reason as ``reaper._aware``: the columns are timezone-aware but some
    drivers hand back naive values, and comparing the two raises rather than
    ordering wrongly.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
