"""Role analysis, the application funnel, and resume analytics.

The three ``docs/09`` names for this phase that skill demand does not cover.
All three divide one count by another, which is why they share a module and a
rule: **a ratio is withheld until there is enough to divide by.**

``docs/07`` states that rule twice — "do not produce strong conclusions from
tiny samples", "use explicit minimum-data thresholds" — and states it once more
for this section specifically: *present as associations, not causal claims.* A
resume with one application and one interview did not cause anything.

DEV-026 delayed role analysis on the belief that alignment scores inherit
unstable importance weights. Two five-reading measurements found otherwise:
keyed by resolved skill, importance moved once in twenty-four labels across two
postings. What varies is which requirements get *extracted* and how they are
worded — and that varies between alternative readings of one posting, while in
production a posting is read once. A score is stable for the reading it came
from; across jobs each read once, the variance behaves as measurement error on
each point rather than as drift.

Which leaves sample size, exactly as for the funnel. So all three ship together,
under one threshold, rather than one of them waiting on a calibration that
turned out to be measuring something else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.ownership import owned
from jip_api.domain.applications.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
)
from jip_api.domain.jobs.analysis import JobAnalysis, RoleFamily
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import JobMatch
from jip_api.domain.resumes.models import ResumeVersion

MINIMUM_JOBS_PER_ROLE = 3
"""Below this, a role family's average alignment is one or two jobs wearing a
percentage sign.

Lower than the five demand uses, because this is an average of a measured
quantity rather than a frequency: three points say something a single point
cannot, where three postings say very little about how often a skill appears.
Both numbers are reasoned rather than derived, and both are here to be argued
with.
"""

MINIMUM_APPLICATIONS = 5
"""Below this, no conversion rate is reported at all.

One application that reached an interview is a 100% interview rate, and there
is no honest way to display that. The stage *counts* are still shown — those
are facts — but nothing is divided.
"""


@dataclass(frozen=True, slots=True)
class RoleInsight:
    """One role family, and how the user's jobs in it have gone."""

    role_family: RoleFamily
    jobs: int
    matched: int

    average_alignment: int | None
    """Null below the threshold, and null when nothing in the family was
    scored. Never zero — that would be a claim about fit."""

    applications: int


@dataclass(frozen=True, slots=True)
class RoleReport:
    roles: list[RoleInsight] = field(default_factory=list)
    minimum_jobs: int = MINIMUM_JOBS_PER_ROLE


@dataclass(frozen=True, slots=True)
class FunnelStage:
    """One step of the funnel from ``docs/07``, as a count.

    ``reached`` counts applications that got *at least* this far, which is what
    makes a funnel a funnel: an application now at OFFER passed through APPLIED,
    and a stage counting only its current occupants would show a pipeline
    draining rather than progressing.
    """

    key: str
    label: str
    reached: int


@dataclass(frozen=True, slots=True)
class FunnelReport:
    applications: int
    stages: list[FunnelStage] = field(default_factory=list)
    minimum_applications: int = MINIMUM_APPLICATIONS

    @property
    def rates_are_meaningful(self) -> bool:
        return self.applications >= MINIMUM_APPLICATIONS


@dataclass(frozen=True, slots=True)
class ResumeInsight:
    """One resume version and what happened after it was sent.

    Associations only. ``docs/07`` is explicit that resume analytics are
    presented as associations rather than causal claims, and with these sample
    sizes the word "because" is never available.
    """

    resume_version_id: uuid.UUID
    label: str
    sent: int
    reached_interview: int
    offers: int


# The funnel from `docs/07`, in order. Each stage names the statuses that count
# as having reached it — a status at or beyond the step.
_FUNNEL: tuple[tuple[str, str, frozenset[ApplicationStatus]], ...] = (
    (
        "applied",
        "Applied",
        frozenset(
            {
                ApplicationStatus.APPLIED,
                ApplicationStatus.HR_SCREEN,
                ApplicationStatus.TECHNICAL_INTERVIEW,
                ApplicationStatus.FINAL_INTERVIEW,
                ApplicationStatus.OFFER,
            }
        ),
    ),
    (
        "responded",
        "Got a response",
        frozenset(
            {
                ApplicationStatus.HR_SCREEN,
                ApplicationStatus.TECHNICAL_INTERVIEW,
                ApplicationStatus.FINAL_INTERVIEW,
                ApplicationStatus.OFFER,
            }
        ),
    ),
    (
        "interviewed",
        "Interviewed",
        frozenset(
            {
                ApplicationStatus.TECHNICAL_INTERVIEW,
                ApplicationStatus.FINAL_INTERVIEW,
                ApplicationStatus.OFFER,
            }
        ),
    ),
    ("offered", "Offer", frozenset({ApplicationStatus.OFFER})),
)

_INTERVIEW_STATUSES = frozenset(
    {
        ApplicationStatus.TECHNICAL_INTERVIEW,
        ApplicationStatus.FINAL_INTERVIEW,
        ApplicationStatus.OFFER,
    }
)


def build_roles(session: Session, user_id: uuid.UUID) -> RoleReport:
    """Average alignment per role family, over the user's own jobs.

    The role family comes from the newest analysis of each job, and the
    alignment from the newest match — both "newest", because versions
    accumulate and reading them all would weight a job by how often it was
    re-run.
    """
    families: dict[RoleFamily, list[int | None]] = {}
    applications_by_job = _applications_by_job(session, user_id)
    applied: dict[RoleFamily, int] = {}

    scores = _latest_scores(session, user_id)

    rows = session.execute(
        select(JobAnalysis.job_id, JobAnalysis.version, JobAnalysis.role_family)
        .join(Job, Job.id == JobAnalysis.job_id)
        .where(
            JobAnalysis.user_id == user_id,
            Job.archived_at.is_(None),
            JobAnalysis.role_family.is_not(None),
        )
    ).all()

    newest: dict[uuid.UUID, tuple[int, RoleFamily]] = {}
    for job_id, version, family in rows:
        current = newest.get(job_id)
        if current is None or version > current[0]:
            newest[job_id] = (version, family)

    for job_id, (_, family) in newest.items():
        families.setdefault(family, []).append(scores.get(job_id))
        if job_id in applications_by_job:
            applied[family] = applied.get(family, 0) + 1

    insights: list[RoleInsight] = []
    for family, values in families.items():
        measured = [value for value in values if value is not None]
        insights.append(
            RoleInsight(
                role_family=family,
                jobs=len(values),
                matched=len(measured),
                # Two conditions, and both have to hold. Enough jobs in the
                # family, and enough of them actually scored — a family of four
                # jobs with one match is still one data point.
                average_alignment=(
                    round(sum(measured) / len(measured))
                    if measured and len(values) >= MINIMUM_JOBS_PER_ROLE
                    else None
                ),
                applications=applied.get(family, 0),
            )
        )

    insights.sort(key=lambda insight: (-insight.jobs, str(insight.role_family)))
    return RoleReport(roles=insights)


def build_funnel(session: Session, user_id: uuid.UUID) -> FunnelReport:
    """How far the user's applications have got, as counts.

    Rates are the caller's business, and only above the threshold. This returns
    the numerator and denominator and refuses to divide them prematurely.
    """
    applications = list(session.scalars(owned(Application, user_id)))
    reached = _stages_reached(session, user_id, applications)

    return FunnelReport(
        applications=len(applications),
        stages=[
            FunnelStage(
                key=key,
                label=label,
                reached=sum(1 for stages in reached.values() if stages & statuses),
            )
            for key, label, statuses in _FUNNEL
        ],
    )


def build_resume_performance(session: Session, user_id: uuid.UUID) -> list[ResumeInsight]:
    """What happened after each resume version was sent.

    Only versions actually attached to an application appear. A resume nobody
    sent has no performance, and listing it at zero would read as a verdict on
    the document rather than on the absence of data.
    """
    applications = [
        application
        for application in session.scalars(owned(Application, user_id))
        if application.resume_version_id is not None
    ]
    if not applications:
        return []

    version_ids = {a.resume_version_id for a in applications if a.resume_version_id}
    versions = {
        version.id: version
        for version in session.scalars(
            owned(ResumeVersion, user_id).where(ResumeVersion.id.in_(version_ids))
        )
    }

    reached = _stages_reached(session, user_id, applications)
    by_version: dict[uuid.UUID, list[set[ApplicationStatus]]] = {}
    for application in applications:
        if application.resume_version_id:
            by_version.setdefault(application.resume_version_id, []).append(
                reached.get(application.id, {application.status})
            )

    insights: list[ResumeInsight] = []
    for version_id, per_application in by_version.items():
        version = versions.get(version_id)
        insights.append(
            ResumeInsight(
                resume_version_id=version_id,
                label=f"Version {version.version}" if version else "A resume version",
                sent=len(per_application),
                reached_interview=sum(
                    1 for stages in per_application if stages & _INTERVIEW_STATUSES
                ),
                offers=sum(1 for stages in per_application if ApplicationStatus.OFFER in stages),
            )
        )

    insights.sort(key=lambda insight: (-insight.sent, insight.label))
    return insights


def _stages_reached(
    session: Session, user_id: uuid.UUID, applications: list[Application]
) -> dict[uuid.UUID, set[ApplicationStatus]]:
    """Every stage each application passed through, from its own history.

    **Current status is not the answer.** An application rejected after a
    technical interview sits at REJECTED, and a funnel reading current statuses
    would report that it never interviewed — turning every rejection into a
    candidate who never applied. In a real search most applications end in a
    terminal status, so that version of the funnel would be wrong for the
    majority of its input and wrong in the flattering direction.

    Phase 8 wrote `application_events` for exactly this: every status change
    recorded with what it moved between, append-only, and never rewritten. The
    stages an application reached are the `to_status` values in its history,
    plus its current one for anything created before the first move.
    """
    reached: dict[uuid.UUID, set[ApplicationStatus]] = {
        application.id: {application.status} for application in applications
    }

    rows = session.execute(
        select(ApplicationEvent.application_id, ApplicationEvent.to_status).where(
            ApplicationEvent.user_id == user_id,
            ApplicationEvent.to_status.is_not(None),
        )
    ).all()

    for application_id, status in rows:
        if application_id in reached:
            reached[application_id].add(status)

    return reached


def _applications_by_job(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, Application]:
    return {
        application.job_id: application
        for application in session.scalars(owned(Application, user_id))
    }


def _latest_scores(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, int | None]:
    """The newest match's score per job."""
    newest: dict[uuid.UUID, tuple[int, int | None]] = {}
    for match in session.scalars(owned(JobMatch, user_id)):
        current = newest.get(match.job_id)
        if current is None or match.version > current[0]:
            newest[match.job_id] = (match.version, match.overall_score)
    return {job_id: score for job_id, (_, score) in newest.items()}
