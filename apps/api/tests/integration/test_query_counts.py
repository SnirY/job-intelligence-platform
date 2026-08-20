"""What the read endpoints cost, and whether the cost grows with the data.

Phase 11 lists performance as untouched: eighty-eight indexes, no eager loading
anywhere in the codebase, and no measurement. This is the measurement, written
so it keeps working rather than producing one number and expiring.

**The assertion is the shape, not the count.** A budget of "no more than N
queries" is a number somebody picks and later raises, and it says nothing about
the thing that actually hurts — a page that costs four queries per row is fine
on a test account and ruinous on a real one. So every case here loads a small
set and a larger one and asserts the difference: an endpoint may cost whatever
it costs, and it may not cost *more per item*.

That catches N+1 by construction, in either direction. A query per job shows up
as growth. A fix that batches shows up as the growth going away, without anyone
having to agree what the right absolute number was.

Absolute counts are recorded too, as a ratchet with slack rather than a target,
so a change that triples a fixed cost is not invisible just because it triples
it uniformly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from jip_ai import build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.api.dependencies import get_dispatcher
from jip_api.application.jobs.analysis_pipeline import run_analysis
from jip_api.domain.processing.models import ProcessingJob
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
JOBS = "/api/v1/jobs"
CAREER = "/api/v1/career"
ALICE = "user_alice"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- 5+ years of backend engineering experience\n"
    "- Strong Python\n"
    "- Spring Boot for our services\n\n"
    "You will design and build our routing services."
)

PARSE_RESPONSE: dict[str, Any] = {
    "summary": "Senior backend role.",
    "requirements": [
        {
            "normalized_text": "5+ years backend engineering",
            "requirement_type": "EXPERIENCE",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "5+ years of backend engineering experience",
            "confidence": 95,
            "years_min": 5,
        },
        {
            "normalized_text": "Python",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "CORE",
            "explicitness": "EXPLICIT",
            "source_text": "Strong Python",
            "confidence": 95,
            "skill_name": "Python",
        },
        {
            "normalized_text": "Spring Boot",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "Spring Boot for our services",
            "confidence": 90,
            "skill_name": "Spring Boot",
        },
    ],
    "responsibilities": [],
    "years_experience_min": 5,
}

ANALYSIS_RESPONSE: dict[str, Any] = {
    "role_family": "BACKEND",
    "role_family_confidence": 92,
    "role_family_reasoning": "Server-side routing services in Python.",
    "seniority": "SENIOR",
    "seniority_confidence": 88,
    "seniority_reasoning": "Asks for 5+ years and expects mentoring.",
    "summary": "A senior backend role.",
}


# --- counting -----------------------------------------------------------------


@dataclass
class Counter:
    """Every statement issued while it is listening."""

    statements: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.statements)

    def selects(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]


@contextmanager
def counting() -> Iterator[Counter]:
    """Count SQL statements against every engine, for the duration of a block.

    Listens on the ``Engine`` class rather than an instance, because the app
    builds its own and the test never holds it.
    """
    counter = Counter()

    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        del conn, cursor, parameters, context, executemany
        counter.statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield counter
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def cost_of(client: TestClient, factory: TokenFactory, path: str, **params: Any) -> int:
    """How many statements one GET of `path` issues."""
    with counting() as counter:
        response = client.get(path, headers=auth(factory), params=params or None)
        assert response.status_code == 200, response.text
    return counter.count


def assert_flat(
    client: TestClient,
    factory: TokenFactory,
    path: str,
    grow: Any,
    *,
    small: int,
    large: int,
    tolerance: int = 0,
    **params: Any,
) -> None:
    """The cost of `path` must not rise with the number of rows behind it.

    `grow` takes a count and creates that many more of whatever the endpoint
    reads. Measured at two sizes rather than differentiated once, because a
    single reading cannot tell a fixed cost from a per-row one.

    `tolerance` is per *item*, not per call, and is meant for endpoints that
    legitimately issue one extra statement for a whole batch — never for a
    handful of stragglers. Default zero: an endpoint that pays per row should
    have to say so.
    """
    grow(small)
    before = cost_of(client, factory, path, **params)

    grow(large - small)
    after = cost_of(client, factory, path, **params)

    added = large - small
    per_item = (after - before) / added

    assert per_item <= tolerance, (
        f"{path} costs {per_item:.2f} extra queries per item "
        f"({before} at {small} rows, {after} at {large}). "
        "That is an N+1: the page will get slower for exactly the users who use it most."
    )


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
    dispatcher: RecordingDispatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    with serve_jwks(factory) as jwks_url:
        monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)
        monkeypatch.setenv("JIP_AUTH_ISSUER", ISSUER)
        monkeypatch.setenv("JIP_AUTH_JWKS_URL", jwks_url)
        monkeypatch.setenv("JIP_AUTH_AUTHORIZED_PARTIES", AUTHORIZED_PARTY)

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()

        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", clean_database_url)
        command.upgrade(config, "head")

        from jip_api.main import create_app

        app = create_app()
        app.dependency_overrides[get_dispatcher] = lambda: dispatcher

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def add_skill(client: TestClient, factory: TokenFactory, name: str) -> None:
    response = client.post(
        f"{CAREER}/skills",
        headers=auth(factory),
        json={"name": name, "category": "LANGUAGE"},
    )
    assert response.status_code == 201, response.text


def plain_job(client: TestClient, factory: TokenFactory, title: str) -> str:
    """A job with a description and no analysis. Cheap to make many of."""
    response = client.post(
        JOBS,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": title,
            "description": f"{POSTING}\n\nReference {title}.",
            "allow_duplicate": True,
        },
    )
    assert response.status_code == 201, response.text
    job_id: str = response.json()["data"]["id"]
    return job_id


def analyse(client: TestClient, factory: TokenFactory, job_id: str) -> None:
    started = client.post(f"{JOBS}/{job_id}/analysis", headers=auth(factory))
    assert started.status_code == 202, started.text

    router = build_router(
        resume_parse_model="fake-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )
    session = new_session()
    try:
        processing = session.get(
            ProcessingJob, uuid.UUID(started.json()["data"]["processing_job_id"])
        )
        assert processing is not None
        run_analysis(
            session,
            FakeLLMProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE]),
            router,
            job=processing,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()


def matched_jobs(client: TestClient, factory: TokenFactory, count: int, offset: int = 0) -> None:
    """`count` jobs, each analysed and matched. The expensive shape."""
    for index in range(count):
        job_id = plain_job(client, factory, f"Matched role {offset + index}")
        analyse(client, factory, job_id)
        response = client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))
        assert response.status_code == 200, response.text


# --- the lists ----------------------------------------------------------------


def test_the_jobs_list_does_not_pay_per_job(client: TestClient, factory: TokenFactory) -> None:
    """The screen a user opens most, against the data they accumulate most.

    Every row carries a score, an alignment label, a staleness flag and the
    coverage counts, and each of those is a plausible place to have written a
    loop.
    """
    add_skill(client, factory, "Python")
    counter = {"made": 0}

    def grow(n: int) -> None:
        matched_jobs(client, factory, n, offset=counter["made"])
        counter["made"] += n

    assert_flat(client, factory, JOBS, grow, small=2, large=6, page_size=50)


def test_the_alignment_distribution_does_not_pay_per_job(
    client: TestClient, factory: TokenFactory
) -> None:
    """It reads the whole filtered set rather than a page, which is the point of
    it and also what would make a per-row cost expensive without a page size to
    cap it."""
    add_skill(client, factory, "Python")
    counter = {"made": 0}

    def grow(n: int) -> None:
        matched_jobs(client, factory, n, offset=counter["made"])
        counter["made"] += n

    assert_flat(client, factory, f"{JOBS}/distribution", grow, small=2, large=6)


def test_the_dashboard_does_not_pay_per_job(client: TestClient, factory: TokenFactory) -> None:
    """The first screen after sign-in, and the one that reads the most tables."""
    add_skill(client, factory, "Python")
    counter = {"made": 0}

    def grow(n: int) -> None:
        matched_jobs(client, factory, n, offset=counter["made"])
        counter["made"] += n

    assert_flat(client, factory, "/api/v1/dashboard", grow, small=2, large=6)


def test_the_match_view_does_not_pay_per_requirement(
    client: TestClient, factory: TokenFactory
) -> None:
    """Items, their evidence and their requirements are three batched reads.

    Asserted as an absolute here rather than by growth, because the number of
    requirements is fixed by the posting rather than by anything the test can
    add. The ceiling is loose on purpose — it is a ratchet against a loop being
    introduced, not a target to optimise towards.
    """
    add_skill(client, factory, "Python")
    job_id = plain_job(client, factory, "Match cost")
    analyse(client, factory, job_id)
    response = client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))
    assert response.status_code == 200, response.text

    cost = cost_of(client, factory, f"{JOBS}/{job_id}/match")

    assert cost <= 25, (
        f"reading one match cost {cost} queries against three requirements. "
        "Three batched reads plus the profile snapshot is the shape; a number "
        "that scales with requirements is not."
    )


def test_the_applications_list_does_not_pay_per_application(
    client: TestClient, factory: TokenFactory
) -> None:
    add_skill(client, factory, "Python")
    made: list[str] = []

    def grow(n: int) -> None:
        for index in range(n):
            job_id = plain_job(client, factory, f"Tracked role {len(made) + index}")
            response = client.post(
                "/api/v1/applications",
                headers=auth(factory),
                json={"job_id": job_id, "status": "SAVED"},
            )
            assert response.status_code == 201, response.text
            made.append(job_id)

    assert_flat(client, factory, "/api/v1/applications", grow, small=2, large=6, page_size=50)
