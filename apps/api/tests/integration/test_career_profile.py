"""Career profile endpoints against a real database.

Two things are being protected here: that a partial update means what it says,
and that one user can never reach another user's profile.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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

PROFILE = "/api/v1/career/profile"
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


def profile_rows() -> int:
    with get_engine().connect() as connection:
        return int(
            connection.execute(sqlalchemy.text("SELECT count(*) FROM career_profiles")).scalar_one()
        )


# --- creation on demand -------------------------------------------------------


def test_first_read_creates_an_empty_profile(client: TestClient, factory: TokenFactory) -> None:
    response = client.get(PROFILE, headers=auth(factory, ALICE))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["headline"] is None
    assert data["links"] == []
    assert profile_rows() == 1


def test_repeated_reads_do_not_create_extra_profiles(
    client: TestClient, factory: TokenFactory
) -> None:
    ids = {client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]["id"] for _ in range(3)}

    assert len(ids) == 1
    assert profile_rows() == 1


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    assert client.get(PROFILE).status_code == 401
    assert profile_rows() == 0


# --- updating -----------------------------------------------------------------


def test_patch_persists_supplied_fields(client: TestClient, factory: TokenFactory) -> None:
    response = client.patch(
        PROFILE,
        headers=auth(factory, ALICE),
        json={
            "headline": "Backend engineer",
            "years_of_experience": 3,
            "current_location": "Tel Aviv",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["headline"] == "Backend engineer"
    assert data["years_of_experience"] == 3

    reread = client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]
    assert reread["headline"] == "Backend engineer"


def test_omitted_fields_are_left_alone(client: TestClient, factory: TokenFactory) -> None:
    """A PATCH must not blank out what it did not mention."""
    client.patch(
        PROFILE,
        headers=auth(factory, ALICE),
        json={"headline": "Backend engineer", "current_location": "Tel Aviv"},
    )

    client.patch(PROFILE, headers=auth(factory, ALICE), json={"years_of_experience": 5})

    data = client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]
    assert data["headline"] == "Backend engineer"
    assert data["current_location"] == "Tel Aviv"
    assert data["years_of_experience"] == 5


def test_explicit_null_clears_a_field(client: TestClient, factory: TokenFactory) -> None:
    """Sending null is how a field is erased — distinct from omitting it."""
    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": "Backend engineer"})

    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": None})

    assert client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]["headline"] is None


def test_blank_string_is_stored_as_cleared(client: TestClient, factory: TokenFactory) -> None:
    """A form submits "" for an emptied field; that must not become stored data."""
    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": "Backend engineer"})

    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": "   "})

    assert client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]["headline"] is None


def test_links_round_trip(client: TestClient, factory: TokenFactory) -> None:
    response = client.patch(
        PROFILE,
        headers=auth(factory, ALICE),
        json={"links": [{"label": "GitHub", "url": "https://github.com/example"}]},
    )

    links = response.json()["data"]["links"]
    assert len(links) == 1
    assert links[0]["label"] == "GitHub"
    assert str(links[0]["url"]).startswith("https://github.com/example")


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"years_of_experience": -1},
        {"years_of_experience": 200},
        {"headline": "x" * 201},
        {"links": [{"label": "Bad", "url": "javascript:alert(1)"}]},
        {"links": [{"label": "", "url": "https://example.com"}]},
        {"unknown_field": "value"},
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient, factory: TokenFactory, body: dict[str, object]
) -> None:
    response = client.patch(PROFILE, headers=auth(factory, ALICE), json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_javascript_link_never_reaches_the_database(
    client: TestClient, factory: TokenFactory
) -> None:
    """Profile links render as anchors, so a non-http scheme is stored XSS."""
    client.patch(
        PROFILE,
        headers=auth(factory, ALICE),
        json={"links": [{"label": "Bad", "url": "javascript:alert(1)"}]},
    )

    with get_engine().connect() as connection:
        stored = connection.execute(sqlalchemy.text("SELECT links::text FROM career_profiles"))
        for (value,) in stored:
            assert "javascript" not in value.lower()


# --- ownership ----------------------------------------------------------------


def test_each_user_gets_their_own_profile(client: TestClient, factory: TokenFactory) -> None:
    alice = client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]["id"]
    bob = client.get(PROFILE, headers=auth(factory, BOB)).json()["data"]["id"]

    assert alice != bob
    assert profile_rows() == 2


def test_one_user_cannot_read_anothers_profile(client: TestClient, factory: TokenFactory) -> None:
    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": "Alice private headline"})

    bob_view = client.get(PROFILE, headers=auth(factory, BOB)).json()["data"]

    assert bob_view["headline"] is None


def test_one_user_cannot_modify_anothers_profile(client: TestClient, factory: TokenFactory) -> None:
    """The profile id is never an input, so there is nothing to point elsewhere.

    This asserts the consequence: Bob writing to /career/profile changes Bob's
    row and leaves Alice's untouched.
    """
    client.patch(PROFILE, headers=auth(factory, ALICE), json={"headline": "Alice"})

    client.patch(PROFILE, headers=auth(factory, BOB), json={"headline": "Bob"})

    alice_view = client.get(PROFILE, headers=auth(factory, ALICE)).json()["data"]
    assert alice_view["headline"] == "Alice"


def test_profile_is_removed_with_its_user(client: TestClient, factory: TokenFactory) -> None:
    """ON DELETE CASCADE, so deleting a user leaves no orphaned profile."""
    client.get(PROFILE, headers=auth(factory, ALICE))
    assert profile_rows() == 1

    with get_engine().begin() as connection:
        connection.execute(sqlalchemy.text("DELETE FROM users"))

    assert profile_rows() == 0
