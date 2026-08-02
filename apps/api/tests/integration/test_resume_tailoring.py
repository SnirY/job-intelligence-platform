"""Tailoring and rendering end to end, against a real database.

Slices 2-6 of Phase 7. What these protect that a unit test cannot:

- selection really draws on ``JobMatchEvidence`` and really withholds
  unverified facts;
- a strategy is produced without AI at all, because AI failure must never
  block manual use (``docs/02-user-flows.md``);
- an invented number survives the whole round trip as BLOCKED;
- only accepted and edited suggestions reach the finalised version;
- nothing here writes to ``job_matches``, ``job_match_items``, or
  ``job_match_evidence``;
- User A cannot download User B's resume, which
  ``docs/11-engineering-standards.md`` requires by name.
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
from jip_api.application.resumes import tailoring_service as tailoring
from jip_api.domain.career.skills import UserSkill
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import JobMatch, JobMatchEvidence, JobMatchItem
from jip_api.domain.processing.models import ProcessingJob
from jip_api.domain.resumes.models import ResumeVersion
from jip_api.domain.resumes.tailoring import ResumeStrategy
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
JOBS = "/api/v1/jobs"
RESUMES = "/api/v1/resumes"
VERSIONS = "/api/v1/resume-versions"
STRATEGIES = "/api/v1/resume-strategies"
SUGGESTIONS = "/api/v1/resume-suggestions"
CAREER = "/api/v1/career"
ALICE = "user_alice"
BOB = "user_bob"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- Strong Python\n"
    "- 5+ years of backend engineering experience\n\n"
    "You will design and build our routing services."
)

PARSE_RESPONSE: dict[str, Any] = {
    "summary": "Senior backend role.",
    "requirements": [
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
            "normalized_text": "5+ years backend engineering",
            "requirement_type": "EXPERIENCE",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "5+ years of backend engineering experience",
            "confidence": 95,
            "years_min": 5,
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
    "seniority_reasoning": "Asks for 5+ years.",
    "summary": "A senior backend role.",
}

STRATEGY_RESPONSE: dict[str, Any] = {
    "summary": "Lead with the Python routing work.",
    "emphasize": ["Python", "Routing services"],
    "reduce": ["Unrelated frontend work"],
    "reorder_note": "Put skills first.",
    "priority_projects": [],
    "missing_evidence": ["Your mentoring achievement is not on this resume."],
    "career_gaps": ["No Kubernetes anywhere in your profile."],
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
        # AI is left unconfigured by the autouse `no_live_ai` fixture in
        # conftest, which is what makes "a strategy is produced without AI"
        # mean anything. Where these tests need a model they drive the service
        # directly with a fake.

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


# --- helpers ------------------------------------------------------------------


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def fake_router() -> Any:
    return build_router(
        resume_parse_model="fake-model",
        resume_parse_max_output_tokens=16000,
        resume_parse_effort=None,
    )


def matched_job(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> str:
    """A job analysed, with a profile behind it, and matched."""
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

    session = new_session()
    try:
        processing = session.get(
            ProcessingJob, uuid.UUID(started.json()["data"]["processing_job_id"])
        )
        assert processing is not None
        run_analysis(
            session,
            FakeLLMProvider([PARSE_RESPONSE, ANALYSIS_RESPONSE]),
            fake_router(),
            job=processing,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()

    add_skill(client, factory, "Python", subject)
    set_years(client, factory, 7, subject)

    matched = client.post(f"{JOBS}/{job_id}/match", headers=auth(factory, subject))
    assert matched.status_code == 200, matched.text
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
        f"{CAREER}/profile", headers=auth(factory, subject), json={"years_of_experience": years}
    )
    assert response.status_code == 200, response.text


def plan(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, expect: int = 201
) -> dict[str, Any]:
    response = client.post(f"{JOBS}/{job_id}/resume-strategies", headers=auth(factory, subject))
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def read_plan(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, expect: int = 200
) -> dict[str, Any]:
    response = client.get(f"{JOBS}/{job_id}/resume-strategies", headers=auth(factory, subject))
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def draft_with(
    client: TestClient, factory: TokenFactory, *lines: str, subject: str = ALICE
) -> tuple[str, str]:
    """A resume with one experience section, returning (resume id, version id)."""
    resume = client.post(
        RESUMES, headers=auth(factory, subject), json={"title": "Backend", "family": "BASE"}
    )
    assert resume.status_code == 201, resume.text
    resume_id: str = resume.json()["data"]["id"]

    version = client.post(
        f"{RESUMES}/{resume_id}/versions", headers=auth(factory, subject), json={"label": "First"}
    )
    assert version.status_code == 201, version.text
    version_id: str = version.json()["data"]["id"]

    saved = client.put(
        f"{VERSIONS}/{version_id}/content",
        headers=auth(factory, subject),
        json={
            "sections": [
                {
                    "kind": "EXPERIENCE",
                    "display_order": 0,
                    "items": [
                        {
                            "text": line,
                            "heading": "Backend Engineer, Verdant",
                            "display_order": order,
                        }
                        for order, line in enumerate(lines)
                    ],
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    return resume_id, version_id


def suggest(
    client: TestClient,
    factory: TokenFactory,
    strategy_id: str,
    version_id: str,
    candidates: list[dict[str, Any]],
    subject: str = ALICE,
) -> None:
    """Run the rewrite stage with a scripted model response.

    Called directly rather than through the endpoint, the same way
    ``test_job_match.py`` drives analysis: the route resolves its provider from
    settings, and there is no AI key in the test environment.
    """
    session = new_session()
    try:
        strategy = session.get(ResumeStrategy, uuid.UUID(strategy_id))
        assert strategy is not None
        version = session.get(ResumeVersion, uuid.UUID(version_id))
        assert version is not None
        job = session.get(Job, strategy.job_id)
        assert job is not None

        tailoring.create_suggestions(
            session,
            FakeLLMProvider([{"suggestions": candidates}]),
            fake_router(),
            user_id=strategy.user_id,
            strategy=strategy,
            version=version,
            job=job,
            max_attempts=1,
        )
        strategy.version_id = version.id
        session.commit()
    finally:
        session.close()


def item_ids(client: TestClient, factory: TokenFactory, version_id: str) -> list[str]:
    response = client.get(f"{VERSIONS}/{version_id}", headers=auth(factory))
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return [item["id"] for section in data["sections"] for item in section["items"]]


# --- preconditions ------------------------------------------------------------


def test_a_job_with_no_match_cannot_be_tailored(client: TestClient, factory: TokenFactory) -> None:
    created = client.post(
        JOBS, headers=auth(factory), json={"import_method": "MANUAL", "title": "Platform Engineer"}
    )
    job_id = created.json()["data"]["id"]

    view = read_plan(client, factory, job_id)
    assert view["strategy"] is None
    assert view["can_create"] is False
    assert "matched" in (view["blocking_reason"] or "")

    body = plan(client, factory, job_id, expect=409)
    assert "matched" in body["error"]["message"]


def test_a_strategy_is_produced_without_ai(client: TestClient, factory: TokenFactory) -> None:
    """No API key is configured in the test environment, so this is the
    AI-unavailable path: selection is deterministic and still runs."""
    job_id = matched_job(client, factory)

    data = plan(client, factory, job_id)

    assert data["strategy"]["version"] == 1
    assert data["strategy"]["model"] is None
    assert data["strategy"]["selection"]["sections"]


def test_selection_draws_on_the_match_evidence(client: TestClient, factory: TokenFactory) -> None:
    """The skill reached the page because a requirement's evidence pointed at
    it, not because it was on the profile."""
    job_id = matched_job(client, factory)

    data = plan(client, factory, job_id)

    sections = {section["kind"]: section for section in data["strategy"]["selection"]["sections"]}
    assert "SKILLS" in sections
    texts = [item["text"] for item in sections["SKILLS"]["items"]]
    assert "Python" in texts
    assert all(item["reasons"] for item in sections["SKILLS"]["items"])


def test_an_unverified_fact_is_withheld_and_reported(
    client: TestClient, factory: TokenFactory
) -> None:
    """``VerificationStatus`` is the gate. An unverified skill is set aside
    rather than dropped, so the user can confirm it and make it usable."""
    job_id = matched_job(client, factory)

    session = new_session()
    try:
        skill = session.execute(select(UserSkill)).scalars().first()
        assert skill is not None
        skill.verification_status = "AI_EXTRACTED"
        session.commit()
    finally:
        session.close()

    # Rematch so the item verdicts reflect the weaker verification.
    client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))
    data = plan(client, factory, job_id)

    withheld = data["strategy"]["selection"].get("withheld_unverified", [])
    selected = [
        item["text"]
        for section in data["strategy"]["selection"]["sections"]
        for item in section["items"]
    ]
    assert "Python" not in selected
    assert any(row["text"] == "Python" for row in withheld)


def test_tailoring_never_writes_to_the_match_tables(
    client: TestClient, factory: TokenFactory
) -> None:
    """The invariant the phase was given: the matching engine is deterministic
    and Phase 7 is a consumer of it."""
    job_id = matched_job(client, factory)

    session = new_session()
    try:
        before = tuple(
            session.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (JobMatch, JobMatchItem, JobMatchEvidence)
        )
    finally:
        session.close()

    plan(client, factory, job_id)
    plan(client, factory, job_id)

    session = new_session()
    try:
        after = tuple(
            session.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (JobMatch, JobMatchItem, JobMatchEvidence)
        )
    finally:
        session.close()

    assert before == after


def test_planning_again_creates_a_new_version(client: TestClient, factory: TokenFactory) -> None:
    job_id = matched_job(client, factory)

    plan(client, factory, job_id)
    second = plan(client, factory, job_id)

    assert second["strategy"]["version"] == 2
    assert read_plan(client, factory, job_id)["strategy"]["version"] == 2


# --- suggestions and truth validation -----------------------------------------


def test_an_invented_number_is_stored_blocked(client: TestClient, factory: TokenFactory) -> None:
    """The rule ``docs/06-resume-engine.md`` states without qualification,
    surviving the whole round trip rather than only the validator."""
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Improved the performance of the routing service.")
    [item] = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [
            {
                "item_id": item,
                "suggested_text": "Improved routing service performance by 40%.",
                "rationale": "Quantified.",
                "kind": "REWRITE",
            }
        ],
    )

    view = read_plan(client, factory, job_id)
    [suggestion] = view["suggestions"]
    assert suggestion["is_blocked"] is True
    assert suggestion["risk"] == "HIGH"
    assert suggestion["requires_review"] is True
    assert view["blocked_count"] == 1
    assert any(claim["status"] == "BLOCKED" for claim in suggestion["claims"])


def test_a_suggestion_for_an_unknown_item_is_ignored(
    client: TestClient, factory: TokenFactory
) -> None:
    """An id we never sent would otherwise be a way to write to a line the user
    does not own."""
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Built the routing service.")

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [
            {
                "item_id": str(uuid.uuid4()),
                "suggested_text": "Anything at all.",
                "rationale": "",
                "kind": "REWRITE",
            }
        ],
    )

    assert read_plan(client, factory, job_id)["suggestions"] == []


def test_a_blocked_suggestion_can_still_be_accepted(
    client: TestClient, factory: TokenFactory
) -> None:
    """The system asks rather than overrules: the user may know the figure is
    real. What it will not do is apply it without asking."""
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Improved the routing service.")
    [item] = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [
            {
                "item_id": item,
                "suggested_text": "Improved the routing service by 40%.",
                "rationale": "",
                "kind": "REWRITE",
            }
        ],
    )
    [suggestion] = read_plan(client, factory, job_id)["suggestions"]

    accepted = client.post(f"{SUGGESTIONS}/{suggestion['id']}/accept", headers=auth(factory))

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "ACCEPTED"
    assert accepted.json()["data"]["is_blocked"] is True


def test_editing_keeps_both_what_was_proposed_and_what_was_taken(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Built the routing service.")
    [item] = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [
            {
                "item_id": item,
                "suggested_text": "Architected the routing service.",
                "rationale": "",
                "kind": "REWRITE",
            }
        ],
    )
    [suggestion] = read_plan(client, factory, job_id)["suggestions"]

    edited = client.post(
        f"{SUGGESTIONS}/{suggestion['id']}/edit",
        headers=auth(factory),
        json={"text": "Built and maintained the routing service."},
    )

    assert edited.status_code == 200, edited.text
    data = edited.json()["data"]
    assert data["status"] == "EDITED"
    assert data["suggested_text"] == "Architected the routing service."
    assert data["final_text"] == "Built and maintained the routing service."


# --- finalising ---------------------------------------------------------------


def test_only_decided_suggestions_are_applied(client: TestClient, factory: TokenFactory) -> None:
    """Silence is not consent. A pending suggestion leaves its line alone."""
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    resume_id, version_id = draft_with(
        client,
        factory,
        "Built the routing service.",
        "Mentored two junior engineers.",
        "Wrote the deployment scripts.",
    )
    first, second, third = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [
            {"item_id": first, "suggested_text": "Built routing services.", "kind": "REWRITE"},
            {"item_id": second, "suggested_text": "Mentored engineers.", "kind": "SHORTEN"},
            {"item_id": third, "suggested_text": "Owned deployment.", "kind": "REWRITE"},
        ],
    )
    by_item = {row["item_id"]: row for row in read_plan(client, factory, job_id)["suggestions"]}

    client.post(f"{SUGGESTIONS}/{by_item[first]['id']}/accept", headers=auth(factory))
    client.post(f"{SUGGESTIONS}/{by_item[second]['id']}/reject", headers=auth(factory))
    # The third is left pending on purpose.

    finalized = client.post(
        f"{STRATEGIES}/{strategy['id']}/finalize",
        headers=auth(factory),
        json={"resume_id": resume_id, "label": "Tailored"},
    )

    assert finalized.status_code == 200, finalized.text
    result = finalized.json()["data"]
    assert result["applied"] == 1

    detail = client.get(f"{VERSIONS}/{result['version_id']}", headers=auth(factory))
    texts = [
        item["text"] for section in detail.json()["data"]["sections"] for item in section["items"]
    ]
    assert "Built routing services." in texts
    assert "Mentored two junior engineers." in texts
    assert "Wrote the deployment scripts." in texts


def test_finalising_writes_a_new_version_and_keeps_the_reviewed_one(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    resume_id, version_id = draft_with(client, factory, "Built the routing service.")
    [item] = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [{"item_id": item, "suggested_text": "Built routing services.", "kind": "REWRITE"}],
    )
    [suggestion] = read_plan(client, factory, job_id)["suggestions"]
    client.post(f"{SUGGESTIONS}/{suggestion['id']}/accept", headers=auth(factory))

    result = client.post(
        f"{STRATEGIES}/{strategy['id']}/finalize",
        headers=auth(factory),
        json={"resume_id": resume_id},
    ).json()["data"]

    assert result["version_id"] != version_id
    assert result["version"] == 2

    original = client.get(f"{VERSIONS}/{version_id}", headers=auth(factory))
    assert (
        original.json()["data"]["sections"][0]["items"][0]["text"] == "Built the routing service."
    )

    created = client.get(f"{VERSIONS}/{result['version_id']}", headers=auth(factory))
    assert created.json()["data"]["parent_version_id"] == version_id


# --- rendering ----------------------------------------------------------------


def test_a_version_renders_as_printable_html(client: TestClient, factory: TokenFactory) -> None:
    _, version_id = draft_with(client, factory, "Built the routing service.")

    response = client.get(f"{VERSIONS}/{version_id}/render", headers=auth(factory))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "@page" in response.text
    assert "Built the routing service." in response.text


def test_rendered_text_is_escaped(client: TestClient, factory: TokenFactory) -> None:
    """Resume text is user input on our own origin. Rendering it as markup
    would be handing a script tag a page to run on."""
    _, version_id = draft_with(client, factory, "Built <script>alert(1)</script> services.")

    response = client.get(f"{VERSIONS}/{version_id}/render", headers=auth(factory))

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_one_user_cannot_download_another_users_resume(
    client: TestClient, factory: TokenFactory
) -> None:
    """Required by name in ``docs/11-engineering-standards.md``. 404 rather
    than 403: distinguishing "not yours" from "does not exist" is an
    enumeration oracle."""
    _, version_id = draft_with(client, factory, "Built the routing service.")

    response = client.get(f"{VERSIONS}/{version_id}/render", headers=auth(factory, BOB))

    assert response.status_code == 404, response.text


def test_one_user_cannot_read_another_users_strategy(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = matched_job(client, factory)
    plan(client, factory, job_id)

    response = client.get(f"{JOBS}/{job_id}/resume-strategies", headers=auth(factory, BOB))

    assert response.status_code == 404, response.text


def test_one_user_cannot_decide_another_users_suggestion(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Built the routing service.")
    [item] = item_ids(client, factory, version_id)

    suggest(
        client,
        factory,
        strategy["id"],
        version_id,
        [{"item_id": item, "suggested_text": "Built routing services.", "kind": "REWRITE"}],
    )
    [suggestion] = read_plan(client, factory, job_id)["suggestions"]

    response = client.post(f"{SUGGESTIONS}/{suggestion['id']}/accept", headers=auth(factory, BOB))

    assert response.status_code == 404, response.text


def test_a_run_that_proposed_nothing_is_distinguishable_from_no_run(
    client: TestClient, factory: TokenFactory
) -> None:
    """Stage 2.8.6, and the reason the walkthrough could not read its own result.

    An empty list is a legitimate answer: the rewriter is told to leave a good
    line alone, and to return nothing when nothing needs changing. The view
    reported that identically to a strategy nobody had generated for, so a
    completed run looked like a button that had not been pressed.

    Read from `ai_runs`, which is written on both the success and failure paths,
    so it cannot disagree with what actually happened.
    """
    job_id = matched_job(client, factory)
    strategy = plan(client, factory, job_id)["strategy"]
    _, version_id = draft_with(client, factory, "Improved the routing service.")

    before = read_plan(client, factory, job_id)
    assert before["suggestions"] == []
    assert before["suggestions_generated"] is False

    # The model answers, and answers with nothing.
    suggest(client, factory, strategy["id"], version_id, [])

    after = read_plan(client, factory, job_id)
    assert after["suggestions"] == []
    assert after["suggestions_generated"] is True
