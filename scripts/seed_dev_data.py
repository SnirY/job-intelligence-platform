"""Fill a development account with enough data to actually look at the screens.

Four screens shipped in Phase 12 and none of them shows anything on an empty
account. Reaching them by hand means building a profile, saving a job, running
an analysis, running a match, adding a board and scanning it — twenty minutes of
clicking before twenty minutes of looking, which is how a manual walkthrough
stops happening.

    python scripts/seed_dev_data.py

**No model is called and nothing costs money.** The analysis and its
requirements are written directly, and `run_match` is deterministic — it takes a
profile snapshot and a list of requirements and needs no provider at all. That
is the whole reason this script can exist.

What it makes, and which screen each part is for:

| Row | For |
|---|---|
| A career profile with skills and one role | Everything downstream; nothing matches without it |
| A job with a link | The liveness row in the job's Details card |
| A job whose posting asks for money | The posting-concerns panel |
| An analysis, requirements, and a real match | The cover letter panel, which refuses without one |
| A watched board and three discovered postings | `/discovery` and its review list |

Idempotent. Everything it writes is tagged, and a second run reports what is
already there rather than making a second copy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.application.matching.pipeline import run_match
from jip_api.domain.career.history import Experience
from jip_api.domain.career.models import CareerProfile, VerificationStatus
from jip_api.domain.career.skills import Skill, SkillSource, UserSkill
from jip_api.domain.discovery.models import DiscoveredPosting, WatchedBoard
from jip_api.domain.jobs.analysis import (
    AnalyzedSeniority,
    JobAnalysis,
    JobRequirement,
    RequirementExplicitness,
    RequirementImportance,
    RequirementType,
    RoleFamily,
)
from jip_api.domain.jobs.models import Job, JobImportMethod, JobProcessingStatus, normalize_title
from jip_api.domain.users.models import User
from jip_api.infrastructure.db.session import new_session
from jip_config import Environment, get_settings

TAG = "[seed]"
"""Written into every title this script creates.

So a person can tell at a glance which rows are theirs and which are scaffolding,
and so a second run can recognise its own work.
"""

SKILLS = ("Python", "PostgreSQL", "Flask", "Linux")
"""Looked up in the catalogue rather than created.

The catalogue is shared and migrations populate it; inventing rows in it from a
dev script is how a shared table acquires entries nobody remembers adding. So
these are names the catalogue actually holds — the first draft used FastAPI and
Docker, and **neither is in it**, which is a real gap in the catalogue rather
than a problem with this list. Anything missing is reported rather than silently
skipped, so a shrinking count is visible instead of looking like success.
"""

SCAM_POSTING = (
    "Remote Data Entry Associate. Immediate start, no experience necessary. "
    "Earn competitive weekly pay working from home on flexible hours. "
    "There is a one-time training fee of $250 which covers your onboarding "
    "materials. Contact me on WhatsApp to arrange the interview."
)

REAL_POSTING = (
    "We are hiring a Senior Backend Engineer for our shipment platform. You "
    "will build REST services in Python, own the PostgreSQL schema behind "
    "carrier reconciliation, and help move the remaining Flask endpoints "
    "across. We work hybrid from Lisbon, two days a week in the office, and "
    "you will join a team of six reporting to the Head of Platform. "
    "You will own your services in production, including the on-call rotation, "
    "and you will have a real say in what we build next. We offer private "
    "healthcare, a learning budget, and we cover the cost of your equipment."
)
"""Deliberately over `THIN_DESCRIPTION_CHARS`.

The first version was 350 characters, which tripped the thin-posting rule on the
jobs that are supposed to look fine — so a walkthrough would have found a
concern on every job and learned nothing from any of them. The scam posting
carries the concerns; these two are the control.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user",
        help=(
            "Which account to seed — any part of its Clerk id. "
            "Omit to take the one you signed in with most recently."
        ),
    )
    args = parser.parse_args()

    try:
        _refuse_unless_local()
    except SystemExit:
        raise
    except Exception as error:  # pragma: no cover - defensive
        print(f"Could not read settings: {error}", file=sys.stderr)
        return 1

    session = new_session()
    try:
        user = _find_user(session, args.user)
        if user is None:
            return 1

        made = _seed(session, user)
        session.commit()
    finally:
        session.close()

    for line in made:
        print(f"  {line}")
    print("\nOpen /jobs and /discovery.")
    return 0


def _refuse_unless_local() -> None:
    """Two independent checks, because this writes rows.

    The environment setting is the stated intent and the database host is the
    fact. Either one alone is a check somebody can be wrong about — a `.env`
    copied from staging says local, and a local `.env` can point at a remote
    database.
    """
    settings = get_settings()

    if settings.environment is not Environment.LOCAL:
        raise SystemExit(f"Refusing to seed: environment is {settings.environment}, not local.")

    host = urlsplit(settings.database_url.replace("postgresql+psycopg", "postgresql")).hostname
    if host not in {"localhost", "127.0.0.1", "::1", "postgres"}:
        raise SystemExit(f"Refusing to seed: the database is at {host!r}, which is not local.")


def _find_user(session: Session, wanted: str | None) -> User | None:
    """The account to seed, or a message explaining why not.

    Never creates one. A user row is minted by signing in, and a script that
    invented one would produce an account nobody can log into — which looks like
    seeding worked and is worse than failing.

    **Matched on `external_user_id`, not on email.** The first version of this
    took `--email` and could never work: `provisioning._sync_profile` says so
    directly — "Clerk's default session token carries no email or name" — so
    `users.email` is null in an ordinary local setup and every lookup missed.

    With no argument it takes the newest row, which is the session you just
    signed in with. It says which one it picked, because signing in twice is
    normal here and picking silently would seed the account you are not looking
    at.
    """
    users = list(session.scalars(select(User).order_by(User.created_at.desc())))

    if not users:
        print("No users yet. Sign in at http://localhost:3000, then run this again.")
        return None

    if wanted:
        matches = [
            user
            for user in users
            if wanted in user.external_user_id or (user.email and wanted in user.email)
        ]
        if len(matches) == 1:
            return matches[0]
        print(f"{'No' if not matches else 'More than one'} account matches {wanted!r}.")
        _list_users(users)
        return None

    if len(users) > 1:
        print(f"{len(users)} accounts here. Taking the newest — pass --user to choose another.")
        _list_users(users)
        print()

    chosen = users[0]
    print(f"Seeding {chosen.external_user_id}")
    return chosen


def _list_users(users: list[User]) -> None:
    """Show what there is to choose between.

    Printed rather than described, because the identifiers are Clerk subjects
    and nobody knows theirs by heart.
    """
    for index, user in enumerate(users):
        when = user.created_at.strftime("%Y-%m-%d %H:%M")
        newest = "  (newest)" if index == 0 else ""
        print(f"  {user.external_user_id}  first seen {when}{newest}")


def _seed(session: Session, user: User) -> list[str]:
    made: list[str] = []

    existing = session.scalars(
        select(Job).where(Job.user_id == user.id, Job.title.like(f"{TAG}%")).limit(1)
    ).one_or_none()
    if existing is not None:
        return ["Already seeded. Delete the [seed] jobs and boards to start over."]

    made.append(_profile(session, user.id))
    made.append(_job_with_a_link(session, user.id))
    made.append(_job_that_asks_for_money(session, user.id))
    made.append(_matched_job(session, user.id))
    made.extend(_discovery(session, user.id))
    return made


def _profile(session: Session, user_id: uuid.UUID) -> str:
    profile = session.scalars(
        select(CareerProfile).where(CareerProfile.user_id == user_id)
    ).one_or_none()
    if profile is None:
        profile = CareerProfile(user_id=user_id, headline=f"{TAG} Backend Engineer")
        session.add(profile)

    session.add(
        Experience(
            user_id=user_id,
            company="Verdant Logistics",
            title=f"{TAG} Senior Backend Engineer",
            description=(
                "Built REST services in Python and FastAPI. Owned the PostgreSQL "
                "schema behind carrier reconciliation. Everything ran in Docker."
            ),
            # USER_CONFIRMED so selection will actually use it. Unverified
            # evidence is deliberately withheld from a tailored resume, and a
            # seed that produced only withheld facts would look like a bug.
            verification_status=VerificationStatus.USER_CONFIRMED,
        )
    )

    added = 0
    missing: list[str] = []
    for name in SKILLS:
        skill = session.scalars(select(Skill).where(Skill.canonical_name == name)).one_or_none()
        if skill is None:
            missing.append(name)
            continue
        already = session.scalars(
            select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.skill_id == skill.id)
        ).one_or_none()
        if already is not None:
            continue
        session.add(
            UserSkill(
                user_id=user_id,
                skill_id=skill.id,
                source=SkillSource.MANUAL,
                verification_status=VerificationStatus.USER_CONFIRMED,
            )
        )
        added += 1

    session.flush()
    note = f"profile: one role and {added} skills"
    if missing:
        note += f" (not in the catalogue: {', '.join(missing)})"
    return note


def _new_job(user_id: uuid.UUID, title: str, **kwargs: Any) -> Job:
    return Job(
        user_id=user_id,
        title=f"{TAG} {title}",
        normalized_title=normalize_title(title),
        status=JobProcessingStatus.RAW,
        **kwargs,
    )


def _job_with_a_link(session: Session, user_id: uuid.UUID) -> str:
    """For the liveness row. A real, stable URL that answers 200."""
    job = _new_job(
        user_id,
        "Platform Engineer (has a link)",
        company="Tidewater",
        import_method=JobImportMethod.URL,
        source_url="https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        description=REAL_POSTING,
    )
    session.add(job)
    session.flush()
    return "job with a link: press Check on its Details card"


def _job_that_asks_for_money(session: Session, user_id: uuid.UUID) -> str:
    """For the concerns panel. Trips two rules at once, which is the point —
    the panel should order the serious one first."""
    job = _new_job(
        user_id,
        "Remote Data Entry Associate (looks wrong)",
        company="Unknown",
        import_method=JobImportMethod.PASTED_DESCRIPTION,
        description=SCAM_POSTING,
        posted_at=dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=200),
    )
    session.add(job)
    session.flush()
    return "job that asks for money: three concerns, oldest posting too"


def _matched_job(session: Session, user_id: uuid.UUID) -> str:
    """For the cover letter panel, which refuses without a match.

    The analysis and its requirements are written rather than parsed. `run_match`
    then runs for real — it is deterministic and needs no provider, which is what
    makes a genuine match reachable from a script.
    """
    job = _new_job(
        user_id,
        "Senior Backend Engineer (matched)",
        company="Verdant Logistics",
        location="Lisbon, Portugal",
        import_method=JobImportMethod.PASTED_DESCRIPTION,
        description=REAL_POSTING,
    )
    session.add(job)
    session.flush()

    analysis = JobAnalysis(
        user_id=user_id,
        job_id=job.id,
        version=1,
        # The job screen renders these as "Read by {model} using {prompt}", so
        # they have to read as a sentence. The first version set provider="seed"
        # and model="none" and produced "Read by none using seed", which is not
        # wrong so much as meaningless to whoever is looking at it.
        provider="seed script",
        model="no model",
        parse_prompt_version="a seeded analysis",
        input_hash="seed",
        payload={"seeded": True},
        role_family=RoleFamily.BACKEND,
        seniority=AnalyzedSeniority.SENIOR,
    )
    session.add(analysis)
    session.flush()

    requirements = []
    for name, importance in (
        ("Python", RequirementImportance.CORE),
        ("FastAPI", RequirementImportance.CORE),
        ("PostgreSQL", RequirementImportance.REQUIRED),
        # Deliberately not in the seeded profile, so the match has a real gap
        # and the letter has something it is not allowed to claim.
        ("Kubernetes", RequirementImportance.REQUIRED),
    ):
        requirement = JobRequirement(
            user_id=user_id,
            analysis_id=analysis.id,
            job_id=job.id,
            requirement_type=RequirementType.TECHNICAL_SKILL,
            importance=importance,
            explicitness=RequirementExplicitness.EXPLICIT,
            source_text=f"Experience with {name}",
            normalized_text=name.lower(),
        )
        session.add(requirement)
        requirements.append(requirement)
    session.flush()

    outcome = run_match(
        session, user_id=user_id, job=job, analysis=analysis, requirements=requirements
    )
    job.status = JobProcessingStatus.ANALYZED
    session.flush()
    return f"matched job: scored {outcome.result.overall_score} — write a cover letter from it"


def _discovery(session: Session, user_id: uuid.UUID) -> list[str]:
    """For `/discovery`. A real board plus three candidates already in the list,
    so the review screen has something on it before anything is scanned."""
    board = WatchedBoard(
        user_id=user_id,
        provider="greenhouse",
        token="anthropic",
        label=f"{TAG} Anthropic",
    )
    session.add(board)

    now = dt.datetime.now(tz=dt.UTC)

    # Two ordinary rows and one deliberately long one. DEV-082 was a row whose
    # content pushed the action buttons onto their own line, and it is only
    # visible beside rows that stayed put — a list where every row says "Remote"
    # is a list where that bug cannot be seen, by a person or by a test.
    #
    # The long one is dated a day earlier so it sorts to the bottom (the review
    # list is newest first), which keeps it clear of anything that takes the
    # first row and promotes it.
    candidates = (
        ("Backend Engineer", "Remote", now),
        ("Platform Engineer", "Remote", now),
        (
            "Staff Platform Engineer, Developer Experience and Build Tooling",
            "Remote-Friendly (Travel Required) | San Francisco, CA "
            "| Seattle, WA | New York City, NY",
            now - dt.timedelta(days=1),
        ),
    )

    for index, (title, location, first_seen) in enumerate(candidates):
        session.add(
            DiscoveredPosting(
                user_id=user_id,
                provider="greenhouse",
                board="anthropic",
                external_id=f"seed-{index}",
                title=f"{TAG} {title}",
                url=f"https://example.com/seed/{index}",
                company="Seeded Co",
                location=location,
                first_seen_at=first_seen,
                last_seen_at=first_seen,
                description_text=REAL_POSTING,
            )
        )
    session.flush()
    return [
        "watched board: a real Greenhouse board, press Scan now",
        "three candidates waiting in the review list, one long enough to show a layout fault",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
