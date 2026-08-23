"""Cover letter routes, against a real database.

What the rules *say* is tested in `unit/test_cover_letter_truth.py`, which is
where the setting that matters lives. This file covers what only a real database
and a real request can show: that a letter cannot be drafted from nothing, that
an edit changes what the attached claims mean, and that none of it is reachable
by another user.

Drafting is not exercised end to end here. It needs a career profile, an
analysis and a match before a model is even called, and `test_resume_tailoring`
already carries that setup for the pipeline this borrows. What is asserted is
the boundary: no match, no letter.
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
from jip_api.domain.resumes.cover_letters import (
    CoverLetter,
    CoverLetterClaim,
    CoverLetterStatus,
)
from jip_api.domain.resumes.tailoring import ClaimStatus
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
JOBS = "/api/v1/jobs"
LETTERS = "/api/v1/cover-letters"
ALICE = "user_alice"
BOB = "user_bob"

DESCRIPTION = (
    "We are hiring a Senior Backend Engineer for the shipment platform. You "
    "will build REST services in Python and own the PostgreSQL schema."
) * 3

BODY = "I have built REST services in Python and FastAPI."


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


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


def make_job(client: TestClient, factory: TokenFactory, subject: str = ALICE) -> str:
    response = client.post(
        JOBS,
        headers=auth(factory, subject),
        json={
            "import_method": "PASTED_DESCRIPTION",
            "title": "Senior Backend Engineer",
            "description": DESCRIPTION,
        },
    )
    assert response.status_code == 201, response.text
    job_id: str = response.json()["data"]["id"]
    return job_id


def seed_letter(
    client: TestClient,
    factory: TokenFactory,
    job_id: str,
    *,
    subject: str = ALICE,
    claims: bool = False,
) -> str:
    """A drafted letter, written straight to the database.

    Drafting properly needs a match, an analysis and a model. This file is about
    the routes around a letter rather than about producing one, so the row is
    made directly and the pipeline is left to its own tests.
    """
    me = client.get("/api/v1/users/me", headers=auth(factory, subject))
    user_id = uuid.UUID(me.json()["data"]["id"])

    session = new_session()
    try:
        letter = CoverLetter(
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            status=CoverLetterStatus.DRAFTED,
            angle="Why this candidate fits",
            body=BODY,
        )
        session.add(letter)
        session.flush()
        if claims:
            session.add(
                CoverLetterClaim(
                    user_id=user_id,
                    cover_letter_id=letter.id,
                    text="I reduced errors by 40%.",
                    status=ClaimStatus.BLOCKED,
                    explanation="The figure 40% is not in your profile.",
                    confidence=90,
                )
            )
        session.commit()
        return str(letter.id)
    finally:
        session.close()


# --- there has to be something to write from -----------------------------------


def test_a_job_with_no_match_cannot_have_a_letter(
    client: TestClient, factory: TokenFactory
) -> None:
    """A letter argues from evidence, and the evidence is what matching produced.

    Refused with a reason rather than drafting something generic.
    """
    job_id = make_job(client, factory)

    response = client.post(f"{JOBS}/{job_id}/cover-letter", headers=auth(factory), json={})

    # 409, not 422: the resource's current state refuses the move rather than
    # the request being malformed. The same reading `StrategyNotPossibleError`
    # gets for the same situation.
    assert response.status_code == 409
    assert "matched" in response.json()["error"]["message"].lower()


def test_a_job_with_no_letter_answers_null(client: TestClient, factory: TokenFactory) -> None:
    """An ordinary state, not an error."""
    job_id = make_job(client, factory)

    response = client.get(f"{JOBS}/{job_id}/cover-letter", headers=auth(factory))

    assert response.status_code == 200
    assert response.json()["data"] is None


# --- what a letter carries ------------------------------------------------------


def test_the_claims_travel_with_the_letter(client: TestClient, factory: TokenFactory) -> None:
    """Not a separate call.

    A draft with a blocked claim is one the user must not send, and a payload
    that made the warning optional to fetch would make it optional to see.
    """
    job_id = make_job(client, factory)
    seed_letter(client, factory, job_id, claims=True)

    data = client.get(f"{JOBS}/{job_id}/cover-letter", headers=auth(factory)).json()["data"]

    assert data["body"] == BODY
    assert [c["status"] for c in data["claims"]] == ["BLOCKED"]
    assert "40%" in data["claims"][0]["explanation"]


# --- what a person does to it ---------------------------------------------------


def test_editing_marks_it_as_theirs(client: TestClient, factory: TokenFactory) -> None:
    """The status has to change, because the claims no longer describe the text.

    They were computed against the model's words. Leaving the status at DRAFTED
    would let a screen keep presenting them as though they still applied.
    """
    job_id = make_job(client, factory)
    letter_id = seed_letter(client, factory, job_id)

    response = client.patch(
        f"{LETTERS}/{letter_id}", headers=auth(factory), json={"body": "My own words."}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "EDITED"
    assert data["body"] == "My own words."
    assert data["edited_at"] is not None


def test_editing_after_approval_withdraws_it(client: TestClient, factory: TokenFactory) -> None:
    """Approval was of the previous text, and this is not that text."""
    job_id = make_job(client, factory)
    letter_id = seed_letter(client, factory, job_id)
    client.post(f"{LETTERS}/{letter_id}/approve", headers=auth(factory))

    data = client.patch(
        f"{LETTERS}/{letter_id}", headers=auth(factory), json={"body": "Changed."}
    ).json()["data"]

    assert data["approved_at"] is None


def test_approving_a_letter_with_a_blocked_claim_is_allowed(
    client: TestClient, factory: TokenFactory
) -> None:
    """`docs/06` asks for a missing metric rather than refusing the document.

    The user may know the figure is real. The screen shows them what they are
    approving over; the API does not overrule them.
    """
    job_id = make_job(client, factory)
    letter_id = seed_letter(client, factory, job_id, claims=True)

    response = client.post(f"{LETTERS}/{letter_id}/approve", headers=auth(factory))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "APPROVED"


def test_an_empty_letter_cannot_be_approved(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    letter_id = seed_letter(client, factory, job_id)

    session = new_session()
    try:
        letter = session.get(CoverLetter, uuid.UUID(letter_id))
        assert letter is not None
        letter.body = None
        session.commit()
    finally:
        session.close()

    assert client.post(f"{LETTERS}/{letter_id}/approve", headers=auth(factory)).status_code == 409


# --- ownership ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [("patch", "", {"body": "theirs"}), ("post", "/approve", None)],
)
def test_another_user_cannot_touch_a_letter(
    client: TestClient, factory: TokenFactory, method: str, suffix: str, body: Any
) -> None:
    job_id = make_job(client, factory, subject=ALICE)
    letter_id = seed_letter(client, factory, job_id, subject=ALICE)

    call = client.patch if method == "patch" else client.post
    response = call(f"{LETTERS}/{letter_id}{suffix}", headers=auth(factory, BOB), json=body)

    assert response.status_code == 404


def test_another_user_cannot_read_a_jobs_letter(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory, subject=ALICE)
    seed_letter(client, factory, job_id, subject=ALICE)

    assert (
        client.get(f"{JOBS}/{job_id}/cover-letter", headers=auth(factory, BOB)).status_code == 404
    )


def test_every_cover_letter_route_rejects_an_anonymous_caller(client: TestClient) -> None:
    job_id = uuid.uuid4()
    letter_id = uuid.uuid4()

    assert client.get(f"{JOBS}/{job_id}/cover-letter").status_code == 401
    assert client.post(f"{JOBS}/{job_id}/cover-letter", json={}).status_code == 401
    assert client.patch(f"{LETTERS}/{letter_id}", json={"body": "x"}).status_code == 401
    assert client.post(f"{LETTERS}/{letter_id}/approve").status_code == 401
