"""The canonical skill catalogue, against a real database.

DEV-032. The catalogue is what makes "Postgres" and "PostgreSQL" one skill, and
everything keyed on ``skill_id`` depends on it: Phase 6 matching, DEV-025's
deduplication, Phase 10's demand counts. A skill it does not know does not
raise — it writes a null column, so the failure is silent and looks like a job
that simply asks for less.

It resolved **one** of the seventeen skill names two real postings produced —
one, not the three the issue first recorded: Linux and SQL were never seeded,
and existed in the development database only because a resume import created
them there.
These tests protect the fix and, more importantly, protect against the failure
being silent again: the names below were observed in real readings, not
invented, and each is here because something downstream needs it to resolve.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from jip_api.application.jobs.requirement_skills import resolve_known_skills
from jip_api.domain.career.skills import Skill, SkillAlias, normalize_skill_name
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_config import get_settings

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated(clean_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)
    get_settings.cache_clear()
    reset_engine_cache()

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", clean_database_url)
    command.upgrade(config, "head")

    yield

    get_settings.cache_clear()
    reset_engine_cache()


# Every one of these was named by a real posting and failed to resolve before
# DEV-032. They are the regression, not a wish list.
OBSERVED = [
    "C++",
    "TCP/IP",
    "AI/ML",
    "Algorithms",
    "Data structures",
    "Object-oriented design",
    "Multi-threading",
    "Design Patterns",
    "Version control systems",
    "Kubernetes",
    "Linux",
    "SQL",
    "AWS",
    "Python",
    "DOCSIS",
    "CI/CD",
    "Microservices",
    "Debugging",
]


def test_every_skill_a_real_posting_named_resolves(migrated: None) -> None:
    session = new_session()
    try:
        resolved = resolve_known_skills(session, OBSERVED)
    finally:
        session.close()

    missing = [name for name in OBSERVED if name not in resolved]
    assert not missing, f"the catalogue no longer resolves: {missing}"


def test_the_two_ways_of_writing_c_plus_plus_are_one_skill(migrated: None) -> None:
    """The pair that made DEV-026 look worse than it was.

    "C++" and "C/C++" are one requirement written two ways, and while they
    resolved to nothing they counted as two — in the demand report, in the
    deduplication, and in the stability measurement.
    """
    session = new_session()
    try:
        resolved = resolve_known_skills(session, ["C++", "C/C++"])
    finally:
        session.close()

    assert resolved["C++"].id == resolved["C/C++"].id


def test_a_compound_resolves_to_the_first_skill_it_names(migrated: None) -> None:
    """ "SQL/NoSQL databases" is several skills written as one requirement.

    Filing it under SQL is closer than filing it nowhere, and it is the reading
    a person gives. Asserted so the choice is deliberate rather than incidental.
    """
    session = new_session()
    try:
        resolved = resolve_known_skills(session, ["SQL/NoSQL databases", "SQL"])
    finally:
        session.close()

    assert resolved["SQL/NoSQL databases"].id == resolved["SQL"].id


def test_a_phrase_that_is_not_a_skill_resolves_to_nothing(migrated: None) -> None:
    """The other half of the rule, and the more important one.

    A wrong canonical skill is worse than none: it would put a candidate's
    Python against a requirement that never asked for Python. These three were
    named by real postings and are deliberately absent.
    """
    session = new_session()
    try:
        resolved = resolve_known_skills(
            session,
            [
                "General-purpose programming language",
                "performance-critical software",
                "Java/Python/C++/C#/Go/Rust/TypeScript (at least one)",
            ],
        )
    finally:
        session.close()

    assert resolved == {}


def test_no_alias_shadows_a_canonical_name(migrated: None) -> None:
    """Resolution checks canonical names and aliases separately.

    An alias equal to some skill's canonical name would make the answer depend
    on which lookup ran first, which is the kind of bug that appears only for
    the one skill it affects.
    """
    session = new_session()
    try:
        canonical = set(session.scalars(select(Skill.normalized_name)))
        aliases = set(session.scalars(select(SkillAlias.normalized_alias)))
    finally:
        session.close()

    assert not (canonical & aliases), f"aliases shadowing a canonical name: {canonical & aliases}"


def test_the_catalogue_covers_enough_to_be_worth_having(migrated: None) -> None:
    """A floor, not a target.

    Thirty rows resolved one of seventeen observed names. This asserts the
    catalogue has not been quietly reduced to that again — the exact number
    matters less than that it cannot silently collapse.
    """
    session = new_session()
    try:
        total = len(list(session.scalars(select(Skill.id))))
    finally:
        session.close()

    assert total >= 100


def test_normalisation_agrees_with_the_migration(migrated: None) -> None:
    """The migration duplicates `normalize_skill_name` so its output cannot
    drift when the application's rule changes. That is correct, and it means
    the two can silently disagree — so check they still produce the same key
    for the names that matter."""
    session = new_session()
    try:
        rows = list(session.scalars(select(Skill.canonical_name)))
        stored = {name: normalize_skill_name(name) for name in rows}
        keys = set(session.scalars(select(Skill.normalized_name)))
    finally:
        session.close()

    disagreeing = {name: key for name, key in stored.items() if key not in keys}
    assert not disagreeing, f"application and migration normalise differently: {disagreeing}"
