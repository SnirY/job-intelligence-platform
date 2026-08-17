"""Job matching end to end, against a real database.

What these protect that the unit tests cannot:

- evidence really points at the career rows it claims to;
- history survives recalculation, with its own items and evidence;
- staleness is detected for each of the three things that can move;
- another user cannot read or start a match.
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

from jip_ai import build_router
from jip_ai.providers.fake import FakeLLMProvider
from jip_api.api.dependencies import get_dispatcher
from jip_api.application.jobs.analysis_pipeline import run_analysis
from jip_api.domain.matching.models import JobMatch, JobMatchEvidence, JobMatchItem
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


def analysed_job(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> str:
    """A job with a completed analysis, ready to match against."""
    created = client.post(
        JOBS,
        headers=auth(factory, subject),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": POSTING,
        },
    )
    assert created.status_code == 201, created.text
    job_id: str = created.json()["data"]["id"]

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

    return job_id


def add_skill(
    client: TestClient, factory: TokenFactory, name: str, subject: str = ALICE, **extra: Any
) -> dict[str, Any]:
    response = client.post(
        f"{CAREER}/skills",
        headers=auth(factory, subject),
        json={"name": name, "category": "LANGUAGE", **extra},
    )
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def set_years(client: TestClient, factory: TokenFactory, years: int, subject: str = ALICE) -> None:
    response = client.patch(
        f"{CAREER}/profile",
        headers=auth(factory, subject),
        json={"years_of_experience": years},
    )
    assert response.status_code == 200, response.text


def match(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, expect: int = 200
) -> dict[str, Any]:
    response = client.post(f"{JOBS}/{job_id}/match", headers=auth(factory, subject))
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def read(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"{JOBS}/{job_id}/match", headers=auth(factory, subject), params=params or None
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


# --- preconditions ------------------------------------------------------------


def test_a_job_with_no_analysis_cannot_be_matched(
    client: TestClient, factory: TokenFactory
) -> None:
    created = client.post(
        JOBS,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Backend Engineer",
            "description": POSTING,
        },
    )
    job_id = created.json()["data"]["id"]

    body = match(client, factory, job_id, expect=409)

    assert "not been analysed" in body["error"]["message"]


def test_an_empty_profile_does_not_prevent_a_match(
    client: TestClient, factory: TokenFactory
) -> None:
    """The goal is explicit that an incomplete profile must not be penalised,
    and a match full of NO_EVIDENCE tells the user exactly what to fill in."""
    job_id = analysed_job(client, factory)

    data = match(client, factory, job_id)

    assert data["match"] is not None
    assert data["match"]["overall_score"] is None
    assert data["match"]["alignment_label"] == "Not enough profile data"


def test_reports_whether_a_match_can_be_started(client: TestClient, factory: TokenFactory) -> None:
    created = client.post(
        JOBS,
        headers=auth(factory),
        json={"import_method": "MANUAL", "title": "Platform Engineer"},
    )
    unanalysed = created.json()["data"]["id"]
    analysed = analysed_job(client, factory)

    assert read(client, factory, unanalysed)["can_match"] is False
    assert read(client, factory, unanalysed)["blocking_reason"]
    assert read(client, factory, analysed)["can_match"] is True


def test_reports_no_match_for_a_job_that_has_none(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)

    data = read(client, factory, job_id)

    assert data["match"] is None
    assert data["items"] == []
    assert data["available_versions"] == []


# --- matching -----------------------------------------------------------------


def test_every_requirement_gets_exactly_one_item(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    data = match(client, factory, job_id)

    assert len(data["items"]) == len(PARSE_RESPONSE["requirements"])
    assert len({item["requirement_id"] for item in data["items"]}) == len(data["items"])


def test_every_item_carries_the_documented_fields(
    client: TestClient, factory: TokenFactory
) -> None:
    """docs/10-api-contracts.md names all seven."""
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    for item in match(client, factory, job_id)["items"]:
        assert item["requirement_id"]
        assert item["status"]
        assert item["score"] is not None
        assert item["weight"] is not None
        assert item["confidence"] is not None
        assert item["explanation"].strip()
        assert "evidence" in item


def test_a_held_skill_produces_evidence_pointing_at_the_career_row(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)
    created = add_skill(client, factory, "Python")

    data = match(client, factory, job_id)
    python = next(i for i in data["items"] if i["explanation"].startswith("Python"))

    assert python["evidence"]
    assert python["evidence"][0]["evidence_type"] == "SKILL"
    assert python["evidence"][0]["entity_id"] == created["id"]


def test_transferable_evidence_never_becomes_a_direct_match(
    client: TestClient, factory: TokenFactory
) -> None:
    """The posting wants Spring Boot; the profile has FastAPI."""
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "FastAPI", category="FRAMEWORK")

    data = match(client, factory, job_id)
    statuses = {i["status"] for i in data["items"]}

    assert "TRANSFERABLE_MATCH" in statuses
    spring = next(i for i in data["items"] if "Spring Boot" in i["explanation"])
    assert spring["status"] == "TRANSFERABLE_MATCH"


def test_work_authorisation_is_unknown_rather_than_a_gap(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    data = match(client, factory, job_id)
    statuses = [i["status"] for i in data["items"]]

    assert "UNKNOWN" in statuses


def test_a_core_gap_blocks_and_caps(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    set_years(client, factory, 8)

    data = match(client, factory, job_id)

    assert data["match"]["has_blockers"] is True
    assert any(item["is_blocker"] for item in data["items"])


def test_the_score_is_never_presented_as_a_hiring_chance(
    client: TestClient, factory: TokenFactory
) -> None:
    """docs/05-ai-and-matching.md is categorical about this."""
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    label = match(client, factory, job_id)["match"]["alignment_label"]

    assert "alignment" in label.lower() or "profile data" in label.lower()


def test_the_recommendation_is_separate_from_the_score(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    payload = match(client, factory, job_id)["match"]

    assert payload["recommendation"]
    assert payload["recommendation_reasons"]


def test_category_scores_are_exposed(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    set_years(client, factory, 8)

    categories = match(client, factory, job_id)["match"]["category_scores"]

    assert "TECHNICAL" in categories
    assert "EXPERIENCE" in categories


# --- versioning and history ---------------------------------------------------


def test_recalculating_adds_a_version(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    match(client, factory, job_id)
    second = match(client, factory, job_id)

    assert second["match"]["version"] == 2
    assert second["available_versions"] == [2, 1]


def test_the_previous_version_stays_readable(client: TestClient, factory: TokenFactory) -> None:
    """History is the reason versions exist. A user who disagrees with today's
    reading should still be able to see last week's."""
    job_id = analysed_job(client, factory)
    match(client, factory, job_id)

    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    first = read(client, factory, job_id, version=1)["match"]
    second = read(client, factory, job_id, version=2)["match"]

    assert first["overall_score"] is None
    assert second["overall_score"] is not None


def test_each_version_keeps_its_own_items(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    match(client, factory, job_id)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    first_statuses = {i["status"] for i in read(client, factory, job_id, version=1)["items"]}
    second_statuses = {i["status"] for i in read(client, factory, job_id, version=2)["items"]}

    assert first_statuses != second_statuses


def test_every_match_records_all_three_versions(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")

    payload = match(client, factory, job_id)["match"]

    assert payload["analysis_version"] == 1
    assert payload["engine_version"]

    session = new_session()
    try:
        stored = session.execute(select(JobMatch)).scalar_one()
        assert stored.profile_fingerprint
    finally:
        session.close()


def test_an_unknown_version_is_not_found(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    match(client, factory, job_id)

    response = client.get(f"{JOBS}/{job_id}/match", headers=auth(factory), params={"version": 9})

    assert response.status_code == 404


# --- staleness ----------------------------------------------------------------


def test_a_fresh_match_is_not_stale(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    assert read(client, factory, job_id)["is_stale"] is False


def test_changing_the_profile_makes_the_match_stale(
    client: TestClient, factory: TokenFactory
) -> None:
    """docs/02-user-flows.md Flow 12. Detected by recomputing the fingerprint
    rather than by a flag somebody has to remember to set."""
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    add_skill(client, factory, "Rust")

    data = read(client, factory, job_id)
    assert data["is_stale"] is True
    assert any("profile has changed" in reason for reason in data["stale_reasons"])


# --- the score, as the list sees it -------------------------------------------


def listed(client: TestClient, factory: TokenFactory, job_id: str) -> dict[str, Any]:
    """One job, read back from the list rather than from its own screen."""
    response = client.get(JOBS, headers=auth(factory))
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["data"] if row["id"] == job_id]
    assert len(rows) == 1, f"expected {job_id} in the list once, got {len(rows)}"
    return dict(rows[0])


def test_the_list_carries_the_score_and_the_word_that_goes_with_it(
    client: TestClient, factory: TokenFactory
) -> None:
    """The figure has to reach the screen a user scans, not only the one they open.

    ``docs/05-ai-and-matching.md`` requires the number to travel beside the word
    *alignment*, so the label ships with it rather than being reassembled by
    whichever screen renders the figure.
    """
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    computed = match(client, factory, job_id)["match"]

    row = listed(client, factory, job_id)

    assert row["score"] == computed["overall_score"]
    assert row["alignment_label"] == computed["alignment_label"]
    assert row["is_stale"] is False


def test_an_unmatched_job_lists_a_null_score_and_never_a_zero(
    client: TestClient, factory: TokenFactory
) -> None:
    """Invariant 2, at list scale.

    Zero is a claim about the candidate; null is a claim about our data. A job
    nobody has matched has not scored badly, and the list is exactly where that
    distinction is cheapest to lose — twenty rows of ``0`` would read as twenty
    verdicts.
    """
    job_id = analysed_job(client, factory)

    row = listed(client, factory, job_id)

    assert row["score"] is None
    assert row["alignment_label"] is None
    assert row["is_stale"] is False
    assert row["status_counts"] == {}
    assert row["total_requirements"] == 0


def test_the_list_carries_enough_to_draw_a_coverage_summary(
    client: TestClient, factory: TokenFactory
) -> None:
    """The counts and their denominator, without fetching the requirements.

    ``status_counts`` exists on the match for exactly this: a summary drawn per
    row would otherwise cost one query per row to rebuild from items.

    The denominator travels with the counts. A coverage figure without one is a
    percentage in disguise, and `docs/07` is explicit that a bare percentage is
    what this product does not ship.
    """
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    computed = match(client, factory, job_id)["match"]

    row = listed(client, factory, job_id)

    assert row["status_counts"] == computed["status_counts"]
    assert row["total_requirements"] == computed["total_requirements"]
    assert row["total_requirements"] > 0
    assert sum(row["status_counts"].values()) <= row["total_requirements"]


def test_the_list_reports_a_score_that_has_fallen_out_of_date(
    client: TestClient, factory: TokenFactory
) -> None:
    """A stale score is still shown, and still says it is stale.

    Withholding it would be worse: the number was true of the inputs it was
    computed from, and the screen's job is to say so rather than to hide it.
    """
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    add_skill(client, factory, "Rust")

    row = listed(client, factory, job_id)

    assert row["score"] is not None
    assert row["is_stale"] is True


def test_reanalysing_the_job_makes_the_match_stale(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    # A second analysis of the same posting; the match now points at v1.
    started = client.post(f"{JOBS}/{job_id}/analysis", headers=auth(factory))
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

    data = read(client, factory, job_id)
    assert data["is_stale"] is True
    assert any("re-read" in reason for reason in data["stale_reasons"])


def test_recalculating_clears_staleness(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)
    add_skill(client, factory, "Rust")

    assert read(client, factory, job_id)["is_stale"] is True
    match(client, factory, job_id)
    assert read(client, factory, job_id)["is_stale"] is False


# --- items endpoint -----------------------------------------------------------


def test_items_are_served_from_their_own_endpoint(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    response = client.get(f"{JOBS}/{job_id}/match/items", headers=auth(factory))

    assert response.status_code == 200
    assert len(response.json()["data"]) == len(PARSE_RESPONSE["requirements"])


def test_items_can_be_filtered_by_status(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    response = client.get(
        f"{JOBS}/{job_id}/match/items", headers=auth(factory), params={"status": "UNKNOWN"}
    )

    assert all(item["status"] == "UNKNOWN" for item in response.json()["data"])


def test_the_items_endpoint_is_empty_before_a_match(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = analysed_job(client, factory)

    response = client.get(f"{JOBS}/{job_id}/match/items", headers=auth(factory))

    assert response.status_code == 200
    assert response.json()["data"] == []


# --- determinism against the database -----------------------------------------


def test_two_runs_over_unchanged_data_agree(client: TestClient, factory: TokenFactory) -> None:
    """The same guarantee as the unit test, but through the real loader — a
    non-deterministic query ordering would show up here and nowhere else."""
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    set_years(client, factory, 8)

    first = match(client, factory, job_id)["match"]
    second = match(client, factory, job_id)["match"]

    assert first["overall_score"] == second["overall_score"]
    assert first["recommendation"] == second["recommendation"]
    assert first["status_counts"] == second["status_counts"]
    assert first["category_scores"] == second["category_scores"]
    assert first["confidence"] == second["confidence"]


# --- ownership ----------------------------------------------------------------


def test_another_user_cannot_read_a_match(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    assert client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, BOB)).status_code == 404


def test_another_user_cannot_start_a_match(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)

    assert client.post(f"{JOBS}/{job_id}/match", headers=auth(factory, BOB)).status_code == 404


def test_another_user_cannot_read_match_items(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    response = client.get(f"{JOBS}/{job_id}/match/items", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_unauthenticated_requests_are_rejected(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)

    assert client.get(f"{JOBS}/{job_id}/match").status_code == 401
    assert client.post(f"{JOBS}/{job_id}/match").status_code == 401
    assert client.get(f"{JOBS}/{job_id}/match/items").status_code == 401


def test_a_match_never_draws_on_another_users_profile(
    client: TestClient, factory: TokenFactory
) -> None:
    """The evidence loader is scoped through owned(); this proves it, because
    a leak here would silently improve someone's score."""
    add_skill(client, factory, "Python", subject=BOB)
    add_skill(client, factory, "Rust", subject=BOB)

    job_id = analysed_job(client, factory)
    data = match(client, factory, job_id)

    assert data["match"]["overall_score"] is None


# --- deletion -----------------------------------------------------------------


def test_deleting_a_job_takes_its_match_with_it(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    add_skill(client, factory, "Python")
    match(client, factory, job_id)

    client.delete(f"{JOBS}/{job_id}", headers=auth(factory))

    session = new_session()
    try:
        assert session.execute(select(func.count()).select_from(JobMatch)).scalar_one() == 0
        assert session.execute(select(func.count()).select_from(JobMatchItem)).scalar_one() == 0
        assert session.execute(select(func.count()).select_from(JobMatchEvidence)).scalar_one() == 0
    finally:
        session.close()
