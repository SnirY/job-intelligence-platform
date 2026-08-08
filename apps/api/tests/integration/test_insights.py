"""Career insights, against a real database.

Phase 10 is built on counts because DEV-026 found importance moving on
unchanged input, so what these protect is mostly arithmetic: that a job counts
once however many times it was read, that a percentage carries the sample it
came from, and that a skill the profile does not answer is called a gap for the
right reason.

Also protected: the two endpoints `docs/10` lists and this phase deliberately
does not serve. A 404 there is the design, not an omission, and a later change
that quietly adds an empty one should fail here.
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
from jip_api.application.insights.demand import TOP_SKILLS
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
INSIGHTS = "/api/v1/insights"
JOBS = "/api/v1/jobs"
CAREER = "/api/v1/career"
APPLICATIONS = "/api/v1/applications"
ALICE = "user_alice"
BOB = "user_bob"

POSTING = (
    "Senior Backend Engineer at Verdant Logistics.\n\n"
    "Requirements:\n"
    "- Strong Python\n"
    "- Rust for the routing core\n"
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
            "normalized_text": "Rust",
            "requirement_type": "TECHNICAL_SKILL",
            "importance": "REQUIRED",
            "explicitness": "EXPLICIT",
            "source_text": "Rust for the routing core",
            "confidence": 92,
            "skill_name": "Rust",
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


def get(client: TestClient, factory: TokenFactory, path: str, subject: str = ALICE) -> Any:
    response = client.get(f"{INSIGHTS}{path}", headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def analysed_job(
    client: TestClient, factory: TokenFactory, subject: str = ALICE, *, title: str = "Backend"
) -> str:
    created = client.post(
        JOBS,
        headers=auth(factory, subject),
        json={"import_method": "PASTED_DESCRIPTION", "title": title, "description": POSTING},
    )
    assert created.status_code == 201, created.text
    job_id: str = created.json()["data"]["id"]
    analyse(client, factory, job_id, subject)
    return job_id


def analyse(
    client: TestClient,
    factory: TokenFactory,
    job_id: str,
    subject: str = ALICE,
    *,
    parse: dict[str, Any] | None = None,
) -> None:
    """Run the real pipeline with a scripted provider.

    ``parse`` overrides what the posting is read as, so two jobs can ask for
    different things — which is what makes a percentage worth asserting.
    """
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
            FakeLLMProvider([parse or PARSE_RESPONSE, ANALYSIS_RESPONSE]),
            router,
            job=processing,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()


def add_skill(client: TestClient, factory: TokenFactory, name: str, subject: str = ALICE) -> None:
    response = client.post(
        f"{CAREER}/skills",
        headers=auth(factory, subject),
        json={"name": name, "category": "LANGUAGE"},
    )
    assert response.status_code == 201, response.text


# --- an account with nothing in it --------------------------------------------


def test_a_new_account_gets_an_empty_report(client: TestClient, factory: TokenFactory) -> None:
    """200 with nothing in it, not a 404. There is no missing resource — the
    user has not saved a job yet, and that is a state the screen describes."""
    data = get(client, factory, "/skills/demand")

    assert data["analysed_jobs"] == 0
    assert data["skills"] == []
    assert data["above_threshold"] is False


def test_a_saved_but_unanalysed_job_is_not_in_the_denominator(
    client: TestClient, factory: TokenFactory
) -> None:
    """It has no requirements, so counting it would deflate every percentage by
    the number of jobs sitting in the queue."""
    client.post(
        JOBS,
        headers=auth(factory),
        json={"import_method": "PASTED_DESCRIPTION", "title": "Waiting", "description": POSTING},
    )

    assert get(client, factory, "/skills/demand")["analysed_jobs"] == 0


# --- demand -------------------------------------------------------------------


def test_a_skill_the_posting_asks_for_appears(client: TestClient, factory: TokenFactory) -> None:
    analysed_job(client, factory)

    data = get(client, factory, "/skills/demand")

    assert data["analysed_jobs"] == 1
    assert {skill["name"] for skill in data["skills"]} == {"Python", "Rust"}
    assert all(skill["share"] == 100 for skill in data["skills"])


def test_re_reading_a_job_does_not_count_it_twice(
    client: TestClient, factory: TokenFactory
) -> None:
    """The bug this nearly shipped with.

    Requirements are written per analysis version and every version is kept, so
    one job read three times holds three full sets. Counting them all would
    report a posting three times for having been re-read three times — and the
    importance breakdown, which is per row, would triple with it.
    """
    job_id = analysed_job(client, factory)
    analyse(client, factory, job_id)
    analyse(client, factory, job_id)

    data = get(client, factory, "/skills/demand")

    assert data["analysed_jobs"] == 1
    python = next(skill for skill in data["skills"] if skill["name"] == "Python")
    assert python["jobs"] == 1
    assert sum(python["importance"].values()) == 1


def test_the_share_is_a_percentage_of_analysed_jobs(
    client: TestClient, factory: TokenFactory
) -> None:
    """One of two postings asking for something is 50%, and the arithmetic has
    to survive a skill that only one of them names."""
    analysed_job(client, factory, title="First")

    created = client.post(
        JOBS,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Second",
            "description": "A Kubernetes platform role.",
        },
    )
    assert created.status_code == 201, created.text
    analyse(
        client,
        factory,
        created.json()["data"]["id"],
        parse={
            "summary": "Platform role.",
            "requirements": [
                {
                    "normalized_text": "Kubernetes",
                    "requirement_type": "TECHNICAL_SKILL",
                    "importance": "REQUIRED",
                    "explicitness": "EXPLICIT",
                    "source_text": "A Kubernetes platform role.",
                    "confidence": 90,
                    "skill_name": "Kubernetes",
                }
            ],
            "responsibilities": [],
        },
    )

    data = get(client, factory, "/skills/demand")

    assert data["analysed_jobs"] == 2
    by_name = {skill["name"]: skill for skill in data["skills"]}
    assert by_name["Python"]["jobs"] == 1
    assert by_name["Python"]["share"] == 50
    assert by_name["Kubernetes"]["share"] == 50


def test_the_importance_breakdown_survives(client: TestClient, factory: TokenFactory) -> None:
    """One of the four things docs/07 names under Skill demand."""
    analysed_job(client, factory)

    data = get(client, factory, "/skills/demand")
    python = next(skill for skill in data["skills"] if skill["name"] == "Python")

    assert python["importance"] == {"CORE": 1}


def test_the_role_distribution_survives(client: TestClient, factory: TokenFactory) -> None:
    analysed_job(client, factory)

    data = get(client, factory, "/skills/demand")
    python = next(skill for skill in data["skills"] if skill["name"] == "Python")

    assert python["role_families"] == {"BACKEND": 1}


def test_an_archived_job_leaves_the_report(client: TestClient, factory: TokenFactory) -> None:
    job_id = analysed_job(client, factory)
    assert get(client, factory, "/skills/demand")["analysed_jobs"] == 1

    archived = client.post(f"{JOBS}/{job_id}/archive", headers=auth(factory))
    assert archived.status_code == 200, archived.text

    assert get(client, factory, "/skills/demand")["analysed_jobs"] == 0


# --- thresholds ---------------------------------------------------------------


def test_the_threshold_is_reported_rather_than_hiding_the_figures(
    client: TestClient, factory: TokenFactory
) -> None:
    """docs/07 asks for explicit minimum-data thresholds, not for silence. A
    user with one saved job may see what that job asked for; what they may not
    see is a sentence implying it generalises."""
    analysed_job(client, factory)

    data = get(client, factory, "/skills/demand")

    assert data["above_threshold"] is False
    assert data["minimum_jobs"] >= 2
    assert data["skills"], "the figures themselves are not withheld"


# --- gaps ---------------------------------------------------------------------


def test_a_skill_absent_from_the_profile_is_a_strong_gap(
    client: TestClient, factory: TokenFactory
) -> None:
    analysed_job(client, factory)

    gaps = get(client, factory, "/skills/gaps")["gaps"]

    assert {gap["name"] for gap in gaps} == {"Python", "Rust"}
    assert all(gap["state"] == "STRONG_GAP" for gap in gaps)


def test_a_confirmed_but_undemonstrated_skill_is_weak_evidence(
    client: TestClient, factory: TokenFactory
) -> None:
    """Added by hand, so confirmed — and attached to no experience or project."""
    add_skill(client, factory, "Python")
    analysed_job(client, factory)

    gaps = get(client, factory, "/skills/gaps")["gaps"]
    python = next(gap for gap in gaps if gap["name"] == "Python")

    assert python["state"] == "WEAK_EVIDENCE"
    assert python["held"] is True


def test_the_worst_gap_is_listed_first(client: TestClient, factory: TokenFactory) -> None:
    add_skill(client, factory, "Python")
    analysed_job(client, factory)

    gaps = get(client, factory, "/skills/gaps")["gaps"]

    assert gaps[0]["name"] == "Rust"
    assert gaps[0]["state"] == "STRONG_GAP"


def test_a_gap_is_not_lost_to_the_demand_list_cap(
    client: TestClient, factory: TokenFactory
) -> None:
    """DEV-040, end to end.

    The cap used to be applied inside `build_demand`, and `build_gaps` derives
    from that report — so a skill past the cap disappeared from a list headed
    "asked for, and not evidenced". With every skill asked for by the same one
    job, the tie-break is alphabetical, which is why the two that used to
    vanish are named Y and Z here.
    """
    names = [f"Skill {index:02d}" for index in range(TOP_SKILLS + 1)] + ["Ytterbium", "Zirconium"]

    # Every `source_text` has to appear in the posting. The pipeline drops any
    # requirement it cannot find there, which is the fabrication guard doing its
    # job — and which silently emptied the first version of this test.
    description = "Polyglot role.\n\nRequirements:\n" + "".join(
        f"- Experience with {name}\n" for name in names
    )
    created = client.post(
        JOBS,
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Polyglot",
            "description": description,
        },
    )
    assert created.status_code == 201, created.text

    analyse(
        client,
        factory,
        created.json()["data"]["id"],
        parse={
            **PARSE_RESPONSE,
            "requirements": [
                {
                    "normalized_text": name,
                    "requirement_type": "TECHNICAL_SKILL",
                    "importance": "REQUIRED",
                    "explicitness": "EXPLICIT",
                    "source_text": f"Experience with {name}",
                    "confidence": 90,
                    "skill_name": name,
                }
                for name in names
            ],
        },
    )

    demand = get(client, factory, "/skills/demand")
    gaps = get(client, factory, "/skills/gaps")["gaps"]

    # The chart shows a head, and says how big the whole is.
    assert len(demand["skills"]) == TOP_SKILLS
    assert demand["total_skills"] == len(names)
    assert demand["shown_skills"] == TOP_SKILLS

    # The completeness claim is complete, including the tail of the alphabet.
    assert len(gaps) == len(names)
    assert {"Ytterbium", "Zirconium"} <= {gap["name"] for gap in gaps}


# --- overview -----------------------------------------------------------------


def test_the_overview_agrees_with_the_lists_behind_it(
    client: TestClient, factory: TokenFactory
) -> None:
    """The dashboard's lesson, applied here: a summary that disagrees with the
    screen it summarises is worse than no summary."""
    add_skill(client, factory, "Python")
    analysed_job(client, factory)

    overview = get(client, factory, "/overview")
    demand = get(client, factory, "/skills/demand")
    gaps = get(client, factory, "/skills/gaps")

    assert overview["skills_tracked"] == len(demand["skills"])
    assert overview["gaps_found"] == len(gaps["gaps"])
    assert overview["analysed_jobs"] == demand["analysed_jobs"]


# --- what this phase deliberately does not serve ------------------------------


def test_a_role_family_below_the_threshold_has_no_average(
    client: TestClient, factory: TokenFactory
) -> None:
    """One job in a family is one job wearing a percentage sign.

    Null rather than the number, and never zero — zero would be a claim about
    fit rather than about how much data there is.
    """
    add_skill(client, factory, "Python")
    job_id = analysed_job(client, factory)
    client.post(f"{JOBS}/{job_id}/match", headers=auth(factory))

    roles = get(client, factory, "/roles")["roles"]

    assert len(roles) == 1
    assert roles[0]["jobs"] == 1
    assert roles[0]["average_alignment"] is None


def test_the_role_threshold_is_reported(client: TestClient, factory: TokenFactory) -> None:
    analysed_job(client, factory)

    assert get(client, factory, "/roles")["minimum_jobs"] >= 2


def test_the_funnel_counts_stages_without_dividing_them(
    client: TestClient, factory: TokenFactory
) -> None:
    """The counts are facts and are always shown. The rates are not computed
    below the threshold, and the flag says so rather than the client guessing.
    """
    job_id = analysed_job(client, factory)
    created = client.post(APPLICATIONS, headers=auth(factory), json={"job_id": job_id})
    assert created.status_code == 201, created.text

    funnel = get(client, factory, "/applications/funnel")

    assert funnel["applications"] == 1
    assert funnel["rates_are_meaningful"] is False
    assert [stage["key"] for stage in funnel["stages"]] == [
        "applied",
        "responded",
        "interviewed",
        "offered",
    ]


def test_a_rejected_application_still_counts_as_having_applied(
    client: TestClient, factory: TokenFactory
) -> None:
    """The bug a funnel over current statuses would have.

    An application rejected after an interview sits at REJECTED. Reading
    current status alone would report that it never applied and never
    interviewed — wrong for the majority of a real search, and wrong in the
    flattering direction. The stages come from `application_events`, which
    Phase 8 writes on every move and never rewrites.
    """
    job_id = analysed_job(client, factory)
    created = client.post(APPLICATIONS, headers=auth(factory), json={"job_id": job_id})
    application_id = created.json()["data"]["id"]

    for status in ("INTERESTED", "PREPARING", "READY_TO_APPLY"):
        moved = client.patch(
            f"{APPLICATIONS}/{application_id}/status",
            headers=auth(factory),
            json={"status": status},
        )
        assert moved.status_code == 200, moved.text

    applied = client.post(f"{APPLICATIONS}/{application_id}/apply", headers=auth(factory), json={})
    assert applied.status_code == 200, applied.text

    for status in ("HR_SCREEN", "TECHNICAL_INTERVIEW", "REJECTED"):
        moved = client.patch(
            f"{APPLICATIONS}/{application_id}/status",
            headers=auth(factory),
            json={"status": status},
        )
        assert moved.status_code == 200, moved.text

    stages = {
        stage["key"]: stage["reached"]
        for stage in get(client, factory, "/applications/funnel")["stages"]
    }

    assert stages["applied"] == 1, "a rejection does not un-apply an application"
    assert stages["responded"] == 1
    assert stages["interviewed"] == 1
    assert stages["offered"] == 0


def test_resume_performance_lists_only_versions_actually_sent(
    client: TestClient, factory: TokenFactory
) -> None:
    """A resume nobody sent has no performance, and listing it at zero would
    read as a verdict on the document rather than on the absence of data."""
    analysed_job(client, factory)

    assert get(client, factory, "/resumes")["versions"] == []


# --- ownership ----------------------------------------------------------------


def test_another_users_jobs_are_invisible(client: TestClient, factory: TokenFactory) -> None:
    analysed_job(client, factory, subject=BOB)

    data = get(client, factory, "/skills/demand", subject=ALICE)

    assert data["analysed_jobs"] == 0
    assert data["skills"] == []


def test_insights_need_a_signed_in_user(client: TestClient) -> None:
    assert client.get(f"{INSIGHTS}/skills/demand").status_code == 401
    assert client.get(f"{INSIGHTS}/overview").status_code == 401
