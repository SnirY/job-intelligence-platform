"""Board discovery end to end, against a real database.

The properties worth protecting here, in order:

- a scan writes candidates and **never** creates a job;
- a second scan of the same board offers nothing new;
- a dismissed posting is never resurrected by a later scan;
- a promoted posting becomes an ordinary job, distinguishable only by how it
  arrived;
- another user's boards and postings are unreachable through every route.

The boards themselves are stubbed. `packages/job-sources` has its own tests for
the three providers and none of them opens a socket either — what is under test
here is what this system does with what a board returned.
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
from jip_sources import BoardOutcome, RawPosting, ScanResult
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/discovery"
ALICE = "user_alice"
BOB = "user_bob"

DESCRIPTION = (
    "We are hiring a Senior Backend Engineer for the shipment platform. You "
    "will build REST services in Python and own the PostgreSQL schema behind "
    "carrier reconciliation. Hybrid from Lisbon, two days in the office."
) * 2


def posting(external_id: str = "gh-1", title: str = "Senior Backend Engineer") -> RawPosting:
    return RawPosting(
        provider="greenhouse",
        board="verdant",
        external_id=external_id,
        title=title,
        url=f"https://boards.greenhouse.io/verdant/jobs/{external_id}",
        company="Verdant Logistics",
        location="Lisbon, Portugal",
        description_text=DESCRIPTION,
    )


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def boards_return(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Decide what the stubbed boards hand back, per test."""

    def _set(*postings: RawPosting, error: str | None = None) -> None:
        def _scan(refs: Any, **_kwargs: Any) -> ScanResult:
            return ScanResult(
                outcomes=tuple(
                    BoardOutcome(
                        board=ref,
                        postings=() if error else tuple(postings),
                        error=error,
                        error_code="HTTP_ERROR" if error else None,
                    )
                    for ref in refs
                )
            )

        monkeypatch.setattr("jip_api.application.discovery.scanning.scan", _scan)

    _set(posting())
    return _set


@pytest.fixture
def client(
    factory: TokenFactory,
    clean_database_url: str,
    dispatcher: RecordingDispatcher,
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
        app.dependency_overrides[get_dispatcher] = lambda: dispatcher

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_engine_cache()
        reset_task_caches()
        reset_verifier_cache()


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def add_board(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/boards",
        headers=auth(factory, subject),
        json={"provider": "greenhouse", "token": "verdant", "label": "Verdant Logistics"},
    )
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


def run_scan(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> None:
    """Trigger the scan the way the worker would, since the queue is stubbed."""
    from jip_api.application.discovery.scanning import run_scan as scan_now
    from jip_api.infrastructure.db.session import new_session

    response = client.post(f"{BASE}/scan", headers=auth(factory, subject))
    assert response.status_code == 200, response.text

    session = new_session()
    try:
        user_id = _user_id(client, factory, subject)
        scan_now(session, user_id)
        session.commit()
    finally:
        session.close()


def _user_id(client: TestClient, factory: TokenFactory, subject: str) -> uuid.UUID:
    me = client.get("/api/v1/users/me", headers=auth(factory, subject))
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["data"]["id"])


def pending(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> list[Any]:
    response = client.get(f"{BASE}/postings", headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    rows: list[Any] = response.json()["data"]
    return rows


# --- boards -------------------------------------------------------------------


def test_a_board_can_be_watched(client: TestClient, factory: TokenFactory) -> None:
    board = add_board(client, factory)

    assert board["provider"] == "greenhouse"
    assert board["token"] == "verdant"
    assert board["paused_at"] is None
    assert board["last_scanned_at"] is None


def test_an_unknown_provider_is_refused(client: TestClient, factory: TokenFactory) -> None:
    """Storing it would create a row every future scan reports as a failure."""
    response = client.post(
        f"{BASE}/boards",
        headers=auth(factory),
        json={"provider": "linkedin", "token": "somewhere"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("token", ["../../etc/passwd", "a?b", "a@evil.example.com"])
def test_a_token_that_could_leave_the_path_is_refused(
    client: TestClient, factory: TokenFactory, token: str
) -> None:
    """The host is fixed in the provider module, so the token is the only part
    of the URL that comes from a user."""
    response = client.post(
        f"{BASE}/boards", headers=auth(factory), json={"provider": "greenhouse", "token": token}
    )

    assert response.status_code == 422


def test_the_same_board_cannot_be_watched_twice(client: TestClient, factory: TokenFactory) -> None:
    add_board(client, factory)

    again = client.post(
        f"{BASE}/boards",
        headers=auth(factory),
        json={"provider": "greenhouse", "token": "verdant"},
    )

    assert again.status_code == 409


def test_a_paused_board_is_not_scanned(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    board = add_board(client, factory)
    client.post(f"{BASE}/boards/{board['id']}/pause", headers=auth(factory))

    queued = client.post(f"{BASE}/scan", headers=auth(factory))

    assert queued.json()["data"]["boards"] == 0


def test_removing_a_board_keeps_what_it_found(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """They were offered and may have been acted on. Deleting that history
    because the source was removed would rewrite what happened."""
    board = add_board(client, factory)
    run_scan(client, factory)
    assert len(pending(client, factory)) == 1

    removed = client.delete(f"{BASE}/boards/{board['id']}", headers=auth(factory))

    assert removed.status_code == 204
    assert len(pending(client, factory)) == 1


# --- scanning -----------------------------------------------------------------


def test_a_scan_produces_candidates_and_no_jobs(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """The rule the whole feature is built on."""
    add_board(client, factory)

    run_scan(client, factory)

    assert len(pending(client, factory)) == 1
    jobs = client.get("/api/v1/jobs", headers=auth(factory))
    assert jobs.json()["meta"]["total"] == 0


def test_a_second_scan_offers_nothing_new(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """Without this the review list is unusable by the second week."""
    add_board(client, factory)

    run_scan(client, factory)
    run_scan(client, factory)

    assert len(pending(client, factory)) == 1


def test_a_scan_records_a_failure_against_the_board(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """Per board, so a company that stopped being readable can be named."""
    add_board(client, factory)
    boards_return(error="The board returned 404.")

    run_scan(client, factory)

    board = client.get(f"{BASE}/boards", headers=auth(factory)).json()["data"][0]
    assert board["last_error"] == "The board returned 404."
    assert board["last_scanned_at"] is not None


def test_a_later_scan_clears_a_fixed_failure(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    add_board(client, factory)
    boards_return(error="The board returned 404.")
    run_scan(client, factory)

    boards_return(posting())
    run_scan(client, factory)

    board = client.get(f"{BASE}/boards", headers=auth(factory)).json()["data"][0]
    assert board["last_error"] is None


# --- the decision -------------------------------------------------------------


def test_a_dismissed_posting_leaves_the_list(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    dismissed = client.post(f"{BASE}/postings/{row['id']}/dismiss", headers=auth(factory))

    assert dismissed.status_code == 200
    assert pending(client, factory) == []


def test_a_rescan_never_resurrects_a_dismissal(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """A review list that hands back what you have already rejected is one you
    stop opening."""
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]
    client.post(f"{BASE}/postings/{row['id']}/dismiss", headers=auth(factory))

    run_scan(client, factory)

    assert pending(client, factory) == []


def test_promoting_creates_an_ordinary_job(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """Distinguishable only by how it arrived, and by a person having said yes."""
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    promoted = client.post(f"{BASE}/postings/{row['id']}/promote", headers=auth(factory), json={})

    assert promoted.status_code == 201
    job_id = promoted.json()["data"]["job_id"]
    job = client.get(f"/api/v1/jobs/{job_id}", headers=auth(factory)).json()["data"]
    assert job["import_method"] == "DISCOVERED"
    assert job["title"] == "Senior Backend Engineer"
    assert job["description"].startswith("We are hiring")
    assert job["status"] == "RAW"


def test_a_promoted_posting_leaves_the_list(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    client.post(f"{BASE}/postings/{row['id']}/promote", headers=auth(factory), json={})

    assert pending(client, factory) == []


def test_promoting_twice_returns_the_same_job(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """A double click on a slow connection is not an error."""
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    first = client.post(f"{BASE}/postings/{row['id']}/promote", headers=auth(factory), json={})
    second = client.post(f"{BASE}/postings/{row['id']}/promote", headers=auth(factory), json={})

    assert first.json()["data"]["job_id"] == second.json()["data"]["job_id"]


def test_promoting_something_already_saved_is_reported(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    """A normal case here, not an edge one: a board may well list a role the
    user pasted last week."""
    client.post(
        "/api/v1/jobs",
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": DESCRIPTION,
        },
    )
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    response = client.post(f"{BASE}/postings/{row['id']}/promote", headers=auth(factory), json={})

    assert response.status_code == 409
    assert response.json()["error"]["details"]["existing_title"] == "Senior Backend Engineer"


def test_the_duplicate_can_be_overridden(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    client.post(
        "/api/v1/jobs",
        headers=auth(factory),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": DESCRIPTION,
        },
    )
    add_board(client, factory)
    run_scan(client, factory)
    row = pending(client, factory)[0]

    response = client.post(
        f"{BASE}/postings/{row['id']}/promote",
        headers=auth(factory),
        json={"allow_duplicate": True},
    )

    assert response.status_code == 201


# --- ownership ----------------------------------------------------------------


def test_boards_are_scoped_to_the_caller(client: TestClient, factory: TokenFactory) -> None:
    add_board(client, factory, subject=ALICE)

    assert len(client.get(f"{BASE}/boards", headers=auth(factory, ALICE)).json()["data"]) == 1
    assert client.get(f"{BASE}/boards", headers=auth(factory, BOB)).json()["data"] == []


def test_postings_are_scoped_to_the_caller(
    client: TestClient, factory: TokenFactory, boards_return: Any
) -> None:
    add_board(client, factory, subject=ALICE)
    run_scan(client, factory, subject=ALICE)

    assert len(pending(client, factory, ALICE)) == 1
    assert pending(client, factory, BOB) == []


@pytest.mark.parametrize("suffix", ["/pause", "/resume", ""])
def test_another_user_cannot_reach_a_board(
    client: TestClient, factory: TokenFactory, suffix: str
) -> None:
    board = add_board(client, factory, subject=ALICE)
    method = client.delete if suffix == "" else client.post

    response = method(f"{BASE}/boards/{board['id']}{suffix}", headers=auth(factory, BOB))

    assert response.status_code == 404


@pytest.mark.parametrize("action", ["dismiss", "promote"])
def test_another_user_cannot_decide_about_a_posting(
    client: TestClient, factory: TokenFactory, boards_return: Any, action: str
) -> None:
    add_board(client, factory, subject=ALICE)
    run_scan(client, factory, subject=ALICE)
    row = pending(client, factory, ALICE)[0]

    response = client.post(
        f"{BASE}/postings/{row['id']}/{action}", headers=auth(factory, BOB), json={}
    )

    assert response.status_code == 404


def test_every_discovery_route_rejects_an_anonymous_caller(client: TestClient) -> None:
    assert client.get(f"{BASE}/boards").status_code == 401
    assert client.get(f"{BASE}/postings").status_code == 401
    assert client.post(f"{BASE}/scan").status_code == 401
    assert client.get(f"{BASE}/providers").status_code == 401
