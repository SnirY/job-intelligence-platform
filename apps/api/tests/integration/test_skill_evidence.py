"""Saying why you have a skill, against a real database.

DEV-054. `docs/03-domain-model.md` specified `skill_evidence` and it was never
built, so the only way to demonstrate a skill was to attach it to a role or a
project. Anything learned outside employment could be claimed and never
evidenced, and the matcher scores a demonstrated skill above a listed one — so
the profile quietly penalised whoever's work is not on a payslip.

The ownership tests here are not ceremony. Evidence is free text about the
user's own history, and the route reaches it through two ids in the path; a
filter that checks the evidence id and forgets the user is a disclosure, not a
404.
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


def make_skill(client: TestClient, factory: TokenFactory, subject: str, name: str) -> str:
    response = client.post(
        f"{BASE}/skills",
        headers=auth(factory, subject),
        json={"name": name, "category": "LANGUAGE"},
    )
    assert response.status_code == 201, response.text
    skill_id: str = response.json()["data"]["id"]
    return skill_id


def add(
    client: TestClient, factory: TokenFactory, subject: str, skill_id: str, note: str
) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/skills/{skill_id}/evidence",
        headers=auth(factory, subject),
        json={"note": note},
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


# --- lifecycle ----------------------------------------------------------------


def test_a_new_skill_has_no_stated_reasons(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")

    response = client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE))

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_a_reason_can_be_added_and_read_back(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")

    created = add(client, factory, ALICE, skill_id, "Built a ray tracer over two winters.")

    listed = client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).json()[
        "data"
    ]
    assert [row["id"] for row in listed] == [created["id"]]
    assert listed[0]["note"] == "Built a ray tracer over two winters."
    assert listed[0]["source"] == "MANUAL"


def test_reasons_come_back_oldest_first(client: TestClient, factory: TokenFactory) -> None:
    """Order is part of the contract: the profile screen shows them as a list,
    and a list that reshuffles between reloads reads as data loss."""
    skill_id = make_skill(client, factory, ALICE, "Rust")
    first = add(client, factory, ALICE, skill_id, "Read the book cover to cover.")
    second = add(client, factory, ALICE, skill_id, "Built a ray tracer.")
    third = add(client, factory, ALICE, skill_id, "Ported a parser at work.")

    listed = client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).json()[
        "data"
    ]

    assert [row["id"] for row in listed] == [first["id"], second["id"], third["id"]]


def test_a_reason_can_be_removed(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")
    created = add(client, factory, ALICE, skill_id, "Built a ray tracer.")

    response = client.delete(
        f"{BASE}/skills/{skill_id}/evidence/{created['id']}", headers=auth(factory, ALICE)
    )

    assert response.status_code == 204
    assert (
        client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).json()[
            "data"
        ]
        == []
    )


def test_deleting_the_skill_takes_its_reasons_with_it(
    client: TestClient, factory: TokenFactory
) -> None:
    """The FK is ON DELETE CASCADE. Without it a deleted skill would leave rows
    that no endpoint can reach and no user can see."""
    skill_id = make_skill(client, factory, ALICE, "Rust")
    add(client, factory, ALICE, skill_id, "Built a ray tracer.")

    assert (
        client.delete(f"{BASE}/skills/{skill_id}", headers=auth(factory, ALICE)).status_code == 204
    )

    assert (
        client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).status_code
        == 404
    )


# --- what counts as a reason --------------------------------------------------


@pytest.mark.parametrize("note", ["", "   ", "\n\t "], ids=["empty", "spaces", "whitespace"])
def test_a_blank_reason_is_refused(client: TestClient, factory: TokenFactory, note: str) -> None:
    """A row saying "I have this skill because" and nothing else is worse than
    no row: it raises the score and tells a reader nothing."""
    skill_id = make_skill(client, factory, ALICE, "Rust")

    response = client.post(
        f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE), json={"note": note}
    )

    assert response.status_code in (400, 422), response.text
    assert (
        client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).json()[
            "data"
        ]
        == []
    )


def test_surrounding_whitespace_is_stripped(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")

    created = add(client, factory, ALICE, skill_id, "  Built a ray tracer.\n")

    assert created["note"] == "Built a ray tracer."


def test_the_same_reason_twice_is_kept_twice(client: TestClient, factory: TokenFactory) -> None:
    """The unique constraint is on (skill, source, entity_id), and manual rows
    have a null entity_id — which in Postgres never collides. That is deliberate:
    two courses can produce two honest sentences, and deduplicating free text the
    user typed would be the platform overruling them about their own history."""
    skill_id = make_skill(client, factory, ALICE, "Rust")
    add(client, factory, ALICE, skill_id, "Built a ray tracer.")

    second = client.post(
        f"{BASE}/skills/{skill_id}/evidence",
        headers=auth(factory, ALICE),
        json={"note": "Built a ray tracer."},
    )

    assert second.status_code == 201, second.text


# --- ownership ----------------------------------------------------------------


def test_another_user_cannot_read_your_reasons(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")
    add(client, factory, ALICE, skill_id, "Built a ray tracer.")

    response = client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_another_user_cannot_add_to_your_skill(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")

    response = client.post(
        f"{BASE}/skills/{skill_id}/evidence",
        headers=auth(factory, BOB),
        json={"note": "I put this here."},
    )

    assert response.status_code == 404
    assert (
        client.get(f"{BASE}/skills/{skill_id}/evidence", headers=auth(factory, ALICE)).json()[
            "data"
        ]
        == []
    )


def test_another_user_cannot_delete_your_reason(client: TestClient, factory: TokenFactory) -> None:
    """Bob owns a skill of his own, so the route's ownership check on the *skill*
    passes and the check on the *evidence* is the only thing standing between him
    and Alice's row."""
    alice_skill = make_skill(client, factory, ALICE, "Rust")
    alice_evidence = add(client, factory, ALICE, alice_skill, "Built a ray tracer.")
    bob_skill = make_skill(client, factory, BOB, "Rust")

    response = client.delete(
        f"{BASE}/skills/{bob_skill}/evidence/{alice_evidence['id']}", headers=auth(factory, BOB)
    )

    assert response.status_code == 404
    assert (
        len(
            client.get(
                f"{BASE}/skills/{alice_skill}/evidence", headers=auth(factory, ALICE)
            ).json()["data"]
        )
        == 1
    )


def test_a_reason_belonging_to_your_other_skill_is_not_deletable_here(
    client: TestClient, factory: TokenFactory
) -> None:
    """Both ids are Alice's, but they do not go together. Scoping on the evidence
    id alone would delete the right row for the wrong reason."""
    rust = make_skill(client, factory, ALICE, "Rust")
    python = make_skill(client, factory, ALICE, "Python")
    evidence = add(client, factory, ALICE, rust, "Built a ray tracer.")

    response = client.delete(
        f"{BASE}/skills/{python}/evidence/{evidence['id']}", headers=auth(factory, ALICE)
    )

    assert response.status_code == 404
    assert (
        len(
            client.get(f"{BASE}/skills/{rust}/evidence", headers=auth(factory, ALICE)).json()[
                "data"
            ]
        )
        == 1
    )


def test_an_unknown_skill_is_a_404(client: TestClient, factory: TokenFactory) -> None:
    response = client.get(f"{BASE}/skills/{uuid.uuid4()}/evidence", headers=auth(factory, ALICE))

    assert response.status_code == 404


def test_unauthenticated_access_is_refused(client: TestClient, factory: TokenFactory) -> None:
    skill_id = make_skill(client, factory, ALICE, "Rust")

    assert client.get(f"{BASE}/skills/{skill_id}/evidence").status_code == 401
    assert client.post(f"{BASE}/skills/{skill_id}/evidence", json={"note": "x"}).status_code == 401
    assert client.delete(f"{BASE}/skills/{skill_id}/evidence/{uuid.uuid4()}").status_code == 401
