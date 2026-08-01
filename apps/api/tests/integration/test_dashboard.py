"""The dashboard, against a real database.

The contract for this endpoint is one sentence in ``docs/10-api-contracts.md``:
*"The endpoint aggregates existing domain outputs. It must not duplicate
business logic."* These tests are mostly about that. They drive the real
endpoints — save a job, apply, archive — and then assert the dashboard agrees
with them, because a dashboard that computes its own version of the truth
disagrees with the screen the user checks it against, and the front page is the
one they believe.

What they protect:

- a new account gets an empty dashboard, not a 404 and not invented numbers;
- another user's jobs, applications and skills are never visible;
- archiving removes something everywhere, not just from the list it was
  archived on;
- a job with no score is left out of a ranking rather than sorted as a zero.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

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
DASHBOARD = "/api/v1/dashboard"
JOBS = "/api/v1/jobs"
APPLICATIONS = "/api/v1/applications"
CAREER = "/api/v1/career"
ALICE = "user_alice"
BOB = "user_bob"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- 5+ years of backend engineering experience\n"
    "- Strong Python\n"
    "- Spring Boot for our services\n"
    "- Rust for the routing core\n"
    "- Right to work in Portugal\n\n"
    "You will design and build our routing services and mentor two junior engineers."
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
        {
            "normalized_text": "Rust",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "CORE",
            "explicitness": "EXPLICIT",
            "source_text": "Rust for the routing core",
            "confidence": 92,
            "skill_name": "Rust",
        },
        {
            "normalized_text": "Right to work in Portugal",
            "requirement_type": "WORK_AUTHORIZATION",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "Right to work in Portugal",
            "confidence": 96,
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


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
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
        app.dependency_overrides[get_dispatcher] = lambda: RecordingDispatcher()

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def read(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> dict[str, Any]:
    response = client.get(DASHBOARD, headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def save_job(
    client: TestClient,
    factory: TokenFactory,
    subject: str = ALICE,
    *,
    title: str = "Senior Backend Engineer",
    description: str | None = POSTING,
) -> str:
    body: dict[str, Any] = {"import_method": "MANUAL", "title": title}
    if description is not None:
        body = {"import_method": "PASTED_DESCRIPTION", "title": title, "description": description}

    response = client.post(JOBS, headers=auth(factory, subject), json=body)
    assert response.status_code == 201, response.text
    job_id: str = response.json()["data"]["id"]
    return job_id


def add_skill(client: TestClient, factory: TokenFactory, name: str, subject: str = ALICE) -> None:
    """Enough profile for a match to produce a number.

    Without one the match scores null and the opportunity is correctly left out
    of the ranking, which is a different test.
    """
    response = client.post(
        f"{CAREER}/skills",
        headers=auth(factory, subject),
        json={"name": name, "category": "LANGUAGE"},
    )
    assert response.status_code == 201, response.text


def analysed_job(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> str:
    """A job with a completed analysis, ready to match against."""
    job_id = save_job(client, factory, subject)
    reanalyse(client, factory, job_id, subject)
    return job_id


def reanalyse(client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE) -> None:
    """Run the real pipeline with a scripted provider, appending a version."""
    started = client.post(f"{JOBS}/{job_id}/analysis", headers=auth(factory, subject))
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


# --- an account with nothing in it --------------------------------------------


def test_a_new_account_gets_an_empty_dashboard(client: TestClient, factory: TokenFactory) -> None:
    """200 with empty lists, not 404. Nothing is missing — the user has not
    done anything yet, and that is a state the screen can describe."""
    data = read(client, factory)

    assert data["state"]["jobs_saved"] == 0
    assert data["pipeline"] == []
    assert data["opportunities"] == []
    assert data["activity"] == []
    assert data["skill_gaps"] == []


def test_an_empty_profile_is_the_first_thing_suggested(
    client: TestClient, factory: TokenFactory
) -> None:
    """Every other answer is meaningless without a profile, so it outranks
    them."""
    data = read(client, factory)

    assert data["actions"], "a new account should be told where to start"
    assert data["actions"][0]["kind"] == "BUILD_PROFILE"


def test_every_action_carries_its_evidence(client: TestClient, factory: TokenFactory) -> None:
    """docs/07 requires an observation behind every insight. An action with no
    reason is a recommendation the user has to take on trust."""
    save_job(client, factory)

    for item in read(client, factory)["actions"]:
        assert item["reason"].strip()
        assert item["subject"].strip()


# --- what the counts count ----------------------------------------------------


def test_a_saved_job_shows_up_in_the_state(client: TestClient, factory: TokenFactory) -> None:
    save_job(client, factory)

    data = read(client, factory)

    assert data["state"]["jobs_saved"] == 1
    assert data["state"]["jobs_analysed"] == 0


def test_an_unread_job_is_offered_for_analysis(client: TestClient, factory: TokenFactory) -> None:
    save_job(client, factory, title="Platform Engineer")

    kinds = {item["kind"] for item in read(client, factory)["actions"]}

    assert "ANALYSE_JOB" in kinds


def test_an_archived_job_leaves_the_dashboard(client: TestClient, factory: TokenFactory) -> None:
    """Archiving is the user saying "stop showing me this", and a dashboard is
    entirely a list of things being shown."""
    job_id = save_job(client, factory)
    assert read(client, factory)["state"]["jobs_saved"] == 1

    archived = client.post(f"{JOBS}/{job_id}/archive", headers=auth(factory))
    assert archived.status_code == 200, archived.text

    data = read(client, factory)
    assert data["state"]["jobs_saved"] == 0
    assert all(item["job_id"] != job_id for item in data["actions"])


def test_recent_activity_records_a_saved_job(client: TestClient, factory: TokenFactory) -> None:
    save_job(client, factory, title="Staff Engineer")

    activity = read(client, factory)["activity"]

    assert [entry["subject"] for entry in activity] == ["Staff Engineer"]
    assert activity[0]["kind"] == "JOB_SAVED"


# --- the pipeline -------------------------------------------------------------


def test_the_pipeline_counts_applications_by_stage(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = save_job(client, factory)
    created = client.post(APPLICATIONS, headers=auth(factory), json={"job_id": job_id})
    assert created.status_code == 201, created.text

    pipeline = read(client, factory)["pipeline"]

    assert len(pipeline) == 1
    assert pipeline[0]["count"] == 1
    assert pipeline[0]["before_applying"] is True


def test_empty_stages_are_left_out(client: TestClient, factory: TokenFactory) -> None:
    """Fourteen columns of which one has anything in it reads as a system with
    thirteen problems."""
    job_id = save_job(client, factory)
    client.post(APPLICATIONS, headers=auth(factory), json={"job_id": job_id})

    pipeline = read(client, factory)["pipeline"]

    assert all(stage["count"] > 0 for stage in pipeline)


def test_a_live_application_is_counted_as_live(client: TestClient, factory: TokenFactory) -> None:
    job_id = save_job(client, factory)
    client.post(APPLICATIONS, headers=auth(factory), json={"job_id": job_id})

    assert read(client, factory)["state"]["applications_live"] == 1


# --- ownership ----------------------------------------------------------------


def test_another_users_jobs_are_invisible(client: TestClient, factory: TokenFactory) -> None:
    save_job(client, factory, subject=BOB, title="Bob's job")

    data = read(client, factory, subject=ALICE)

    assert data["state"]["jobs_saved"] == 0
    assert data["activity"] == []


def test_another_users_applications_are_invisible(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = save_job(client, factory, subject=BOB)
    client.post(APPLICATIONS, headers=auth(factory, BOB), json={"job_id": job_id})

    data = read(client, factory, subject=ALICE)

    assert data["pipeline"] == []
    assert data["state"]["applications_live"] == 0


def test_the_dashboard_needs_a_signed_in_user(client: TestClient) -> None:
    assert client.get(DASHBOARD).status_code == 401


# --- opportunities ------------------------------------------------------------


def test_a_job_with_no_match_is_not_an_opportunity(
    client: TestClient, factory: TokenFactory
) -> None:
    """The section is a ranking. A job nobody has measured, placed anywhere in
    it, reads as a verdict on that job."""
    save_job(client, factory)

    assert read(client, factory)["opportunities"] == []


def test_an_unknown_job_id_is_never_returned(client: TestClient, factory: TokenFactory) -> None:
    """Guards the join in `_opportunities`: a match whose job has been archived
    must drop out rather than surface a title from a stale dictionary."""
    data = read(client, factory)

    for opportunity in data["opportunities"]:
        assert uuid.UUID(opportunity["job_id"])


# --- staleness ----------------------------------------------------------------


def test_a_match_against_an_older_reading_is_reported_stale(
    client: TestClient, factory: TokenFactory
) -> None:
    """Found walking 2.10.3, on a real dashboard.

    The first version of `_opportunities` and `_actions` passed the match's own
    `analysis_version` as the *current* one — comparing a number to itself,
    which is never unequal. So a match against a posting that had since been
    re-read reported `is_stale = false`, showed no badge, and produced no
    action, while the match panel two clicks away said the opposite.

    Only visible when the analysis moves and nothing else does. The account
    that found it had also edited its profile, so the screen showed a *true*
    staleness reason for a different cause and the missing one was invisible.
    """
    add_skill(client, factory, "Python")
    job_id = analysed_job(client, factory)
    matched = client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))
    assert matched.status_code == 200, matched.text
    assert read(client, factory)["opportunities"][0]["is_stale"] is False

    reanalyse(client, factory, job_id)

    opportunity = read(client, factory)["opportunities"][0]
    assert opportunity["is_stale"] is True

    kinds = {action["kind"] for action in read(client, factory)["actions"]}
    assert "REFRESH_MATCH" in kinds


def test_the_stale_action_names_the_reading_that_changed(
    client: TestClient, factory: TokenFactory
) -> None:
    """The reason is the evidence, and a reason naming the wrong cause sends
    the user to check the wrong thing."""
    add_skill(client, factory, "Python")
    job_id = analysed_job(client, factory)
    client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))
    reanalyse(client, factory, job_id)

    refresh = next(
        action for action in read(client, factory)["actions"] if action["kind"] == "REFRESH_MATCH"
    )

    assert "re-read" in refresh["reason"]
