"""Certifications against a real database.

DEV-052. Specified in `docs/01`, `docs/03` and `docs/06`, built in none of them
beyond a free-text box in the resume editor. The cost was not the missing
collection: with no CERTIFICATION requirement type, a posting demanding one was
read as EDUCATION and a user who held it was told their education did not appear
to cover it — a BLOCKER, at CORE importance.

The date constraints get their own tests because they are the reason this is a
separate table from `education`. A credential that expires before it was issued
is nonsense the database should refuse whatever the caller believes.
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

from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/career"
ALICE = "user_alice"
BOB = "user_bob"

AWS = {"name": "AWS Certified Solutions Architect", "issuer": "Amazon Web Services"}


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


def add(client: TestClient, factory: TokenFactory, subject: str, **fields: Any) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/certifications", headers=auth(factory, subject), json={**AWS, **fields}
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


def listed(client: TestClient, factory: TokenFactory, subject: str) -> list[dict[str, Any]]:
    response = client.get(f"{BASE}/certifications", headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["data"]
    return rows


# --- lifecycle ----------------------------------------------------------------


def test_the_collection_starts_empty(client: TestClient, factory: TokenFactory) -> None:
    assert listed(client, factory, ALICE) == []


def test_a_certification_can_be_added_and_read_back(
    client: TestClient, factory: TokenFactory
) -> None:
    created = add(
        client,
        factory,
        ALICE,
        issued_on="2023-05-01",
        expires_on="2026-05-01",
        credential_id="ABCD-1234",
        credential_url="https://example.com/verify/ABCD-1234",
    )

    rows = listed(client, factory, ALICE)
    assert [row["id"] for row in rows] == [created["id"]]
    assert rows[0]["name"] == "AWS Certified Solutions Architect"
    assert rows[0]["issuer"] == "Amazon Web Services"
    assert rows[0]["expires_on"] == "2026-05-01"
    assert rows[0]["credential_id"] == "ABCD-1234"
    assert rows[0]["verification_status"] == "USER_CONFIRMED"


def test_a_certification_can_be_edited(client: TestClient, factory: TokenFactory) -> None:
    created = add(client, factory, ALICE)

    response = client.patch(
        f"{BASE}/certifications/{created['id']}",
        headers=auth(factory, ALICE),
        json={"expires_on": "2027-01-01"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["expires_on"] == "2027-01-01"
    assert response.json()["data"]["name"] == created["name"], "an edit must not clear other fields"


def test_a_certification_can_be_removed(client: TestClient, factory: TokenFactory) -> None:
    created = add(client, factory, ALICE)

    response = client.delete(f"{BASE}/certifications/{created['id']}", headers=auth(factory, ALICE))

    assert response.status_code == 204
    assert listed(client, factory, ALICE) == []


def test_credentials_that_never_expire_are_listed_first(
    client: TestClient, factory: TokenFactory
) -> None:
    """A null expiry means "does not expire", so those are the strongest thing
    on the list rather than the least specified. Sorting them last would bury a
    permanent credential under lapsed ones."""
    add(client, factory, ALICE, name="Expiring soon", expires_on="2026-01-01")
    add(client, factory, ALICE, name="Never expires")
    add(client, factory, ALICE, name="Expiring later", expires_on="2030-01-01")

    assert [row["name"] for row in listed(client, factory, ALICE)] == [
        "Never expires",
        "Expiring later",
        "Expiring soon",
    ]


# --- what the dates may say ---------------------------------------------------


def test_expiry_before_issue_is_refused(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(
        f"{BASE}/certifications",
        headers=auth(factory, ALICE),
        json={**AWS, "issued_on": "2025-01-01", "expires_on": "2024-01-01"},
    )

    assert response.status_code == 422, response.text
    assert listed(client, factory, ALICE) == []


def test_a_certification_with_no_expiry_is_accepted(
    client: TestClient, factory: TokenFactory
) -> None:
    """Not every credential expires, and an empty field must not be read as
    "unknown" — the matcher treats a null expiry as still valid, which is only
    honest if the API lets the user say it plainly."""
    created = add(client, factory, ALICE, issued_on="2023-05-01")

    assert created["expires_on"] is None


@pytest.mark.parametrize("field", ["name", "issuer"], ids=["name", "issuer"])
def test_the_identifying_fields_cannot_be_blank(
    client: TestClient, factory: TokenFactory, field: str
) -> None:
    response = client.post(
        f"{BASE}/certifications", headers=auth(factory, ALICE), json={**AWS, field: ""}
    )

    assert response.status_code == 422, response.text


def test_a_bad_verification_link_is_refused(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(
        f"{BASE}/certifications",
        headers=auth(factory, ALICE),
        json={**AWS, "credential_url": "not-a-url"},
    )

    assert response.status_code == 422, response.text


# --- ownership ----------------------------------------------------------------


def test_another_user_sees_none_of_yours(client: TestClient, factory: TokenFactory) -> None:
    add(client, factory, ALICE)

    assert listed(client, factory, BOB) == []


def test_another_user_cannot_edit_yours(client: TestClient, factory: TokenFactory) -> None:
    created = add(client, factory, ALICE)

    response = client.patch(
        f"{BASE}/certifications/{created['id']}",
        headers=auth(factory, BOB),
        json={"issuer": "Mine now"},
    )

    assert response.status_code == 404
    assert listed(client, factory, ALICE)[0]["issuer"] == "Amazon Web Services"


def test_another_user_cannot_delete_yours(client: TestClient, factory: TokenFactory) -> None:
    created = add(client, factory, ALICE)

    response = client.delete(f"{BASE}/certifications/{created['id']}", headers=auth(factory, BOB))

    assert response.status_code == 404
    assert len(listed(client, factory, ALICE)) == 1


def test_an_unknown_certification_is_a_404(client: TestClient, factory: TokenFactory) -> None:
    response = client.delete(f"{BASE}/certifications/{uuid.uuid4()}", headers=auth(factory, ALICE))

    assert response.status_code == 404


def test_unauthenticated_access_is_refused(client: TestClient) -> None:
    assert client.get(f"{BASE}/certifications").status_code == 401
    assert client.post(f"{BASE}/certifications", json=AWS).status_code == 401
    assert client.delete(f"{BASE}/certifications/{uuid.uuid4()}").status_code == 401
