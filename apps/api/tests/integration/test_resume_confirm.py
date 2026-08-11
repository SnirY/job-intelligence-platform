"""Approving reviewed extraction candidates.

The step ``docs/10-api-contracts.md`` is protecting when it says AI extraction
must not write verified profile data directly. Three properties matter more
than anything else here, and each has its own test:

- an ignored candidate changes nothing;
- confirming the same extraction twice creates nothing twice;
- every write lands through the career services, so it is visible on the
  career API afterwards.
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
from jip_api.api.dependencies import get_dispatcher, get_storage
from jip_api.application.resumes import pipeline as pipeline_uc
from jip_api.domain.processing.models import ProcessingJob
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.document_fixtures import RESUME_LINES, pdf_bytes
from tests.integration.resume_fixtures import InMemoryStorage, RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/resumes"
CAREER = "/api/v1/career"
ALICE = "user_alice"
PDF_TYPE = "application/pdf"

PARSE_RESPONSE: dict[str, Any] = {
    "skills": [
        {
            "name": "Python",
            "category": "LANGUAGE",
            "confidence": 95,
            "source_text": "Python, FastAPI",
        },
        # Deliberately an alias. Confirming it must resolve to the canonical
        # React seeded by the migration, not mint a near-duplicate skill.
        {"name": "React.js", "category": "FRAMEWORK", "confidence": 90},
    ],
    "experiences": [
        {
            "company": "Verdant Logistics",
            "title": "Junior Backend Engineer",
            "employment_type": "FULL_TIME",
            "start_date": "2023-03",
            "is_current": True,
            "confidence": 96,
            "achievements": [
                {"text": "Built REST endpoints in FastAPI.", "confidence": 93},
                {"text": "Wrote the carrier reconciliation report.", "confidence": 88},
            ],
        }
    ],
    "projects": [
        {
            "name": "ledgerline",
            "project_type": "PERSONAL",
            "confidence": 90,
            "technologies": [{"name": "Postgres", "confidence": 92}],
        }
    ],
    "education": [
        {
            "institution": "University of Lisbon",
            "degree": "BSc",
            "field_of_study": "Computer Science",
            "start_date": "2019",
            "end_date": "2022",
            "confidence": 94,
        }
    ],
}


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
    storage: InMemoryStorage,
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
        app.dependency_overrides[get_storage] = lambda: storage
        # A lambda, not the class: FastAPI would treat the class as a dependency
        # callable and try to inject its dataclass fields from the request.
        dispatcher = RecordingDispatcher()
        app.dependency_overrides[get_dispatcher] = lambda: dispatcher

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def parse_sections() -> list[dict[str, Any]]:
    """`PARSE_RESPONSE` split the way the parser now asks for it.

    DEV-017 made a resume parse four calls, one per section, so a fake provider
    needs four responses where it needed one. `FakeLLMProvider` replays in
    request order, which is `RESUME_SECTION_PROMPTS`.
    """
    return [
        {"skills": PARSE_RESPONSE.get("skills", [])},
        {"experiences": PARSE_RESPONSE.get("experiences", [])},
        {"projects": PARSE_RESPONSE.get("projects", [])},
        {"education": PARSE_RESPONSE.get("education", [])},
    ]


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


@pytest.fixture
def review(client: TestClient, factory: TokenFactory, storage: InMemoryStorage) -> dict[str, Any]:
    """Upload, run the pipeline, and return the review payload."""
    upload = client.post(
        f"{BASE}/import",
        headers=auth(factory),
        files={"file": ("resume.pdf", pdf_bytes(RESUME_LINES), PDF_TYPE)},
    )
    assert upload.status_code == 202, upload.text
    data = upload.json()["data"]

    session = new_session()
    try:
        job = session.get(ProcessingJob, uuid.UUID(data["processing_job_id"]))
        assert job is not None
        pipeline_uc.run_import(
            session,
            storage,
            FakeLLMProvider(parse_sections()),
            build_router(
                resume_parse_model="test-model",
                resume_parse_max_output_tokens=8000,
                resume_parse_effort=None,
            ),
            job=job,
            max_input_chars=60_000,
            max_attempts=1,
        )
    finally:
        session.close()

    payload: dict[str, Any] = client.get(
        f"{BASE}/imports/{data['source_document_id']}/extraction", headers=auth(factory)
    ).json()["data"]
    payload["document_id"] = data["source_document_id"]
    return payload


def items_of(review: dict[str, Any], candidate_type: str) -> list[dict[str, Any]]:
    return [i for i in review["extraction"]["items"] if i["candidate_type"] == candidate_type]


def confirm(
    client: TestClient,
    factory: TokenFactory,
    review: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/imports/{review['document_id']}/confirm",
        headers=auth(factory),
        json={"decisions": decisions},
    )
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def accept_all(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"item_id": i["id"], "action": "ACCEPT"} for i in review["extraction"]["items"]]


def career(client: TestClient, factory: TokenFactory, path: str) -> list[dict[str, Any]]:
    response = client.get(f"{CAREER}/{path}", headers=auth(factory))
    data: list[dict[str, Any]] = response.json()["data"]
    return data


# --- accept -------------------------------------------------------------------


def test_accepting_everything_populates_the_profile(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    result = confirm(client, factory, review, accept_all(review))

    assert result["remaining_pending"] == 0
    assert len(career(client, factory, "skills")) == 2
    assert len(career(client, factory, "experiences")) == 1
    assert len(career(client, factory, "projects")) == 1
    assert len(career(client, factory, "education")) == 1


def test_accepted_skills_resolve_through_the_alias_catalogue(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """docs/05-ai-and-matching.md: raw skill -> alias lookup -> canonical skill.

    Without this, a job asking for React finds no evidence in a profile whose
    resume said React.js.
    """
    confirm(client, factory, review, accept_all(review))

    names = {s["name"] for s in career(client, factory, "skills")}

    assert names == {"Python", "React"}


def test_accepted_data_is_user_confirmed_with_resume_provenance(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """The user read the item and accepted it, so it is confirmed. Source keeps
    the provenance: confirmed by a person, originally from a resume."""
    confirm(client, factory, review, accept_all(review))

    skill = career(client, factory, "skills")[0]

    assert skill["verification_status"] == "USER_CONFIRMED"
    assert skill["source"] == "RESUME_IMPORT"


def test_achievements_land_under_their_role(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    confirm(client, factory, review, accept_all(review))

    experience = career(client, factory, "experiences")[0]

    assert len(experience["achievements"]) == 2
    assert "Built REST endpoints in FastAPI." in {a["text"] for a in experience["achievements"]}


def test_project_technologies_land_on_their_project(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """Postgres is an alias of PostgreSQL, so the link must be to the canonical
    skill — that is what makes the project usable as matching evidence."""
    confirm(client, factory, review, accept_all(review))

    project = career(client, factory, "projects")[0]

    assert project["skills"] == ["PostgreSQL"]


def test_the_extraction_records_what_each_item_became(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """Provenance in both directions: the career record can be traced back to
    the document that proposed it."""
    confirm(client, factory, review, accept_all(review))

    items = client.get(
        f"{BASE}/imports/{review['document_id']}/extraction", headers=auth(factory)
    ).json()["data"]["extraction"]["items"]

    assert all(i["decision"] == "ACCEPTED" for i in items)
    assert all(i["target_entity_id"] is not None for i in items)


# --- ignore -------------------------------------------------------------------


def test_ignored_items_change_nothing(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    result = confirm(
        client,
        factory,
        review,
        [{"item_id": i["id"], "action": "IGNORE"} for i in review["extraction"]["items"]],
    )

    assert result["created_count"] == 0
    assert career(client, factory, "skills") == []
    assert career(client, factory, "experiences") == []
    assert career(client, factory, "projects") == []
    assert career(client, factory, "education") == []


def test_a_mixed_decision_applies_only_what_was_accepted(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    skills = items_of(review, "SKILL")
    education = items_of(review, "EDUCATION")

    confirm(
        client,
        factory,
        review,
        [
            {"item_id": skills[0]["id"], "action": "ACCEPT"},
            {"item_id": skills[1]["id"], "action": "IGNORE"},
            {"item_id": education[0]["id"], "action": "IGNORE"},
        ],
    )

    assert len(career(client, factory, "skills")) == 1
    assert career(client, factory, "education") == []


def test_an_achievement_whose_role_was_ignored_is_skipped(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """A bullet with no role has nowhere to go, and inventing a role to hang it
    on would be fabricating career data."""
    experience = items_of(review, "EXPERIENCE")[0]
    achievement = items_of(review, "EXPERIENCE_ACHIEVEMENT")[0]

    result = confirm(
        client,
        factory,
        review,
        [
            {"item_id": experience["id"], "action": "IGNORE"},
            {"item_id": achievement["id"], "action": "ACCEPT"},
        ],
    )

    outcomes = {a["item_id"]: a["outcome"] for a in result["applied"]}
    assert outcomes[achievement["id"]] == "SKIPPED_PARENT_NOT_ACCEPTED"
    assert career(client, factory, "experiences") == []


# --- edit ---------------------------------------------------------------------


def test_an_edit_is_what_gets_written(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    experience = items_of(review, "EXPERIENCE")[0]

    confirm(
        client,
        factory,
        review,
        [
            {
                "item_id": experience["id"],
                "action": "EDIT",
                "payload": {"title": "Backend Engineer", "location": "Lisbon"},
            }
        ],
    )

    record = career(client, factory, "experiences")[0]

    assert record["title"] == "Backend Engineer"
    assert record["location"] == "Lisbon"
    assert record["company"] == "Verdant Logistics", "unedited fields must be preserved"


def test_the_original_extraction_survives_an_edit(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """docs/06-resume-engine.md wants corrections remembered, not merged away —
    what the model proposed and what the user meant stay distinguishable."""
    experience = items_of(review, "EXPERIENCE")[0]

    confirm(
        client,
        factory,
        review,
        [{"item_id": experience["id"], "action": "EDIT", "payload": {"title": "Backend Engineer"}}],
    )

    item = next(
        i
        for i in client.get(
            f"{BASE}/imports/{review['document_id']}/extraction", headers=auth(factory)
        ).json()["data"]["extraction"]["items"]
        if i["id"] == experience["id"]
    )

    assert item["decision"] == "EDITED"
    assert item["payload"]["title"] == "Junior Backend Engineer"
    assert item["edited_payload"]["title"] == "Backend Engineer"


# --- idempotency --------------------------------------------------------------


def test_confirming_twice_creates_nothing_twice(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    first = confirm(client, factory, review, accept_all(review))
    second = confirm(client, factory, review, accept_all(review))

    assert first["created_count"] > 0
    assert second["created_count"] == 0
    assert all(a["outcome"] == "ALREADY_APPLIED" for a in second["applied"])

    assert len(career(client, factory, "skills")) == 2
    assert len(career(client, factory, "experiences")) == 1
    assert len(career(client, factory, "projects")) == 1
    assert len(career(client, factory, "education")) == 1
    assert len(career(client, factory, "experiences")[0]["achievements"]) == 2


def test_a_repeat_confirmation_returns_the_same_records(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    first = confirm(client, factory, review, accept_all(review))
    second = confirm(client, factory, review, accept_all(review))

    def targets(result: dict[str, Any]) -> dict[str, str]:
        return {a["item_id"]: a["target_entity_id"] for a in result["applied"]}

    assert targets(first) == targets(second)


def test_accepting_a_skill_the_user_already_has_links_rather_than_fails(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """Approving a resume must not fail because the user already typed Python,
    and must not overwrite what they said about it either."""
    created = client.post(
        f"{CAREER}/skills",
        headers=auth(factory),
        json={"name": "Python", "category": "LANGUAGE", "proficiency": "EXPERT"},
    )
    assert created.status_code == 201

    python_item = next(i for i in items_of(review, "SKILL") if i["payload"]["name"] == "Python")
    result = confirm(client, factory, review, [{"item_id": python_item["id"], "action": "ACCEPT"}])

    assert result["applied"][0]["outcome"] == "LINKED"
    skills = career(client, factory, "skills")
    assert len(skills) == 1
    assert skills[0]["proficiency"] == "EXPERT", "the user's own answer must survive"


def test_accepting_an_experience_the_user_already_has_links(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """A resume usually describes roles already entered by hand. A second copy
    would corrupt the profile every later match is measured against."""
    created = client.post(
        f"{CAREER}/experiences",
        headers=auth(factory),
        json={
            "company": "Verdant Logistics",
            "title": "Junior Backend Engineer",
            "start_date": "2023-03-01",
            "is_current": True,
        },
    )
    assert created.status_code == 201

    experience = items_of(review, "EXPERIENCE")[0]
    result = confirm(client, factory, review, [{"item_id": experience["id"], "action": "ACCEPT"}])

    assert result["applied"][0]["outcome"] == "LINKED"
    assert len(career(client, factory, "experiences")) == 1


# --- lifecycle and errors -----------------------------------------------------


def test_the_document_is_marked_confirmed_once_nothing_is_pending(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    confirm(client, factory, review, accept_all(review))

    document = client.get(
        f"{BASE}/imports/{review['document_id']}/extraction", headers=auth(factory)
    ).json()["data"]["document"]

    assert document["status"] == "CONFIRMED"


def test_partial_confirmation_leaves_the_rest_pending(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    skills = items_of(review, "SKILL")

    result = confirm(client, factory, review, [{"item_id": skills[0]["id"], "action": "ACCEPT"}])

    assert result["remaining_pending"] > 0
    document = client.get(
        f"{BASE}/imports/{review['document_id']}/extraction", headers=auth(factory)
    ).json()["data"]["document"]
    assert document["status"] == "PARSED"


def test_an_item_from_another_extraction_is_refused(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    """A wrong id means the caller is confused about which review it is
    submitting; applying the rest would be worse than refusing."""
    response = client.post(
        f"{BASE}/imports/{review['document_id']}/confirm",
        headers=auth(factory),
        json={"decisions": [{"item_id": str(uuid.uuid4()), "action": "ACCEPT"}]},
    )

    assert response.status_code == 404
    assert career(client, factory, "skills") == []


def test_an_edit_that_blanks_a_required_field_is_reported_not_applied(
    client: TestClient, factory: TokenFactory, review: dict[str, Any]
) -> None:
    experience = items_of(review, "EXPERIENCE")[0]

    result = confirm(
        client,
        factory,
        review,
        [{"item_id": experience["id"], "action": "EDIT", "payload": {"company": "   "}}],
    )

    assert result["applied"][0]["outcome"] == "INVALID"
    assert career(client, factory, "experiences") == []


def test_confirm_requires_an_extraction(client: TestClient, factory: TokenFactory) -> None:
    """Uploaded but not yet parsed: there is nothing to decide on."""
    upload = client.post(
        f"{BASE}/import",
        headers=auth(factory),
        files={"file": ("resume.pdf", pdf_bytes(RESUME_LINES), PDF_TYPE)},
    )
    document_id = upload.json()["data"]["source_document_id"]

    response = client.post(
        f"{BASE}/imports/{document_id}/confirm",
        headers=auth(factory),
        json={"decisions": [{"item_id": str(uuid.uuid4()), "action": "ACCEPT"}]},
    )

    assert response.status_code == 404
