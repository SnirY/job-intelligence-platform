"""Authenticated requests end to end, against a real database.

Covers the API surface of authentication: what reaches the database, what is
turned away at the door, and whether repeated sign-ins produce one user or
several.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jip_api.infrastructure.auth.clerk import reset_verifier_cache
from jip_api.infrastructure.db.session import get_engine, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks

pytestmark = pytest.mark.integration

ME = "/api/v1/users/me"
API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """An app wired to a fresh database and a locally served JWKS."""
    with serve_jwks(factory) as jwks_url:
        monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)
        monkeypatch.setenv("JIP_CLERK_ISSUER", ISSUER)
        monkeypatch.setenv("JIP_CLERK_JWKS_URL", jwks_url)
        monkeypatch.setenv("JIP_CLERK_AUTHORIZED_PARTIES", AUTHORIZED_PARTY)
        monkeypatch.setenv("JIP_CLERK_LEEWAY_SECONDS", "0")

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()

        # Build the schema with the real migrations rather than create_all, so
        # these tests fail if a migration and its model drift apart.
        alembic_config = Config(str(API_ROOT / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(API_ROOT / "migrations"))
        alembic_config.set_main_option("sqlalchemy.url", clean_database_url)
        command.upgrade(alembic_config, "head")

        from jip_api.main import create_app

        with TestClient(create_app(), raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def count_users() -> int:
    with get_engine().connect() as connection:
        return int(connection.execute(sqlalchemy.text("SELECT count(*) FROM users")).scalar_one())


# --- rejection ---------------------------------------------------------------


def test_missing_authorization_header_is_rejected(client: TestClient) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
        "token abc.def.ghi",
    ],
)
def test_malformed_authorization_headers_are_rejected(client: TestClient, header: str) -> None:
    response = client.get(ME, headers={"Authorization": header})

    assert response.status_code == 401


def test_expired_token_is_rejected(client: TestClient, factory: TokenFactory) -> None:
    token = factory.token(expires_in=dt.timedelta(seconds=-60))

    assert client.get(ME, headers=auth(token)).status_code == 401


def test_token_from_another_signing_key_is_rejected(client: TestClient) -> None:
    attacker = TokenFactory.create()

    assert client.get(ME, headers=auth(attacker.token())).status_code == 401


def test_rejection_does_not_disclose_the_reason(client: TestClient, factory: TokenFactory) -> None:
    """Every failure looks identical, so a caller cannot probe toward a pass."""
    expired = client.get(ME, headers=auth(factory.token(expires_in=dt.timedelta(seconds=-60))))
    wrong_party = client.get(ME, headers=auth(factory.token(azp="https://evil.example.com")))
    missing = client.get(ME)

    bodies = [
        {k: v for k, v in response.json()["error"].items() if k != "request_id"}
        for response in (expired, wrong_party, missing)
    ]
    assert bodies[0] == bodies[1] == bodies[2]
    assert "expired" not in str(bodies[0]).lower()


def test_rejected_request_creates_no_user(client: TestClient, factory: TokenFactory) -> None:
    client.get(ME, headers=auth(factory.token(expires_in=dt.timedelta(seconds=-60))))

    assert count_users() == 0


# --- acceptance and provisioning ---------------------------------------------


def test_valid_token_returns_the_user(client: TestClient, factory: TokenFactory) -> None:
    token = factory.token(subject="user_alice", email="alice@example.com", name="Alice")

    response = client.get(ME, headers=auth(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert uuid.UUID(data["id"])
    assert data["email"] == "alice@example.com"
    assert data["display_name"] == "Alice"


def test_response_never_exposes_the_provider_id(client: TestClient, factory: TokenFactory) -> None:
    response = client.get(ME, headers=auth(factory.token(subject="user_alice")))

    assert "clerk" not in response.text.lower()
    assert "user_alice" not in response.text


def test_first_sign_in_creates_exactly_one_user(client: TestClient, factory: TokenFactory) -> None:
    client.get(ME, headers=auth(factory.token(subject="user_alice")))

    assert count_users() == 1


def test_repeated_sign_in_does_not_duplicate_the_user(
    client: TestClient, factory: TokenFactory
) -> None:
    ids = set()
    for _ in range(4):
        response = client.get(ME, headers=auth(factory.token(subject="user_alice")))
        ids.add(response.json()["data"]["id"])

    assert len(ids) == 1
    assert count_users() == 1


def test_distinct_subjects_get_distinct_users(client: TestClient, factory: TokenFactory) -> None:
    first = client.get(ME, headers=auth(factory.token(subject="user_alice")))
    second = client.get(ME, headers=auth(factory.token(subject="user_bob")))

    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    assert count_users() == 2


def test_same_email_on_a_different_subject_does_not_take_over_the_account(
    client: TestClient, factory: TokenFactory
) -> None:
    """Identity is the subject, never the email address.

    If a shared email merged accounts, anyone who could get that address
    verified at the provider would inherit the original user's data.
    """
    original = client.get(
        ME, headers=auth(factory.token(subject="user_alice", email="shared@example.com"))
    )
    impostor = client.get(
        ME, headers=auth(factory.token(subject="user_mallory", email="shared@example.com"))
    )

    assert original.json()["data"]["id"] != impostor.json()["data"]["id"]
    assert count_users() == 2


def test_profile_claims_are_refreshed_on_later_sign_in(
    client: TestClient, factory: TokenFactory
) -> None:
    client.get(ME, headers=auth(factory.token(subject="user_alice", email="old@example.com")))

    response = client.get(
        ME, headers=auth(factory.token(subject="user_alice", email="new@example.com"))
    )

    assert response.json()["data"]["email"] == "new@example.com"
    assert count_users() == 1


def test_absent_claims_do_not_erase_stored_profile(
    client: TestClient, factory: TokenFactory
) -> None:
    """Clerk's default token carries no email; that must not wipe the cache."""
    client.get(ME, headers=auth(factory.token(subject="user_alice", email="alice@example.com")))

    response = client.get(ME, headers=auth(factory.token(subject="user_alice")))

    assert response.json()["data"]["email"] == "alice@example.com"


def test_client_supplied_user_id_is_ignored(client: TestClient, factory: TokenFactory) -> None:
    """Authorization comes from the token alone.

    A `user_id` in the query string, body, or a header is data — never an
    account selector (docs/10-api-contracts.md).
    """
    victim = client.get(ME, headers=auth(factory.token(subject="user_victim")))
    victim_id = victim.json()["data"]["id"]

    response = client.get(
        ME,
        params={"user_id": victim_id},
        headers={**auth(factory.token(subject="user_attacker")), "X-User-Id": victim_id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] != victim_id
