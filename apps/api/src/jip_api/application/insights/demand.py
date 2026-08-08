"""What the user's own saved jobs keep asking for.

Everything on this screen is a **count**, and that is a decision rather than a
simplification. DEV-026 measured the same posting read twice and found the
requirements that name a technology stable across both runs, while the ones
describing a quality in prose moved — three of three, half their weight, on
unchanged input.

So Phase 10 is built on the half that holds still:

- demand counts distinct jobs per canonical ``skill_id``, which is a fact about
  what the user saved;
- gap state comes from the profile, not from a match;
- nothing is averaged, weighted, or scored.

Deliberately absent, and belonging to the same phase: role analysis, which
``docs/09`` describes as average alignment per role family. That is an average
of scores, scores are built from importance weights, and importance is the
field DEV-026 is about. It waits for calibration rather than shipping a number
that moves when nothing has changed.

Also absent: the application funnel. Its inputs are stable — statuses are typed
by the user, not inferred — but ``docs/07`` requires explicit minimum-data
thresholds, and a funnel is the clearest case of a figure that means nothing
until there are enough rows to divide by.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.insights.gaps import GAP_SEVERITY, GapState, gap_state, is_gap
from jip_api.application.matching.evidence import load_profile_snapshot
from jip_api.domain.career.skills import Skill, normalize_skill_name
from jip_api.domain.jobs.analysis import (
    JobAnalysis,
    JobRequirement,
    RequirementImportance,
)
from jip_api.domain.jobs.models import Job

MINIMUM_JOBS = 5
"""Below this, figures are shown and conclusions are not.

``docs/07`` asks for explicit minimum-data thresholds and does not set one.
Five is the smallest number where a "3 of 5 postings" reads as a pattern rather
than as a coincidence, and it is stated here rather than inlined so it can be
argued with.

The figures themselves are never hidden. A user with two saved jobs is entitled
to see what those two asked for — what they are not entitled to is a sentence
implying it generalises.
"""

TOP_SKILLS = 12
"""How many rows "What comes up most" shows. A presentation cap, nothing more.

It applies to the demand list alone. It used to be applied inside
``build_demand``, which meant ``build_gaps`` — deriving from the same report —
inherited a cut made by a rule it does not share: gaps are ordered by severity,
and the cut was by frequency and then, within a frequency tier, alphabetically
by name. Three real gaps were invisible on the development account because
their names began with S, T and V (DEV-040).

So the report now carries everything and the cap is applied where the list is
rendered, beside the total, so a truncated list says how much it is hiding.
"""


@dataclass(frozen=True, slots=True)
class SkillDemand:
    """One skill, and how much of the user's own market asks for it.

    Carries the four things ``docs/07`` names under *Skill demand*: the number
    of relevant jobs, the percentage, the importance breakdown, and the role
    distribution.
    """

    key: str
    """Identity across postings.

    The canonical ``skill_id`` when the catalogue knows the skill, and the
    normalised name when it does not. Both are needed: the seeded catalogue
    holds thirty rows and the postings in this account name seventeen skills,
    of which it recognises three. Counting only what resolves would report a
    C++ role as asking for Linux and nothing else.

    The cost is that an uncatalogued skill written two ways in two postings
    counts as two, which is a visible imprecision rather than a silent
    omission — and the normaliser already collapses the common variants.
    """

    skill_id: uuid.UUID | None
    name: str
    catalogued: bool
    """Whether this resolved to the shared catalogue.

    Surfaced rather than hidden, because it is the difference between "two
    postings asked for this" and "two postings used this word"."""

    jobs: int
    share: int
    """Percentage of the user's analysed jobs. Integer — a decimal place would
    imply a precision that a denominator of six does not have."""

    importance: dict[RequirementImportance, int] = field(default_factory=dict)
    role_families: dict[str, int] = field(default_factory=dict)

    state: GapState = GapState.NO_GAP
    held: bool = False


@dataclass(frozen=True, slots=True)
class DemandReport:
    analysed_jobs: int
    """The denominator, carried everywhere so no figure is quoted without it."""

    skills: list[SkillDemand] = field(default_factory=list)

    @property
    def is_above_threshold(self) -> bool:
        return self.analysed_jobs >= MINIMUM_JOBS


def build_demand(session: Session, user_id: uuid.UUID) -> DemandReport:
    """Skill demand across the user's analysed, unarchived jobs.

    Counted per distinct job rather than per requirement row. A posting naming
    Linux twice asks for it once — DEV-025 fixed that in the reading, and
    counting rows here would reintroduce the same double count in a different
    column.
    """
    latest = _latest_analysis_ids(session, user_id)
    if not latest:
        return DemandReport(analysed_jobs=0)

    snapshot = load_profile_snapshot(session, user_id)
    held_by_id = {skill.skill_id: skill for skill in snapshot.skills}

    rows = session.execute(
        select(
            JobRequirement.skill_id,
            Skill.canonical_name,
            JobRequirement.skill_name,
            JobRequirement.importance,
            JobAnalysis.role_family,
            JobRequirement.job_id,
        )
        .outerjoin(Skill, Skill.id == JobRequirement.skill_id)
        .join(JobAnalysis, JobAnalysis.id == JobRequirement.analysis_id)
        .where(
            JobRequirement.user_id == user_id,
            JobRequirement.skill_name.is_not(None),
            # The newest reading only. Requirements are written per analysis
            # version and every version is kept, so one job read three times
            # holds three full sets — and counting all of them would report a
            # posting three times for having been re-read three times.
            JobRequirement.analysis_id.in_(latest),
        )
    ).all()

    jobs_per_skill: dict[str, set[uuid.UUID]] = {}
    identities: dict[str, tuple[uuid.UUID | None, str]] = {}
    importance: dict[str, dict[RequirementImportance, int]] = {}
    families: dict[str, dict[str, int]] = {}

    for skill_id, canonical, raw_name, level, family, job_id in rows:
        key = str(skill_id) if skill_id else normalize_skill_name(raw_name)
        identities.setdefault(key, (skill_id, canonical or raw_name))
        jobs_per_skill.setdefault(key, set()).add(job_id)

        seen = importance.setdefault(key, {})
        seen[level] = seen.get(level, 0) + 1
        if family:
            by_family = families.setdefault(key, {})
            by_family[str(family)] = by_family.get(str(family), 0) + 1

    total = len(latest)
    demands = []
    for key, job_ids in jobs_per_skill.items():
        skill_id, name = identities[key]
        # Resolved skills are looked up by id; the rest by normalised name,
        # which is the same key the matcher falls back to. A profile listing
        # "C++" and a posting asking for "C++" have to meet somewhere, and the
        # catalogue is not that place for fourteen of seventeen skills here.
        evidence = held_by_id.get(skill_id) if skill_id else snapshot.skills_by_normalized.get(key)
        demands.append(
            SkillDemand(
                key=key,
                skill_id=skill_id,
                name=name,
                catalogued=skill_id is not None,
                jobs=len(job_ids),
                share=round(len(job_ids) * 100 / total),
                importance=importance.get(key, {}),
                role_families=families.get(key, {}),
                state=gap_state(evidence),
                held=evidence is not None,
            )
        )

    # Most-asked-for first; ties alphabetically, so the order is stable between
    # two loads of the same data.
    #
    # Every skill, not the top twelve. The cap belongs to the demand list and is
    # applied by `most_asked` at the edge — applying it here also truncated the
    # gaps, which are ordered by a different rule and are a completeness claim
    # rather than a chart (DEV-040).
    demands.sort(key=lambda demand: (-demand.jobs, demand.name))
    return DemandReport(analysed_jobs=total, skills=demands)


def most_asked(report: DemandReport, limit: int = TOP_SKILLS) -> list[SkillDemand]:
    """The head of the demand list, for the chart that only wants a head.

    Separate from the report so that the one list which is deliberately
    incomplete is the only one that is, and so the caller has to hold the total
    beside it to say so.
    """
    return report.skills[:limit]


def build_gaps(report: DemandReport) -> list[SkillDemand]:
    """The demanded skills the profile does not fully answer.

    Ordered by severity, then by how many jobs asked. Severity first because a
    skill missing entirely from one posting is a bigger problem than a
    well-evidenced skill appearing in three — ``docs/07``'s own point that a gap
    in a strong opportunity can outweigh one appearing more often.

    Derived from the demand report rather than re-queried, so the two lists on
    the screen cannot disagree about what was asked for.

    That sharing is why the report must not arrive pre-truncated. This list is a
    completeness claim — "asked for, and not evidenced" — and a cap applied
    upstream by frequency silently drops gaps that this ordering would have put
    near the top. DEV-040.
    """
    return sorted(
        (skill for skill in report.skills if is_gap(skill.state)),
        key=lambda skill: (-GAP_SEVERITY[skill.state], -skill.jobs, skill.name),
    )


def _latest_analysis_ids(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """The newest reading of each unarchived job, as analysis ids.

    Two things at once, and both matter to the arithmetic on this screen.

    **One reading per job.** Analyses are versioned and every version keeps its
    requirements, so a job read three times holds three full sets. This account
    has one job with 36, 15 and 12 requirement rows against v1, v2 and v3 —
    counting them all would report that job three times for the crime of having
    been re-read.

    **Only jobs that have a reading.** A saved job nobody has analysed has no
    requirements, so including it in the denominator would deflate every
    percentage by the number of jobs sitting in the queue.
    """
    newest: dict[uuid.UUID, tuple[int, uuid.UUID]] = {}
    rows = session.execute(
        select(JobAnalysis.job_id, JobAnalysis.version, JobAnalysis.id)
        .join(Job, Job.id == JobAnalysis.job_id)
        .where(JobAnalysis.user_id == user_id, Job.archived_at.is_(None))
    ).all()

    for job_id, version, analysis_id in rows:
        current = newest.get(job_id)
        if current is None or version > current[0]:
            newest[job_id] = (version, analysis_id)

    return [analysis_id for _, analysis_id in newest.values()]
