"""The application tracker end to end, against a real database.

What these protect that the unit tests cannot:

- a status never lands without its event, because they share a transaction;
- the exact resume version is pinned *and* frozen when an application is sent;
- the timeline survives, in the order things happened rather than the order
  they were entered;
- a job and its application stay separate concepts;
- another user cannot read or move any of it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from jip_api.api.dependencies import get_dispatcher
from jip_api.domain.applications.models import ApplicationEvent
from jip_api.domain.jobs.models import Job, JobProcessingStatus
from jip_api.infrastructure.auth.oidc import reset_verifier_cache
from jip_api.infrastructure.db.session import new_session, reset_engine_cache
from jip_api.infrastructure.tasks.dispatcher import reset_task_caches
from jip_config import get_settings
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
JOBS = "/api/v1/jobs"
APPS = "/api/v1/applications"
RESUMES = "/api/v1/resumes"
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


# --- helpers ------------------------------------------------------------------


def auth(factory: TokenFactory, subject: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def make_job(client: TestClient, factory: TokenFactory, subject: str = ALICE, **extra: Any) -> str:
    response = client.post(
        JOBS,
        headers=auth(factory, subject),
        json={"import_method": "MANUAL", "title": "Senior Backend Engineer", **extra},
    )
    assert response.status_code == 201, response.text
    job_id: str = response.json()["data"]["id"]
    return job_id


def track(
    client: TestClient, factory: TokenFactory, job_id: str, subject: str = ALICE, expect: int = 201
) -> dict[str, Any]:
    response = client.post(APPS, headers=auth(factory, subject), json={"job_id": job_id})
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def move(
    client: TestClient,
    factory: TokenFactory,
    application_id: str,
    status: str,
    subject: str = ALICE,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.patch(
        f"{APPS}/{application_id}/status",
        headers=auth(factory, subject),
        json={"status": status},
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def timeline(
    client: TestClient, factory: TokenFactory, application_id: str, subject: str = ALICE
) -> list[dict[str, Any]]:
    response = client.get(f"{APPS}/{application_id}/events", headers=auth(factory, subject))
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["data"]
    return events


def make_version(client: TestClient, factory: TokenFactory) -> str:
    resume = client.post(
        RESUMES, headers=auth(factory), json={"title": "Backend", "family": "BASE"}
    )
    assert resume.status_code == 201, resume.text
    version = client.post(
        f"{RESUMES}/{resume.json()['data']['id']}/versions",
        headers=auth(factory),
        json={"label": "First"},
    )
    assert version.status_code == 201, version.text
    version_id: str = version.json()["data"]["id"]
    return version_id


# --- creation -----------------------------------------------------------------


def test_tracking_a_job_starts_a_timeline(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)

    application = track(client, factory, job_id)

    assert application["status"] == "SAVED"
    events = timeline(client, factory, application["id"])
    assert [event["event_type"] for event in events] == ["CREATED"]


def test_a_job_is_not_an_application(client: TestClient, factory: TokenFactory) -> None:
    """The distinction the phase rests on. A saved job with no application is
    the normal case, and if every job produced one the funnel's first
    conversion rate would always be 100%."""
    make_job(client, factory)
    make_job(client, factory, title="Another role")

    listed = client.get(APPS, headers=auth(factory)).json()["data"]

    assert listed == []


def test_a_job_can_only_be_tracked_once(client: TestClient, factory: TokenFactory) -> None:
    """A second application would split one pursuit across two timelines, and
    the funnel would count it twice."""
    job_id = make_job(client, factory)
    track(client, factory, job_id)

    body = track(client, factory, job_id, expect=409)

    assert "already tracking" in body["error"]["message"]


def test_tracking_a_job_that_is_not_yours_is_not_found(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = make_job(client, factory, subject=BOB)

    track(client, factory, job_id, expect=404)


# --- the rule that matters most -------------------------------------------------


def test_every_status_change_creates_an_event(client: TestClient, factory: TokenFactory) -> None:
    """``docs/11-engineering-standards.md``: every status update must also
    create history. This is the assertion that keeps that true."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    move(client, factory, application["id"], "INTERESTED")
    move(client, factory, application["id"], "PREPARING")
    move(client, factory, application["id"], "APPLIED")

    events = timeline(client, factory, application["id"])
    changes = [event for event in events if event["event_type"] == "STATUS_CHANGED"]

    assert len(changes) == 3
    assert [(c["from_status"], c["to_status"]) for c in changes] == [
        ("SAVED", "INTERESTED"),
        ("INTERESTED", "PREPARING"),
        ("PREPARING", "APPLIED"),
    ]


def test_a_refused_move_writes_nothing_at_all(client: TestClient, factory: TokenFactory) -> None:
    """The other half of "one transaction": a rejected transition must not
    leave a half-written event behind."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    move(client, factory, application["id"], "APPLIED")
    move(client, factory, application["id"], "TECHNICAL_INTERVIEW")

    before = len(timeline(client, factory, application["id"]))
    move(client, factory, application["id"], "HR_SCREEN", expect=409)

    after = timeline(client, factory, application["id"])
    assert len(after) == before
    assert (
        client.get(f"{APPS}/{application['id']}", headers=auth(factory)).json()["data"]["status"]
        == "TECHNICAL_INTERVIEW"
    )


def test_a_refusal_explains_itself(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    move(client, factory, application["id"], "APPLIED")

    body = move(client, factory, application["id"], "PREPARING", expect=409)

    assert "already been sent" in body["error"]["message"]


def test_events_cannot_be_edited_through_the_api(client: TestClient, factory: TokenFactory) -> None:
    """There is deliberately no route that updates or deletes an event.

    Asserted rather than assumed: the day someone adds one, this fails.
    """
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    event_id = timeline(client, factory, application["id"])[0]["id"]

    for method in ("patch", "put", "delete"):
        response = getattr(client, method)(
            f"{APPS}/{application['id']}/events/{event_id}", headers=auth(factory)
        )
        assert response.status_code in {404, 405}, f"{method} reached something"


# --- applying -------------------------------------------------------------------


def test_applying_pins_and_freezes_the_resume_version(
    client: TestClient, factory: TokenFactory
) -> None:
    """``docs/07``: preserve the exact resume version. Freezing is what makes
    that preservation mean anything afterwards."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    version_id = make_version(client, factory)

    response = client.post(
        f"{APPS}/{application['id']}/apply",
        headers=auth(factory),
        json={"resume_version_id": version_id, "source": "LINKEDIN"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "APPLIED"
    assert data["resume_version_id"] == version_id
    assert data["source"] == "LINKEDIN"
    assert data["applied_at"] is not None

    version = client.get(f"/api/v1/resume-versions/{version_id}", headers=auth(factory)).json()[
        "data"
    ]
    assert version["status"] == "USED"
    assert version["is_editable"] is False


def test_the_pinned_version_can_no_longer_be_edited(
    client: TestClient, factory: TokenFactory
) -> None:
    """The point of the freeze, from the user's side."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    version_id = make_version(client, factory)
    client.post(
        f"{APPS}/{application['id']}/apply",
        headers=auth(factory),
        json={"resume_version_id": version_id},
    )

    refused = client.put(
        f"/api/v1/resume-versions/{version_id}/content",
        headers=auth(factory),
        json={"sections": []},
    )

    assert refused.status_code == 409, refused.text


def test_a_backdated_application_keeps_its_own_date(
    client: TestClient, factory: TokenFactory
) -> None:
    """Someone entering last month's applications needs the timeline to read
    correctly, not to be compressed into this afternoon."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    last_month = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=30)).isoformat()

    response = client.post(
        f"{APPS}/{application['id']}/apply",
        headers=auth(factory),
        json={"applied_at": last_month},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["applied_at"].startswith(last_month[:10])


def test_applying_records_both_the_move_and_the_submission(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    version_id = make_version(client, factory)

    client.post(
        f"{APPS}/{application['id']}/apply",
        headers=auth(factory),
        json={"resume_version_id": version_id},
    )

    kinds = [event["event_type"] for event in timeline(client, factory, application["id"])]
    assert "RESUME_ATTACHED" in kinds
    assert "STATUS_CHANGED" in kinds
    assert "SUBMITTED" in kinds


# --- notes and feedback ----------------------------------------------------------


def test_a_note_becomes_a_timeline_entry(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    response = client.post(
        f"{APPS}/{application['id']}/notes",
        headers=auth(factory),
        json={"text": "Recruiter said two weeks."},
    )

    assert response.status_code == 201, response.text
    summaries = [event["summary"] for event in timeline(client, factory, application["id"])]
    assert "Recruiter said two weeks." in summaries


def test_feedback_is_stored_apart_from_notes(client: TestClient, factory: TokenFactory) -> None:
    """``docs/07`` requires known feedback kept separate from system inference,
    and forbids presenting a guessed reason as fact. Nothing writes this field
    but the user."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    response = client.post(
        f"{APPS}/{application['id']}/feedback",
        headers=auth(factory),
        json={"feedback": "Went with someone who had more Kubernetes."},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["rejection_feedback"] == "Went with someone who had more Kubernetes."
    assert data["notes"] is None


# --- the board ---------------------------------------------------------------------


def test_the_list_says_which_moves_are_legal(client: TestClient, factory: TokenFactory) -> None:
    """The board builds its control from this, so the screen and the endpoint
    cannot disagree about what is possible."""
    job_id = make_job(client, factory)
    track(client, factory, job_id)

    listed = client.get(APPS, headers=auth(factory)).json()["data"]

    assert listed[0]["allowed_transitions"]
    assert "INTERESTED" in listed[0]["allowed_transitions"]
    assert "HR_SCREEN" not in listed[0]["allowed_transitions"]


def test_a_card_carries_its_job_title(client: TestClient, factory: TokenFactory) -> None:
    """One request draws the board. Fetching each job separately would be one
    round trip per card."""
    job_id = make_job(client, factory, company="Verdant")
    track(client, factory, job_id)

    listed = client.get(APPS, headers=auth(factory)).json()["data"]

    assert listed[0]["job_title"] == "Senior Backend Engineer"
    assert listed[0]["company"] == "Verdant"


def test_archived_applications_are_hidden_by_default(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)
    move(client, factory, application["id"], "WITHDRAWN")
    move(client, factory, application["id"], "ARCHIVED")

    assert client.get(APPS, headers=auth(factory)).json()["data"] == []
    assert (
        len(client.get(f"{APPS}?include_archived=true", headers=auth(factory)).json()["data"]) == 1
    )


def test_nothing_here_writes_to_the_job(client: TestClient, factory: TokenFactory) -> None:
    """``Job.status`` tracks our pipeline, not the user's progress. Merging the
    two would let the tracker rewrite the job library."""
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    move(client, factory, application["id"], "APPLIED")

    session = new_session()
    try:
        job = session.get(Job, uuid.UUID(job_id))
        assert job is not None
        # RAW is where a hand-entered job sits until it is analysed. The point
        # is that applying did not move it — the pipeline status is ours, the
        # application status is the user's, and they are unrelated.
        assert job.status is JobProcessingStatus.RAW
    finally:
        session.close()


# --- ownership ----------------------------------------------------------------------


def test_another_user_cannot_read_an_application(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    response = client.get(f"{APPS}/{application['id']}", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_another_user_cannot_move_an_application(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    move(client, factory, application["id"], "INTERESTED", subject=BOB, expect=404)


def test_another_user_cannot_read_the_timeline(client: TestClient, factory: TokenFactory) -> None:
    job_id = make_job(client, factory)
    application = track(client, factory, job_id)

    response = client.get(f"{APPS}/{application['id']}/events", headers=auth(factory, BOB))

    assert response.status_code == 404


def test_events_are_scoped_to_their_owner(client: TestClient, factory: TokenFactory) -> None:
    """Belt and braces: the rows themselves carry the owner, so a query that
    forgot to join through the application still cannot leak."""
    job_id = make_job(client, factory)
    track(client, factory, job_id)

    session = new_session()
    try:
        owners = {row.user_id for row in session.execute(select(ApplicationEvent)).scalars()}
        assert len(owners) == 1
    finally:
        session.close()
