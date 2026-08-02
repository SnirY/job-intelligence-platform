"""Skills, experience, projects, and education against a real database.

The ownership block runs the same checks against all four collections, because
the mistake it guards against — filtering by id without also filtering by user —
is one that has to be re-made per endpoint to be caught.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import get_engine, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/career"
ALICE = "user_alice"
BOB = "user_bob"


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def client(
    factory: TokenFactory, clean_database_url: str, monkeypatch: pytest.MonkeyPatch
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

        with TestClient(create_app(), raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def create(
    client: TestClient, factory: TokenFactory, subject: str, path: str, body: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(f"{BASE}/{path}", headers=auth(factory, subject), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


SKILL = ("skills", {"name": "Python", "category": "LANGUAGE"})
EXPERIENCE = ("experiences", {"company": "Acme", "title": "Backend Engineer"})
PROJECT = ("projects", {"name": "Portfolio site"})
EDUCATION = ("education", {"institution": "Technion", "degree": "BSc"})

COLLECTIONS = [SKILL, EXPERIENCE, PROJECT, EDUCATION]
COLLECTION_IDS = ["skills", "experiences", "projects", "education"]


# --- basic lifecycle ----------------------------------------------------------


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_collections_start_empty(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    response = client.get(f"{BASE}/{path}", headers=auth(factory, ALICE))

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_create_then_list(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    created = create(client, factory, ALICE, path, body)

    listed = client.get(f"{BASE}/{path}", headers=auth(factory, ALICE)).json()["data"]

    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_delete_removes_the_record(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    created = create(client, factory, ALICE, path, body)

    response = client.delete(f"{BASE}/{path}/{created['id']}", headers=auth(factory, ALICE))

    assert response.status_code == 204
    assert client.get(f"{BASE}/{path}", headers=auth(factory, ALICE)).json()["data"] == []


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_unauthenticated_access_is_refused(
    client: TestClient, path: str, body: dict[str, Any]
) -> None:
    assert client.get(f"{BASE}/{path}").status_code == 401
    assert client.post(f"{BASE}/{path}", json=body).status_code == 401


# --- ownership ----------------------------------------------------------------


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_users_only_see_their_own_records(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    create(client, factory, ALICE, path, body)

    assert client.get(f"{BASE}/{path}", headers=auth(factory, BOB)).json()["data"] == []


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_updating_another_users_record_is_refused(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    alice_record = create(client, factory, ALICE, path, body)

    response = client.patch(
        f"{BASE}/{path}/{alice_record['id']}", headers=auth(factory, BOB), json={}
    )

    assert response.status_code == 404
    assert len(client.get(f"{BASE}/{path}", headers=auth(factory, ALICE)).json()["data"]) == 1


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_deleting_another_users_record_is_refused(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    alice_record = create(client, factory, ALICE, path, body)

    response = client.delete(f"{BASE}/{path}/{alice_record['id']}", headers=auth(factory, BOB))

    assert response.status_code == 404
    assert len(client.get(f"{BASE}/{path}", headers=auth(factory, ALICE)).json()["data"]) == 1


@pytest.mark.parametrize(("path", "body"), COLLECTIONS, ids=COLLECTION_IDS)
def test_foreign_and_missing_ids_are_indistinguishable(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    """A different answer for "exists but not yours" would let a caller
    enumerate what other users hold."""
    alice_record = create(client, factory, ALICE, path, body)

    foreign = client.delete(f"{BASE}/{path}/{alice_record['id']}", headers=auth(factory, BOB))
    missing = client.delete(f"{BASE}/{path}/{uuid.uuid4()}", headers=auth(factory, BOB))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]


# --- skills: canonical resolution ---------------------------------------------


def canonical_count() -> int:
    with get_engine().connect() as connection:
        return int(connection.execute(sqlalchemy.text("SELECT count(*) FROM skills")).scalar_one())


@pytest.mark.parametrize("variant", ["React", "react", "REACT", " React ", "  react  "])
def test_normalization_collapses_case_and_spacing(
    client: TestClient, factory: TokenFactory, variant: str
) -> None:
    """Mechanical variants resolve without needing an alias entry."""
    before = canonical_count()
    create(client, factory, ALICE, "skills", {"name": "React"})
    after_first = canonical_count()

    response = client.post(f"{BASE}/skills", headers=auth(factory, BOB), json={"name": variant})

    assert response.status_code == 201
    assert canonical_count() == after_first, f"{variant!r} created a second canonical skill"
    assert after_first >= before


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("React.js", "React"), ("ReactJS", "React"), ("JS", "JavaScript"), ("Postgres", "PostgreSQL")],
)
def test_seeded_aliases_resolve_to_the_canonical_skill(
    client: TestClient, factory: TokenFactory, alias: str, canonical: str
) -> None:
    """A semantic variant is not a spelling difference.

    Normalization cannot know React.js means React; only the alias table does,
    and without it a job asking for React finds no evidence in a profile that
    says React.js.
    """
    before = canonical_count()

    created = create(client, factory, ALICE, "skills", {"name": alias})

    assert created["name"] == canonical
    assert canonical_count() == before, f"{alias!r} created a new canonical skill"


def test_distinct_skills_stay_distinct(client: TestClient, factory: TokenFactory) -> None:
    """Normalization keeps + and #, or C, C++, and C# would collapse into one.

    Asserted as three distinct canonical ids rather than as three *new* rows.
    The delta was a proxy that held only while the catalogue was sparse enough
    not to contain them — DEV-032 seeded C++ and C#, and counting new rows then
    measured how much of the catalogue already existed rather than whether the
    three names stayed apart.
    """
    claimed = [
        create(client, factory, ALICE, "skills", {"name": name})["skill_id"]
        for name in ("C", "C++", "C#")
    ]

    assert len(set(claimed)) == 3, "C, C++ and C# collapsed into fewer skills"


def test_the_same_skill_cannot_be_claimed_twice(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, ALICE, "skills", {"name": "Python"})

    response = client.post(f"{BASE}/skills", headers=auth(factory, ALICE), json={"name": "python"})

    assert response.status_code == 409


def test_manual_skills_are_user_confirmed(client: TestClient, factory: TokenFactory) -> None:
    """Typed by a person, so confirmed. AI-proposed skills arrive elsewhere."""
    created = create(client, factory, ALICE, "skills", {"name": "Python"})

    assert created["verification_status"] == "USER_CONFIRMED"
    assert created["source"] == "MANUAL"


def test_removing_a_claim_keeps_the_canonical_skill(
    client: TestClient, factory: TokenFactory
) -> None:
    """The catalogue is shared; deleting one person's claim must not remove the
    skill from everyone else."""
    alice_skill = create(client, factory, ALICE, "skills", {"name": "Python"})
    create(client, factory, BOB, "skills", {"name": "Python"})

    client.delete(f"{BASE}/skills/{alice_skill['id']}", headers=auth(factory, ALICE))

    bob_skills = client.get(f"{BASE}/skills", headers=auth(factory, BOB)).json()["data"]
    assert [s["name"] for s in bob_skills] == ["Python"]


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("skills", {"name": "   "}),
        ("skills", {"name": "Python", "years_of_experience": -1}),
        ("skills", {"name": "Python", "proficiency": "GODLIKE"}),
        ("experiences", {"company": "", "title": "Engineer"}),
        ("experiences", {"company": "Acme", "title": "Engineer", "unexpected": 1}),
        (
            "experiences",
            {
                "company": "Acme",
                "title": "Engineer",
                "start_date": "2024-01-01",
                "end_date": "2023-01-01",
            },
        ),
        (
            "experiences",
            {"company": "Acme", "title": "E", "is_current": True, "end_date": "2024-01-01"},
        ),
        ("projects", {"name": "P", "repository_url": "javascript:alert(1)"}),
        ("projects", {"name": ""}),
        ("education", {"institution": ""}),
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient, factory: TokenFactory, path: str, body: dict[str, Any]
) -> None:
    response = client.post(f"{BASE}/{path}", headers=auth(factory, ALICE), json=body)

    assert response.status_code == 422, response.text
    assert client.get(f"{BASE}/{path}", headers=auth(factory, ALICE)).json()["data"] == []


def test_a_current_role_keeps_no_end_date(client: TestClient, factory: TokenFactory) -> None:
    created = create(
        client,
        factory,
        ALICE,
        "experiences",
        {"company": "Acme", "title": "Engineer", "is_current": True, "start_date": "2024-01-01"},
    )

    assert created["is_current"] is True
    assert created["end_date"] is None


def test_duplicate_project_name_is_refused(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, ALICE, "projects", {"name": "Portfolio"})

    response = client.post(
        f"{BASE}/projects", headers=auth(factory, ALICE), json={"name": "Portfolio"}
    )

    assert response.status_code == 409


# --- cascade ------------------------------------------------------------------


def test_all_career_records_are_removed_with_their_user(
    client: TestClient, factory: TokenFactory
) -> None:
    for path, body in COLLECTIONS:
        create(client, factory, ALICE, path, body)

    with get_engine().begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM users"))
        remaining = {
            table: connection.execute(sqlalchemy.text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("user_skills", "experiences", "projects", "education")
        }

    assert remaining == {"user_skills": 0, "experiences": 0, "projects": 0, "education": 0}
