"""Target role CRUD against a real database.

The ownership block is the important part: these rows are addressed by id, so
unlike the profile there *is* something a caller can point at another user's
data.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks

pytestmark = pytest.mark.integration

ROLES = "/api/v1/career/target-roles"
API_ROOT = Path(__file__).resolve().parents[2]

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

        with TestClient(create_app(), raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def create(
    client: TestClient, factory: TokenFactory, subject: str, **fields: object
) -> dict[str, object]:
    body: dict[str, object] = {"title": "Backend Engineer", **fields}
    response = client.post(ROLES, headers=auth(factory, subject), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()["data"]
    return created


# --- basics -------------------------------------------------------------------


def test_list_starts_empty(client: TestClient, factory: TokenFactory) -> None:
    response = client.get(ROLES, headers=auth(factory, ALICE))

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_create_then_list(client: TestClient, factory: TokenFactory) -> None:
    created = create(
        client, factory, ALICE, role_family="Backend", desired_seniority="JUNIOR", priority=2
    )

    assert created["title"] == "Backend Engineer"
    assert created["desired_seniority"] == "JUNIOR"
    assert created["is_active"] is True

    listed = client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


def test_list_is_ordered_by_priority(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, ALICE, title="Third", priority=9)
    create(client, factory, ALICE, title="First", priority=1)
    create(client, factory, ALICE, title="Second", priority=5)

    listed = client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]
    titles = [row["title"] for row in listed]

    assert titles == ["First", "Second", "Third"]


def test_update_changes_only_supplied_fields(client: TestClient, factory: TokenFactory) -> None:
    created = create(client, factory, ALICE, role_family="Backend", priority=3)

    response = client.patch(
        f"{ROLES}/{created['id']}",
        headers=auth(factory, ALICE),
        json={"is_active": False},
    )

    assert response.status_code == 200
    updated = response.json()["data"]
    assert updated["is_active"] is False
    assert updated["role_family"] == "Backend"
    assert updated["priority"] == 3


def test_delete_removes_the_role(client: TestClient, factory: TokenFactory) -> None:
    created = create(client, factory, ALICE)

    response = client.delete(f"{ROLES}/{created['id']}", headers=auth(factory, ALICE))

    assert response.status_code == 204
    assert client.get(ROLES, headers=auth(factory, ALICE)).json()["data"] == []


def test_duplicate_title_is_refused(client: TestClient, factory: TokenFactory) -> None:
    """A double-submitted form must not create two identical targets."""
    create(client, factory, ALICE, title="Backend Engineer")

    response = client.post(ROLES, headers=auth(factory, ALICE), json={"title": "Backend Engineer"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_two_users_may_share_a_title(client: TestClient, factory: TokenFactory) -> None:
    """Uniqueness is per user, not global."""
    create(client, factory, ALICE, title="Backend Engineer")
    create(client, factory, BOB, title="Backend Engineer")

    assert len(client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]) == 1
    assert len(client.get(ROLES, headers=auth(factory, BOB)).json()["data"]) == 1


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "Valid", "priority": -1},
        {"title": "Valid", "desired_seniority": "OVERLORD"},
        {"title": "Valid", "unexpected": 1},
    ],
)
def test_invalid_creates_are_rejected(
    client: TestClient, factory: TokenFactory, body: dict[str, object]
) -> None:
    response = client.post(ROLES, headers=auth(factory, ALICE), json=body)

    assert response.status_code == 422
    assert client.get(ROLES, headers=auth(factory, ALICE)).json()["data"] == []


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(ROLES).status_code == 401
    assert client.post(ROLES, json={"title": "Backend"}).status_code == 401


# --- ownership ----------------------------------------------------------------


def test_users_only_see_their_own_roles(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, ALICE, title="Alice role")
    create(client, factory, BOB, title="Bob role")

    alice = client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]

    assert [row["title"] for row in alice] == ["Alice role"]


def test_reading_another_users_role_is_not_possible(
    client: TestClient, factory: TokenFactory
) -> None:
    """The list endpoint is the only read path, and it is scoped."""
    alice_role = create(client, factory, ALICE, title="Alice role")

    bob_view = client.get(ROLES, headers=auth(factory, BOB)).json()["data"]

    assert all(row["id"] != alice_role["id"] for row in bob_view)


def test_updating_another_users_role_is_refused(client: TestClient, factory: TokenFactory) -> None:
    alice_role = create(client, factory, ALICE, title="Alice role")

    response = client.patch(
        f"{ROLES}/{alice_role['id']}",
        headers=auth(factory, BOB),
        json={"title": "Hijacked"},
    )

    assert response.status_code == 404
    still = client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]
    assert still[0]["title"] == "Alice role"


def test_deleting_another_users_role_is_refused(client: TestClient, factory: TokenFactory) -> None:
    alice_role = create(client, factory, ALICE, title="Alice role")

    response = client.delete(f"{ROLES}/{alice_role['id']}", headers=auth(factory, BOB))

    assert response.status_code == 404
    assert len(client.get(ROLES, headers=auth(factory, ALICE)).json()["data"]) == 1


def test_another_users_role_is_indistinguishable_from_a_missing_one(
    client: TestClient, factory: TokenFactory
) -> None:
    """Both answer 404.

    A different status for "exists but not yours" would let a caller enumerate
    which ids other users hold.
    """
    alice_role = create(client, factory, ALICE, title="Alice role")

    foreign = client.delete(f"{ROLES}/{alice_role['id']}", headers=auth(factory, BOB))
    missing = client.delete(f"{ROLES}/{uuid.uuid4()}", headers=auth(factory, BOB))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]


def test_roles_are_removed_with_their_user(client: TestClient, factory: TokenFactory) -> None:
    import sqlalchemy

    from jip_api.infrastructure.db.session import get_engine

    create(client, factory, ALICE, title="Alice role")

    with get_engine().begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM users"))
        remaining = connection.execute(
            sqlalchemy.text("SELECT count(*) FROM target_roles")
        ).scalar_one()

    assert remaining == 0
