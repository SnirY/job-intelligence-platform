"""Job analysis end to end, against a real database.

The pipeline is driven directly with a scripted provider — the queue's only job
here is to prove the API asked for the work. What these tests protect:

- the job, its description, and its preserved original survive an analysis and
  a failed analysis alike;
- reanalysis adds a version and leaves the previous one readable;
- requirements resolve to the *seeded* canonical catalogue, and an unknown
  technology does not add a row to it;
- another user cannot read or start an analysis.
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
from sqlalchemy import func, select

from jip_ai import AIError, AIFailureCode, build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.api.dependencies import get_dispatcher
from jip_api.application.jobs.analysis_pipeline import run_analysis
from jip_api.domain.ai.models import AIRun
from jip_api.domain.career.skills import Skill
from jip_api.domain.jobs.analysis import JobAnalysis, JobRequirement
from jip_api.domain.processing.models import ProcessingJob
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/jobs"
ALICE = "user_alice"
BOB = "user_bob"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- 5+ years of backend engineering experience\n"
    "- Strong Python and Postgres\n"
    "- Kubernetes experience is a nice to have\n"
    "- Familiarity with Elixir\n\n"
    "You will design and build our routing services, own the schema behind "
    "carrier reconciliation, and mentor two junior engineers. We work hybrid "
    "from Lisbon, two days a week in the office."
)

PARSE_RESPONSE: dict[str, Any] = {
    "summary": "Senior backend role owning a routing platform.",
    "title": "Senior Backend Engineer",
    "company": "Verdant Logistics",
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
            "source_text": "Strong Python and Postgres",
            "confidence": 95,
            "skill_name": "Python",
        },
        {
            # An alias. Must resolve to the seeded PostgreSQL skill.
            "normalized_text": "PostgreSQL",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "CORE",
            "explicitness": "EXPLICIT",
            "source_text": "Strong Python and Postgres",
            "confidence": 95,
            "skill_name": "Postgres",
        },
        {
            # Hedged, but the model called it required.
            "normalized_text": "Kubernetes",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "Kubernetes experience is a nice to have",
            "confidence": 85,
            "skill_name": "Kubernetes",
        },
        {
            # Not in the catalogue. Must not be added to it.
            "normalized_text": "Elixir",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "PREFERRED",
            "explicitness": "EXPLICIT",
            "source_text": "Familiarity with Elixir",
            "confidence": 70,
            "skill_name": "Elixir",
        },
        {
            # Fabricated. Must be dropped.
            "normalized_text": "AWS",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "Deep AWS expertise across every service",
            "confidence": 90,
            "skill_name": "AWS",
        },
    ],
    "responsibilities": [
        {
            "text": "Design and build routing services",
            "source_text": "You will design and build our routing services",
            "confidence": 90,
        },
        {
            "text": "Mentor junior engineers",
            "source_text": "mentor two junior engineers",
            "confidence": 85,
        },
    ],
    "years_experience_min": 5,
}

ANALYSIS_RESPONSE: dict[str, Any] = {
    "role_family": "BACKEND",
    "role_family_confidence": 92,
    "role_family_reasoning": "Server-side routing services in Python and Postgres.",
    "seniority": "SENIOR",
    "seniority_confidence": 88,
    "seniority_reasoning": "Asks for 5+ years, expects schema ownership, and includes mentoring.",
    "domain": "logistics",
    "summary": "A senior backend role owning delivery routing at scale.",
}


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


def create_job(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> str:
    response = client.post(
        BASE,
        headers=auth(factory, subject),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": POSTING,
        },
    )
    assert response.status_code == 201, response.text
    job_id: str = response.json()["data"]["id"]
    return job_id


def start(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, expect: int = 202
) -> dict[str, Any]:
    response = client.post(f"{BASE}/{job_id}/analysis", headers=auth(factory, subject))
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def read(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"{BASE}/{job_id}/analysis", headers=auth(factory, subject), params=params or None
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def run_pipeline(
    processing_job_id: str,
    *,
    parse: dict[str, Any] | AIError | None = None,
    analysis: dict[str, Any] | AIError | None = None,
) -> None:
    """Drive the real pipeline with a scripted provider.

    The worker task is a thin wrapper over this; running the pipeline directly
    keeps the test about the pipeline rather than about RQ.
    """
    router = build_router(
        resume_parse_model="fake-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )
    provider = FakeLLMProvider(
        [
            parse if parse is not None else PARSE_RESPONSE,
            analysis if analysis is not None else ANALYSIS_RESPONSE,
        ]
    )

    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(processing_job_id))
        assert job is not None
        run_analysis(
            session,
            provider,
            router,
            job=job,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()


def analyse(client: TestClient, factory: TokenFactory, job_id: str, **script: Any) -> None:
    started = start(client, factory, job_id)
    run_pipeline(started["processing_job_id"], **script)


# --- starting -----------------------------------------------------------------


def test_queues_an_analysis(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    job_id = create_job(client, factory)

    started = start(client, factory, job_id)

    assert started["job_id"] == job_id
    assert started["status"] == "PENDING"
    assert dispatcher.calls[-1][0] == "jip_worker.tasks.jobs.run_job_analysis"


def test_refuses_to_analyse_a_job_with_no_description(
    client: TestClient, factory: TokenFactory
) -> None:
    """A URL import still in flight is the common case, and the right answer is
    to wait rather than to spend a model call on an empty string."""
    response = client.post(
        BASE,
        headers=auth(factory),
        json={"import_method": "MANUAL", "title": "Platform Engineer"},
    )
    job_id = response.json()["data"]["id"]

    body = start(client, factory, job_id, expect=409)

    assert "no description" in body["error"]["message"]


def test_reports_whether_an_analysis_can_be_started(
    client: TestClient, factory: TokenFactory
) -> None:
    """The button's enabled state and the endpoint's 409 rule must agree, or
    the user clicks something that fails."""
    response = client.post(
        BASE,
        headers=auth(factory),
        json={"import_method": "MANUAL", "title": "Platform Engineer"},
    )
    empty = response.json()["data"]["id"]
    full = create_job(client, factory)

    assert read(client, factory, empty)["can_analyze"] is False
    assert read(client, factory, full)["can_analyze"] is True


# --- reading ------------------------------------------------------------------


def test_reports_no_analysis_for_a_job_that_has_none(
    client: TestClient, factory: TokenFactory
) -> None:
    """200 with a null analysis, not 404. The job exists; a 404 would say it
    did not, which is a different problem with a different fix."""
    job_id = create_job(client, factory)

    data = read(client, factory, job_id)

    assert data["analysis"] is None
    assert data["requirements"] == []
    assert data["available_versions"] == []


def test_returns_the_analysis_after_it_runs(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    data = read(client, factory, job_id)

    assert data["analysis"]["version"] == 1
    assert data["analysis"]["role_family"] == "BACKEND"
    assert data["analysis"]["seniority"] == "SENIOR"
    assert data["job_status"] == "ANALYZED"


def test_records_the_reasoning_behind_each_judgement(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    analysis = read(client, factory, job_id)["analysis"]

    assert "5+ years" in analysis["seniority_reasoning"]
    assert analysis["seniority_confidence"] == 88
    assert analysis["role_family_reasoning"]
    assert analysis["role_family_confidence"] == 92


def test_records_both_prompt_versions(client: TestClient, factory: TokenFactory) -> None:
    """Stored separately because the two steps version independently."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    analysis = read(client, factory, job_id)["analysis"]

    assert analysis["parse_prompt_version"] == "job_parser_v1"
    assert analysis["analysis_prompt_version"] == "job_analysis_v1"


# --- requirements -------------------------------------------------------------


def test_keeps_the_posting_s_own_words_on_every_requirement(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]

    assert requirements
    for requirement in requirements:
        assert requirement["source_text"] in POSTING


def test_drops_a_requirement_quoting_text_that_is_not_in_the_posting(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]

    assert not any(r["normalized_text"] == "AWS" for r in requirements)


def test_demotes_a_hedged_requirement(client: TestClient, factory: TokenFactory) -> None:
    """ "Kubernetes is a nice to have" came back REQUIRED and must not stay
    that way — this is the substitution that makes someone skip a job."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]
    kubernetes = next(r for r in requirements if r["normalized_text"] == "Kubernetes")

    assert kubernetes["importance"] == "PREFERRED"


def test_preserves_the_required_and_preferred_split(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]
    by_name = {r["normalized_text"]: r["importance"] for r in requirements}

    assert by_name["5+ years backend engineering"] == "REQUIRED"
    assert by_name["Python"] == "CORE"
    assert by_name["Kubernetes"] == "PREFERRED"
    assert by_name["Elixir"] == "PREFERRED"


def test_serves_requirements_from_their_own_endpoint(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(f"{BASE}/{job_id}/requirements", headers=auth(factory))

    assert response.status_code == 200
    assert len(response.json()["data"]) == 5


def test_filters_requirements_by_importance(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(
        f"{BASE}/{job_id}/requirements", headers=auth(factory), params={"importance": "CORE"}
    )

    assert {r["normalized_text"] for r in response.json()["data"]} == {"Python", "PostgreSQL"}


def test_filters_requirements_by_type(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(
        f"{BASE}/{job_id}/requirements",
        headers=auth(factory),
        params={"requirement_type": "EXPERIENCE"},
    )

    assert len(response.json()["data"]) == 1


def test_requirements_endpoint_is_empty_before_an_analysis(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)

    response = client.get(f"{BASE}/{job_id}/requirements", headers=auth(factory))

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_keeps_responsibilities_separate_from_requirements(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    data = read(client, factory, job_id)

    assert len(data["responsibilities"]) == 2
    assert {r["text"] for r in data["responsibilities"]} == {
        "Design and build routing services",
        "Mentor junior engineers",
    }


# --- skill resolution ---------------------------------------------------------


def test_resolves_a_requirement_to_a_canonical_skill(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]
    python = next(r for r in requirements if r["normalized_text"] == "Python")

    assert python["skill_id"] is not None


def test_resolves_an_alias_to_the_canonical_skill(
    client: TestClient, factory: TokenFactory
) -> None:
    """The posting said "Postgres". Phase 6 must see the same skill as a
    profile that says "PostgreSQL", or the match silently fails."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]
    postgres = next(r for r in requirements if r["normalized_text"] == "PostgreSQL")

    session = new_session()
    try:
        skill = session.get(Skill, uuid.UUID(postgres["skill_id"]))
        assert skill is not None
        assert skill.canonical_name == "PostgreSQL"
    finally:
        session.close()


def test_leaves_an_unknown_skill_unresolved(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    requirements = read(client, factory, job_id)["requirements"]
    elixir = next(r for r in requirements if r["normalized_text"] == "Elixir")

    assert elixir["skill_id"] is None
    assert elixir["skill_name"] == "Elixir"


def test_does_not_add_an_unknown_skill_to_the_shared_catalogue(
    client: TestClient, factory: TokenFactory
) -> None:
    """The rule the goal is most specific about. Letting job analysis write to
    a table every user shares is how the catalogue fills with "strong Elixir",
    "Elixir (a plus)", and "ELIXIR" — each a skill that never matches again."""
    job_id = create_job(client, factory)

    session = new_session()
    try:
        before = session.execute(select(func.count()).select_from(Skill)).scalar_one()
    finally:
        session.close()

    analyse(client, factory, job_id)

    session = new_session()
    try:
        after = session.execute(select(func.count()).select_from(Skill)).scalar_one()
        elixir = session.execute(
            select(Skill).where(Skill.normalized_name == "elixir")
        ).scalar_one_or_none()
    finally:
        session.close()

    assert after == before
    assert elixir is None


# --- versioning ---------------------------------------------------------------


def test_reanalysis_adds_a_version(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)
    analyse(client, factory, job_id)

    data = read(client, factory, job_id)

    assert data["analysis"]["version"] == 2
    assert data["available_versions"] == [2, 1]


def test_the_previous_version_stays_readable(client: TestClient, factory: TokenFactory) -> None:
    """History is the reason versions exist. A reanalysis that silently
    replaced the last one would make disagreeing with it unrecoverable."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)
    analyse(
        client,
        factory,
        job_id,
        analysis={**ANALYSIS_RESPONSE, "seniority": "MID", "role_family": "FULL_STACK"},
    )

    first = read(client, factory, job_id, version=1)["analysis"]
    second = read(client, factory, job_id, version=2)["analysis"]

    assert first["seniority"] == "SENIOR"
    assert second["seniority"] == "MID"


def test_each_version_keeps_its_own_requirements(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)
    analyse(
        client,
        factory,
        job_id,
        parse={
            **PARSE_RESPONSE,
            "requirements": [PARSE_RESPONSE["requirements"][0]],
        },
    )

    assert len(read(client, factory, job_id, version=1)["requirements"]) == 5
    assert len(read(client, factory, job_id, version=2)["requirements"]) == 1


def test_an_unknown_version_is_not_found(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(f"{BASE}/{job_id}/analysis", headers=auth(factory), params={"version": 9})

    assert response.status_code == 404


# --- staleness ----------------------------------------------------------------


def test_a_fresh_analysis_is_not_stale(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    assert read(client, factory, job_id)["is_stale"] is False


def test_editing_the_description_makes_the_analysis_stale(
    client: TestClient, factory: TokenFactory
) -> None:
    """A fact, not a guess: the hash of the text the analysis read is stored
    on it."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    client.patch(
        f"{BASE}/{job_id}",
        headers=auth(factory),
        json={"description": POSTING + "\n\nWe also use Kafka."},
    )

    assert read(client, factory, job_id)["is_stale"] is True


def test_editing_something_other_than_the_description_does_not(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    client.patch(f"{BASE}/{job_id}", headers=auth(factory), json={"notes": "Referred by Dana"})

    assert read(client, factory, job_id)["is_stale"] is False


# --- preservation -------------------------------------------------------------


def test_analysis_does_not_touch_the_description(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    job = client.get(f"{BASE}/{job_id}", headers=auth(factory)).json()["data"]

    assert job["description"] == POSTING


def test_analysis_does_not_touch_the_preserved_original(
    client: TestClient, factory: TokenFactory
) -> None:
    """``GOAL.md``: AI must never overwrite ``original_description``. The
    parser produced a title and a company, and neither may land here."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    source = client.get(f"{BASE}/{job_id}/source", headers=auth(factory)).json()["data"]

    assert source["original_description"] == POSTING


def test_analysis_does_not_overwrite_what_the_user_typed(
    client: TestClient, factory: TokenFactory
) -> None:
    """``jobs.role_family`` and ``jobs.seniority`` are the user's answers. The
    analysis has its own, in its own table, and better is not a licence to
    replace."""
    response = client.post(
        BASE,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": POSTING,
            "role_family": "Platform",
            "seniority": "MID",
        },
    )
    job_id = response.json()["data"]["id"]

    analyse(client, factory, job_id)

    job = client.get(f"{BASE}/{job_id}", headers=auth(factory)).json()["data"]

    assert job["role_family"] == "Platform"
    assert job["seniority"] == "MID"
    assert read(client, factory, job_id)["analysis"]["seniority"] == "SENIOR"


# --- failure ------------------------------------------------------------------


def test_a_failed_analysis_keeps_the_job(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    started = start(client, factory, job_id)

    with pytest.raises(AIError):
        run_pipeline(
            started["processing_job_id"],
            parse=AIError(AIFailureCode.PROVIDER_ERROR, "The provider is down."),
        )

    job = client.get(f"{BASE}/{job_id}", headers=auth(factory)).json()["data"]

    assert job["description"] == POSTING
    assert job["status"] == "ANALYSIS_FAILED"


def test_a_failed_analysis_is_distinguishable_from_a_failed_fetch(
    client: TestClient, factory: TokenFactory
) -> None:
    """FAILED is what the UI reads to offer a paste box. Telling someone to
    re-enter a description that is already there is the wrong recovery."""
    job_id = create_job(client, factory)
    started = start(client, factory, job_id)

    with pytest.raises(AIError):
        run_pipeline(
            started["processing_job_id"],
            parse=AIError(AIFailureCode.PROVIDER_ERROR, "The provider is down."),
        )

    job = client.get(f"{BASE}/{job_id}", headers=auth(factory)).json()["data"]
    assert job["status"] != "FAILED"


def test_a_failed_analysis_leaves_the_previous_version_intact(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    started = start(client, factory, job_id)
    with pytest.raises(AIError):
        run_pipeline(
            started["processing_job_id"],
            parse=AIError(AIFailureCode.RATE_LIMIT, "Slow down."),
        )

    data = read(client, factory, job_id)

    assert data["analysis"]["version"] == 1
    assert data["analysis"]["seniority"] == "SENIOR"


def test_a_retry_after_a_failure_succeeds(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    started = start(client, factory, job_id)

    with pytest.raises(AIError):
        run_pipeline(
            started["processing_job_id"],
            parse=AIError(AIFailureCode.TIMEOUT, "Took too long."),
        )

    analyse(client, factory, job_id)

    assert read(client, factory, job_id)["analysis"]["version"] == 1


def _runs_for(job_id: str) -> list[Any]:
    session = new_session()
    try:
        return list(
            session.execute(select(AIRun).where(AIRun.entity_id == uuid.UUID(job_id))).scalars()
        )
    finally:
        session.close()


def test_records_a_run_for_each_operation_of_a_successful_analysis(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    assert {run.operation for run in _runs_for(job_id)} == {"JOB_PARSE", "JOB_ANALYSIS"}


def test_a_wholly_failed_analysis_still_records_its_attempts(
    client: TestClient, factory: TokenFactory
) -> None:
    """DEV-016. A failed operation used to leave `ai_runs` empty, so the only
    evidence was a generic message on `processing_jobs` — and that is the case
    you most need the trace for, because it is the one that cost money without
    producing anything.
    """
    job_id = create_job(client, factory)
    started = start(client, factory, job_id)

    with pytest.raises(AIError):
        run_pipeline(
            started["processing_job_id"],
            parse=AIError(AIFailureCode.PROVIDER_ERROR, "The provider is down."),
        )

    runs = _runs_for(job_id)
    assert runs, "a failed parse recorded nothing at all"
    assert {run.operation for run in runs} == {"JOB_PARSE"}
    assert all(str(run.status) == "FAILED" for run in runs)
    assert all(run.failure_code == "PROVIDER_ERROR" for run in runs)


def test_those_attempts_survive_the_workers_rollback(
    client: TestClient, factory: TokenFactory
) -> None:
    """The subtlety that makes DEV-016 more than a missing `session.add`.

    `run_job_analysis` opens its failure handler with `session.rollback()`, so
    a trace that has only been flushed by the time the exception reaches it is
    discarded. Persisting them before the commit in `_mark_analysis_failed` is
    what makes them durable, and this asserts that rather than the flush.
    """
    job_id = create_job(client, factory)
    started = start(client, factory, job_id)

    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(started["processing_job_id"]))
        assert job is not None
        with pytest.raises(AIError):
            run_analysis(
                session,
                FakeLLMProvider([AIError(AIFailureCode.PROVIDER_ERROR, "down")]),
                build_router(
                    resume_parse_model="fake-model",
                    resume_parse_max_output_tokens=16000,
                    resume_parse_effort=None,
                ),
                job=job,
                max_input_chars=60_000,
                max_attempts=1,
            )
        # Exactly what the worker does next.
        session.rollback()
    finally:
        session.close()

    assert _runs_for(job_id), "the rollback discarded the trace"


# --- warnings -----------------------------------------------------------------


def test_tells_the_user_what_validation_corrected(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    warnings = read(client, factory, job_id)["analysis"]["warnings"]

    assert any("not in this posting" in w for w in warnings)
    assert any("preference" in w for w in warnings)


# --- ownership ----------------------------------------------------------------


def test_another_user_cannot_read_an_analysis(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(f"{BASE}/{job_id}/analysis", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_another_user_cannot_start_an_analysis(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)

    response = client.post(f"{BASE}/{job_id}/analysis", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_another_user_cannot_read_requirements(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    response = client.get(f"{BASE}/{job_id}/requirements", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_an_unauthenticated_request_is_rejected(client: TestClient, factory: TokenFactory) -> None:
    job_id = create_job(client, factory)

    assert client.get(f"{BASE}/{job_id}/analysis").status_code == 401
    assert client.post(f"{BASE}/{job_id}/analysis").status_code == 401
    assert client.get(f"{BASE}/{job_id}/requirements").status_code == 401


def test_rows_are_scoped_to_their_owner(client: TestClient, factory: TokenFactory) -> None:
    """Ownership is on the rows, not only on the routes: a query that forgot
    to scope would still return nothing across users."""
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    session = new_session()
    try:
        analysis = session.execute(select(JobAnalysis)).scalar_one()
        requirement = session.execute(select(JobRequirement).limit(1)).scalar_one()
    finally:
        session.close()

    assert requirement.user_id == analysis.user_id


# --- deletion -----------------------------------------------------------------


def test_deleting_a_job_takes_its_analysis_with_it(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = create_job(client, factory)
    analyse(client, factory, job_id)

    client.delete(f"{BASE}/{job_id}", headers=auth(factory))

    session = new_session()
    try:
        remaining = session.execute(select(func.count()).select_from(JobAnalysis)).scalar_one()
        requirements = session.execute(
            select(func.count()).select_from(JobRequirement)
        ).scalar_one()
    finally:
        session.close()

    assert remaining == 0
    assert requirements == 0
