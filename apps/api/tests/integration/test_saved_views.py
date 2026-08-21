"""Saved views of the jobs list.

What these protect that a unit test cannot: that a view survives a round trip
through the database with the filters it was saved with, that names are unique
per user rather than globally, and that another user cannot see or delete one.

The case worth the file, though, is the last group. A stored view is a promise
about which jobs the reader will see, and the failure mode that matters is a
filter quietly going missing — the list coming back wider than the name says
with nothing admitting it.
"""

from __future__ import annotations

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
VIEWS = "/api/v1/job-views"
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


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def save(
    client: TestClient,
    factory: TokenFactory,
    name: str,
    filters: dict[str, Any] | None = None,
    subject: str = ALICE,
    expect: int = 201,
) -> dict[str, Any]:
    response = client.post(
        VIEWS,
        headers=auth(factory, subject),
        json={"name": name, "filters": filters or {}},
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def read(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> list[dict[str, Any]]:
    response = client.get(VIEWS, headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


# --- the round trip -----------------------------------------------------------


def test_a_view_comes_back_with_the_filters_it_was_saved_with(
    client: TestClient, factory: TokenFactory
) -> None:
    filters = {
        "search": "backend",
        "work_mode": "REMOTE",
        "min_score": 70,
        "max_score": 100,
        "sort": "BEST_ALIGNED",
    }
    save(client, factory, "Remote, strong", filters)

    views = read(client, factory)

    assert len(views) == 1
    assert views[0]["name"] == "Remote, strong"
    assert views[0]["filters"] == filters
    assert views[0]["is_readable"] is True


def test_a_view_does_not_remember_the_page(client: TestClient, factory: TokenFactory) -> None:
    """A view is a question. Where the reader had got to in the answer is not
    part of it, and storing it would drop somebody on page four of a list they
    have not seen."""
    save(client, factory, "Anything", {"search": "backend", "page": 4})

    assert "page" not in read(client, factory)[0]["filters"]


def test_an_empty_view_stores_nothing_rather_than_a_row_of_nulls(
    client: TestClient, factory: TokenFactory
) -> None:
    """ "Everything, newest first" is a real view, and it should read that way in
    the database rather than as eleven explicit nulls."""
    save(client, factory, "Everything", {"search": None, "company": None, "min_score": None})

    assert read(client, factory)[0]["filters"] == {}


def test_views_come_back_in_the_order_they_were_made(
    client: TestClient, factory: TokenFactory
) -> None:
    for name in ("First", "Second", "Third"):
        save(client, factory, name)

    assert [view["name"] for view in read(client, factory)] == ["First", "Second", "Third"]


# --- names --------------------------------------------------------------------


def test_a_repeated_name_is_refused_rather_than_overwritten(
    client: TestClient, factory: TokenFactory
) -> None:
    """Two things a user might mean by saving over a name — "update this" and "I
    forgot I had one" — and picking the destructive reading silently is not a
    guess worth making."""
    save(client, factory, "Remote")

    body = save(client, factory, "Remote", expect=409)

    assert "already have a view" in body["error"]["message"]
    assert len(read(client, factory)) == 1


def test_two_users_may_each_have_a_view_called_the_same_thing(
    client: TestClient, factory: TokenFactory
) -> None:
    save(client, factory, "Remote", subject=ALICE)
    save(client, factory, "Remote", subject=BOB)

    assert len(read(client, factory, ALICE)) == 1
    assert len(read(client, factory, BOB)) == 1


def test_a_name_is_trimmed_rather_than_stored_with_its_spaces(
    client: TestClient, factory: TokenFactory
) -> None:
    save(client, factory, "  Remote  ")

    assert read(client, factory)[0]["name"] == "Remote"


def test_a_blank_name_is_refused(client: TestClient, factory: TokenFactory) -> None:
    save(client, factory, "   ", expect=422)


def test_a_view_can_be_renamed(client: TestClient, factory: TokenFactory) -> None:
    view = save(client, factory, "Remote")

    response = client.patch(
        f"{VIEWS}/{view['id']}", headers=auth(factory), json={"name": "Remote and senior"}
    )

    assert response.status_code == 200, response.text
    assert read(client, factory)[0]["name"] == "Remote and senior"


def test_renaming_onto_another_name_is_refused(client: TestClient, factory: TokenFactory) -> None:
    save(client, factory, "Remote")
    second = save(client, factory, "Hybrid")

    response = client.patch(
        f"{VIEWS}/{second['id']}", headers=auth(factory), json={"name": "Remote"}
    )

    assert response.status_code == 409, response.text


# --- a view this version can no longer run ------------------------------------


def test_a_filter_that_no_longer_parses_makes_the_view_unreadable(
    client: TestClient, factory: TokenFactory
) -> None:
    """The case this module exists for.

    A view is a promise about which jobs the reader will see. Dropping a key the
    app no longer understands would return a *wider* list than the name says
    with nothing on screen admitting it — a narrower claim turned into a broader
    one by omission, which is the failure this codebase keeps meeting.

    Written by reaching past the API, because the API refuses to store one: the
    only way a view gets into this state is by the app changing underneath it.
    """
    view = save(client, factory, "Principals", {"seniority": "SENIOR"})

    from sqlalchemy import text

    from jip_api.infrastructure.db.session import new_session

    session = new_session()
    try:
        session.execute(
            text("UPDATE saved_job_views SET filters = :f WHERE id = :i"),
            {"f": '{"seniority": "ARCHMAGE"}', "i": view["id"]},
        )
        session.commit()
    finally:
        session.close()

    stored = read(client, factory)[0]

    assert stored["is_readable"] is False
    assert stored["unreadable"] == ["seniority"]
    # And the filter is still there to be read, not quietly removed.
    assert stored["filters"] == {"seniority": "ARCHMAGE"}


def test_a_key_this_version_does_not_have_is_never_stored(
    client: TestClient, factory: TokenFactory
) -> None:
    """The other direction. A client sending a filter the API does not know is a
    client ahead of its server, and storing the key would promise something this
    version cannot deliver."""
    save(client, factory, "From the future", {"search": "backend", "vibe": "good"})

    stored = read(client, factory)[0]

    assert stored["filters"] == {"search": "backend"}
    assert stored["is_readable"] is True


def test_a_score_outside_the_range_makes_the_view_unreadable(
    client: TestClient, factory: TokenFactory
) -> None:
    view = save(client, factory, "Impossible", {"min_score": 50})

    from sqlalchemy import text

    from jip_api.infrastructure.db.session import new_session

    session = new_session()
    try:
        session.execute(
            text("UPDATE saved_job_views SET filters = :f WHERE id = :i"),
            {"f": '{"min_score": 900}', "i": view["id"]},
        )
        session.commit()
    finally:
        session.close()

    assert read(client, factory)[0]["unreadable"] == ["min_score"]


# --- deletion and ownership ---------------------------------------------------


def test_a_view_can_be_deleted(client: TestClient, factory: TokenFactory) -> None:
    view = save(client, factory, "Remote")

    response = client.delete(f"{VIEWS}/{view['id']}", headers=auth(factory))

    assert response.status_code == 204, response.text
    assert read(client, factory) == []


def test_another_user_cannot_see_a_view(client: TestClient, factory: TokenFactory) -> None:
    save(client, factory, "Remote", subject=ALICE)

    assert read(client, factory, BOB) == []


def test_another_user_cannot_delete_a_view(client: TestClient, factory: TokenFactory) -> None:
    view = save(client, factory, "Remote", subject=ALICE)

    response = client.delete(f"{VIEWS}/{view['id']}", headers=auth(factory, BOB))

    assert response.status_code == 404, response.text
    assert len(read(client, factory, ALICE)) == 1


def test_another_user_cannot_rename_a_view(client: TestClient, factory: TokenFactory) -> None:
    view = save(client, factory, "Remote", subject=ALICE)

    response = client.patch(
        f"{VIEWS}/{view['id']}", headers=auth(factory, BOB), json={"name": "Mine now"}
    )

    assert response.status_code == 404, response.text


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(VIEWS).status_code == 401
    assert client.post(VIEWS, json={"name": "Remote"}).status_code == 401
