"""Resume authoring end to end, against a real database.

Slice 1 of Phase 7: no AI. What these protect:

- a used version's content cannot change, which is the rule
  ``docs/11-engineering-standards.md`` states as "do not mutate past";
- lineage survives, so a tailored version knows what it came from;
- an item can point back at the career row it was selected from;
- another user cannot read or edit any of it.
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

from jip_api.api.dependencies import get_dispatcher
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
RESUMES = "/api/v1/resumes"
VERSIONS = "/api/v1/resume-versions"
CAREER = "/api/v1/career"
ALICE = "user_alice"
BOB = "user_bob"


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


def make_resume(
    client: TestClient, factory: TokenFactory, subject: str = ALICE, **overrides: Any
) -> dict[str, Any]:
    body = {"title": "Backend", "family": "BASE", **overrides}
    response = client.post(RESUMES, headers=auth(factory, subject), json=body)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def make_version(
    client: TestClient,
    factory: TokenFactory,
    resume_id: str,
    subject: str = ALICE,
    **body: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{RESUMES}/{resume_id}/versions", headers=auth(factory, subject), json=body
    )
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def content(**overrides: Any) -> dict[str, Any]:
    return {
        "sections": [
            {
                "kind": "SUMMARY",
                "display_order": 0,
                "items": [{"text": "Backend engineer with six years of Python."}],
            },
            {
                "kind": "EXPERIENCE",
                "display_order": 1,
                "items": [
                    {
                        "text": "Cut planning latency by rebuilding the solver.",
                        "heading": "Senior Engineer, Verdant",
                    }
                ],
            },
        ],
        **overrides,
    }


def put_content(
    client: TestClient,
    factory: TokenFactory,
    version_id: str,
    body: dict[str, Any] | None = None,
    subject: str = ALICE,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.put(
        f"{VERSIONS}/{version_id}/content",
        headers=auth(factory, subject),
        json=body if body is not None else content(),
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def set_status(
    client: TestClient,
    factory: TokenFactory,
    version_id: str,
    status: str,
    subject: str = ALICE,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.post(
        f"{VERSIONS}/{version_id}/status",
        headers=auth(factory, subject),
        json={"status": status},
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


# --- resumes ------------------------------------------------------------------


def test_creates_a_base_resume(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)

    assert resume["title"] == "Backend"
    assert resume["family"] == "BASE"
    assert resume["job_id"] is None


def test_a_job_specific_resume_needs_a_job(client: TestClient, factory: TokenFactory) -> None:
    """The family and the job have to agree, or "job-specific" means nothing."""
    response = client.post(
        RESUMES, headers=auth(factory), json={"title": "For Verdant", "family": "JOB_SPECIFIC"}
    )

    assert response.status_code == 422
    assert "needs the job" in response.json()["error"]["message"]


def test_a_base_resume_cannot_name_a_job(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(
        RESUMES,
        headers=auth(factory),
        json={"title": "Backend", "family": "BASE", "job_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


def test_lists_resumes_without_archived_ones(client: TestClient, factory: TokenFactory) -> None:
    kept = make_resume(client, factory)
    archived = make_resume(client, factory, title="Old")
    client.post(f"{RESUMES}/{archived['id']}/archive", headers=auth(factory))

    listed = client.get(RESUMES, headers=auth(factory)).json()["data"]

    assert [row["id"] for row in listed] == [kept["id"]]


def test_archived_resumes_can_be_asked_for(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    client.post(f"{RESUMES}/{resume['id']}/archive", headers=auth(factory))

    listed = client.get(RESUMES, headers=auth(factory), params={"include_archived": "true"}).json()[
        "data"
    ]

    assert len(listed) == 1


def test_renaming_a_resume_is_allowed(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)

    response = client.patch(
        f"{RESUMES}/{resume['id']}", headers=auth(factory), json={"title": "Platform"}
    )

    assert response.json()["data"]["title"] == "Platform"


# --- versions and content -----------------------------------------------------


def test_the_first_version_is_version_one(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)

    version = make_version(client, factory, resume["id"])

    assert version["version"] == 1
    assert version["status"] == "DRAFT"
    assert version["sections"] == []


def test_versions_append(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    make_version(client, factory, resume["id"])

    second = make_version(client, factory, resume["id"])

    assert second["version"] == 2


def test_content_can_be_written_and_read_back(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    put_content(client, factory, version["id"])
    read = client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).json()["data"]

    assert [section["kind"] for section in read["sections"]] == ["SUMMARY", "EXPERIENCE"]
    assert read["sections"][1]["items"][0]["heading"] == "Senior Engineer, Verdant"


def test_replacing_content_removes_what_was_there(
    client: TestClient, factory: TokenFactory
) -> None:
    """Whole-document writes: a section left out of the request is gone, which
    is how deleting and reordering both work from the user's side."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    put_content(client, factory, version["id"])

    put_content(
        client,
        factory,
        version["id"],
        {"sections": [{"kind": "SKILLS", "items": [{"text": "Python, PostgreSQL"}]}]},
    )
    read = client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).json()["data"]

    assert [section["kind"] for section in read["sections"]] == ["SKILLS"]


def test_an_item_can_point_at_the_career_row_it_came_from(
    client: TestClient, factory: TokenFactory
) -> None:
    """The reference that makes truth validation tractable in slice 4: a claim
    can be checked against the row it came from rather than the whole
    profile."""
    skill = client.post(
        f"{CAREER}/skills", headers=auth(factory), json={"name": "Python", "category": "LANGUAGE"}
    ).json()["data"]

    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    put_content(
        client,
        factory,
        version["id"],
        {
            "sections": [
                {
                    "kind": "SKILLS",
                    "items": [
                        {
                            "text": "Python",
                            "source_type": "SKILL",
                            "source_entity_id": skill["id"],
                        }
                    ],
                }
            ]
        },
    )

    read = client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).json()["data"]
    item = read["sections"][0]["items"][0]

    assert item["source_type"] == "SKILL"
    assert item["source_entity_id"] == skill["id"]


def test_a_sourced_item_must_name_its_row(client: TestClient, factory: TokenFactory) -> None:
    """A reference that cannot be followed is worse than none: slice 4 would
    have nothing to validate against."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    response = client.put(
        f"{VERSIONS}/{version['id']}/content",
        headers=auth(factory),
        json={
            "sections": [{"kind": "SKILLS", "items": [{"text": "Python", "source_type": "SKILL"}]}]
        },
    )

    assert response.status_code >= 400


def test_a_new_version_can_copy_an_existing_one(client: TestClient, factory: TokenFactory) -> None:
    """How tailoring starts in slice 3."""
    resume = make_resume(client, factory)
    first = make_version(client, factory, resume["id"])
    put_content(client, factory, first["id"])

    second = make_version(client, factory, resume["id"], copy_from=first["id"])

    assert [section["kind"] for section in second["sections"]] == ["SUMMARY", "EXPERIENCE"]


def test_a_copy_is_a_real_copy(client: TestClient, factory: TokenFactory) -> None:
    """Editing the tailored version must not reach back into the base."""
    resume = make_resume(client, factory)
    first = make_version(client, factory, resume["id"])
    put_content(client, factory, first["id"])
    second = make_version(client, factory, resume["id"], copy_from=first["id"])

    put_content(
        client,
        factory,
        second["id"],
        {"sections": [{"kind": "SKILLS", "items": [{"text": "Rewritten"}]}]},
    )

    original = client.get(f"{VERSIONS}/{first['id']}", headers=auth(factory)).json()["data"]
    assert [section["kind"] for section in original["sections"]] == ["SUMMARY", "EXPERIENCE"]


def test_lineage_is_recorded(client: TestClient, factory: TokenFactory) -> None:
    """docs/06-resume-engine.md: every job-specific version preserves its
    parent."""
    base = make_resume(client, factory)
    base_version = make_version(client, factory, base["id"])

    job = client.post(
        "/api/v1/jobs",
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": "We are hiring a backend engineer. " * 12,
        },
    ).json()["data"]

    tailored = make_resume(
        client,
        factory,
        title="For Verdant",
        family="JOB_SPECIFIC",
        job_id=job["id"],
        parent_resume_id=base["id"],
    )
    tailored_version = make_version(
        client, factory, tailored["id"], parent_version_id=base_version["id"]
    )

    assert tailored["parent_resume_id"] == base["id"]
    assert tailored_version["parent_version_id"] == base_version["id"]


# --- immutability -------------------------------------------------------------


def test_a_used_version_cannot_be_edited(client: TestClient, factory: TokenFactory) -> None:
    """The rule this slice exists to enforce. An application record must
    describe a document that existed in that form."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    put_content(client, factory, version["id"])

    set_status(client, factory, version["id"], "APPROVED")
    set_status(client, factory, version["id"], "USED")

    body = put_content(client, factory, version["id"], expect=409)
    assert "cannot change" in body["error"]["message"]


def test_a_used_version_keeps_its_content(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    put_content(client, factory, version["id"])
    set_status(client, factory, version["id"], "APPROVED")
    set_status(client, factory, version["id"], "USED")

    put_content(client, factory, version["id"], expect=409)
    read = client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).json()["data"]

    assert len(read["sections"]) == 2
    assert read["is_editable"] is False


def test_an_archived_version_cannot_be_edited(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    set_status(client, factory, version["id"], "ARCHIVED")

    put_content(client, factory, version["id"], expect=409)


def test_a_draft_reports_itself_as_editable(client: TestClient, factory: TokenFactory) -> None:
    """The endpoint that refuses an edit and the button that offers one must
    read the same answer."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    read = client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).json()["data"]

    assert read["is_editable"] is True


def test_using_a_version_records_when(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    set_status(client, factory, version["id"], "APPROVED")

    used = set_status(client, factory, version["id"], "USED")

    assert used["used_at"] is not None


def test_a_used_version_cannot_go_back_to_draft(client: TestClient, factory: TokenFactory) -> None:
    """Sending a document is the event that makes what it said permanent."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    set_status(client, factory, version["id"], "APPROVED")
    set_status(client, factory, version["id"], "USED")

    set_status(client, factory, version["id"], "DRAFT", expect=409)


def test_a_draft_cannot_skip_straight_to_used(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    set_status(client, factory, version["id"], "USED", expect=409)


def test_editing_is_allowed_up_to_approval(client: TestClient, factory: TokenFactory) -> None:
    """Approved is not frozen — a user may still fix a typo before sending."""
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    set_status(client, factory, version["id"], "APPROVED")

    put_content(client, factory, version["id"])


def test_a_new_version_can_follow_a_used_one(client: TestClient, factory: TokenFactory) -> None:
    """Frozen content must not mean a dead end."""
    resume = make_resume(client, factory)
    first = make_version(client, factory, resume["id"])
    put_content(client, factory, first["id"])
    set_status(client, factory, first["id"], "APPROVED")
    set_status(client, factory, first["id"], "USED")

    second = make_version(client, factory, resume["id"], copy_from=first["id"])

    assert second["version"] == 2
    assert second["is_editable"] is True


# --- ownership ----------------------------------------------------------------


def test_another_user_cannot_read_a_resume(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)

    assert client.get(f"{RESUMES}/{resume['id']}", headers=auth(factory, BOB)).status_code == 404


def test_another_user_cannot_read_a_version(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    assert client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory, BOB)).status_code == 404


def test_another_user_cannot_edit_a_version(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    put_content(client, factory, version["id"], subject=BOB, expect=404)


def test_another_user_cannot_copy_a_version(client: TestClient, factory: TokenFactory) -> None:
    """The copy path reads a second version by id, so it needs its own check —
    otherwise it would be a way to read content the caller does not own."""
    alice_resume = make_resume(client, factory)
    alice_version = make_version(client, factory, alice_resume["id"])
    put_content(client, factory, alice_version["id"])

    bob_resume = make_resume(client, factory, subject=BOB, title="Bob's")

    response = client.post(
        f"{RESUMES}/{bob_resume['id']}/versions",
        headers=auth(factory, BOB),
        json={"copy_from": alice_version["id"]},
    )

    assert response.status_code == 404


def test_another_user_cannot_change_a_status(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])

    set_status(client, factory, version["id"], "APPROVED", subject=BOB, expect=404)


def test_unauthenticated_requests_are_rejected(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)

    assert client.get(RESUMES).status_code == 401
    assert client.post(RESUMES, json={"title": "x"}).status_code == 401
    assert client.get(f"{RESUMES}/{resume['id']}").status_code == 401


def test_a_resume_list_never_shows_another_users_rows(
    client: TestClient, factory: TokenFactory
) -> None:
    make_resume(client, factory, subject=BOB, title="Bob's")

    listed = client.get(RESUMES, headers=auth(factory)).json()["data"]

    assert listed == []


# --- deletion -----------------------------------------------------------------


def test_deleting_a_resume_takes_its_versions(client: TestClient, factory: TokenFactory) -> None:
    resume = make_resume(client, factory)
    version = make_version(client, factory, resume["id"])
    put_content(client, factory, version["id"])

    assert client.delete(f"{RESUMES}/{resume['id']}", headers=auth(factory)).status_code == 204
    assert client.get(f"{VERSIONS}/{version['id']}", headers=auth(factory)).status_code == 404
