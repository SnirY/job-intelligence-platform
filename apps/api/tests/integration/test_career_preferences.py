"""Career preferences against a real database.

DEV-035. The defect being closed is not "there is no settings screen" — it is
that four documents described a thing nobody built, and a placeholder page is
indistinguishable from a page whose turn has not come.

So the tests that matter most here are not the CRUD ones. They are the ones
asserting a saved preference actually reaches a job screen, and that a
preference which cannot honestly be checked says so rather than passing quietly.
A preference stored and then ignored is worse than one never offered, because
the user believes it was taken into account.
"""

from __future__ import annotations

import uuid
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

PREFERENCES = "/api/v1/career/preferences"
JOBS = "/api/v1/jobs"
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


def preference_rows() -> int:
    with get_engine().connect() as connection:
        return int(
            connection.execute(
                sqlalchemy.text("SELECT count(*) FROM career_preferences")
            ).scalar_one()
        )


def fit(client: TestClient, factory: TokenFactory, job_id: str, dimension: str) -> dict[str, str]:
    """One dimension of the preference reading on a job's match view."""
    response = client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, ALICE))
    assert response.status_code == 200, response.text
    rows = {row["dimension"]: row for row in response.json()["data"]["preference_fit"]}
    return rows[dimension]


def make_job(client: TestClient, factory: TokenFactory, **fields: object) -> str:
    body = {
        "title": "Backend Engineer",
        "description": "We need someone to build services." * 10,
        "import_method": "MANUAL",
        **fields,
    }
    response = client.post(JOBS, json=body, headers=auth(factory, ALICE))
    assert response.status_code in {200, 201}, response.text
    return str(response.json()["data"]["id"])


# --- creation on demand -------------------------------------------------------


def test_first_read_returns_an_empty_record_rather_than_404(
    client: TestClient, factory: TokenFactory
) -> None:
    """*No constraints* and *no preferences exist* are different answers.

    Only the first is true of a user who has never opened Settings, and a 404
    would push every consumer into inventing its own default.
    """
    response = client.get(PREFERENCES, headers=auth(factory, ALICE))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["work_modes"] == []
    assert data["employment_types"] == []
    assert data["locations"] == []
    assert data["open_to_relocation"] is None
    assert data["salary_min"] is None
    assert data["excluded_role_families"] == []
    assert preference_rows() == 1


def test_repeated_reads_do_not_create_extra_rows(client: TestClient, factory: TokenFactory) -> None:
    ids = {
        client.get(PREFERENCES, headers=auth(factory, ALICE)).json()["data"]["id"] for _ in range(3)
    }

    assert len(ids) == 1
    assert preference_rows() == 1


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    assert client.get(PREFERENCES).status_code == 401
    assert preference_rows() == 0


# --- updating -----------------------------------------------------------------


def test_an_omitted_field_is_left_alone_and_an_empty_list_clears_it(
    client: TestClient, factory: TokenFactory
) -> None:
    """The distinction the sentinel scheme exists for.

    Without it there would be no way to say "I no longer care where the job is"
    as distinct from "leave my locations alone".
    """
    client.patch(
        PREFERENCES,
        json={"work_modes": ["REMOTE"], "locations": ["Tel Aviv"]},
        headers=auth(factory, ALICE),
    )

    # Mentions work_modes only. Locations must survive untouched.
    after_omission = client.patch(
        PREFERENCES, json={"work_modes": ["REMOTE", "HYBRID"]}, headers=auth(factory, ALICE)
    ).json()["data"]
    assert after_omission["locations"] == ["Tel Aviv"]

    after_clearing = client.patch(
        PREFERENCES, json={"locations": []}, headers=auth(factory, ALICE)
    ).json()["data"]
    assert after_clearing["locations"] == []
    assert after_clearing["work_modes"] == ["REMOTE", "HYBRID"]


def test_a_work_mode_the_matcher_has_never_heard_of_is_refused(
    client: TestClient, factory: TokenFactory
) -> None:
    """422 at the edge rather than a preference that silently matches nothing."""
    response = client.patch(
        PREFERENCES, json={"work_modes": ["FROM_THE_BEACH"]}, headers=auth(factory, ALICE)
    )

    assert response.status_code == 422


def test_a_repeated_value_is_stored_once(client: TestClient, factory: TokenFactory) -> None:
    """ "Remote, remote" is not a stronger preference than "remote"."""
    data = client.patch(
        PREFERENCES, json={"work_modes": ["REMOTE", "REMOTE"]}, headers=auth(factory, ALICE)
    ).json()["data"]

    assert data["work_modes"] == ["REMOTE"]


def test_another_user_cannot_see_or_change_these_preferences(
    client: TestClient, factory: TokenFactory
) -> None:
    """Required by `docs/11-engineering-standards.md` for every user-owned router.

    There is no id in the path, so this is not about guessing one: it asserts
    the row is chosen by the token and by nothing else.
    """
    client.patch(PREFERENCES, json={"locations": ["Tel Aviv"]}, headers=auth(factory, ALICE))

    bob = client.get(PREFERENCES, headers=auth(factory, BOB)).json()["data"]
    assert bob["locations"] == []

    client.patch(PREFERENCES, json={"locations": ["Berlin"]}, headers=auth(factory, BOB))
    alice = client.get(PREFERENCES, headers=auth(factory, ALICE)).json()["data"]
    assert alice["locations"] == ["Tel Aviv"]


# --- the half that DEV-035 was actually about ---------------------------------


def test_a_saved_preference_reaches_the_job_screen(
    client: TestClient, factory: TokenFactory
) -> None:
    """The test this whole slice exists for.

    Storing preferences and never reading them is the bug DEV-035 records, not
    the fix for it.
    """
    job_id = make_job(client, factory, work_mode="ONSITE")
    client.patch(PREFERENCES, json={"work_modes": ["REMOTE"]}, headers=auth(factory, ALICE))

    reading = fit(client, factory, job_id, "work_mode")
    assert reading["verdict"] == "CONFLICTS"
    assert "remote" in reading["detail"]


def test_a_preference_nobody_set_is_not_reported_as_satisfied(
    client: TestClient, factory: TokenFactory
) -> None:
    """Silence is not agreement, in the direction of the user."""
    job_id = make_job(client, factory, work_mode="ONSITE")

    assert fit(client, factory, job_id, "work_mode")["verdict"] == "NO_PREFERENCE"


def test_a_posting_that_says_nothing_is_not_reported_as_matching(
    client: TestClient, factory: TokenFactory
) -> None:
    """Silence is not agreement, in the direction of the job.

    The common case: no real posting in this account states a work mode, because
    nothing extracts one. Reporting that as a match to "remote only" would be
    the same class of quiet lie DEV-035 is about.
    """
    job_id = make_job(client, factory)
    client.patch(PREFERENCES, json={"work_modes": ["REMOTE"]}, headers=auth(factory, ALICE))

    assert fit(client, factory, job_id, "work_mode")["verdict"] == "NOT_STATED"


def test_an_unmatched_free_text_location_is_unconfirmed_rather_than_a_conflict(
    client: TestClient, factory: TokenFactory
) -> None:
    """One string failing to contain another is weak evidence.

    "Merkaz" does not contain "Tel Aviv" and may well be it. CONFLICTS is
    reserved for the three dimensions with a closed vocabulary on both sides.
    """
    job_id = make_job(client, factory, location="Caesarea, Israel")
    client.patch(PREFERENCES, json={"locations": ["Tel Aviv"]}, headers=auth(factory, ALICE))

    assert fit(client, factory, job_id, "location")["verdict"] == "UNCONFIRMED"


def test_relocation_widens_what_counts_as_a_location_match(
    client: TestClient, factory: TokenFactory
) -> None:
    job_id = make_job(client, factory, location="Berlin, Germany")
    client.patch(
        PREFERENCES,
        json={"locations": ["Tel Aviv"], "open_to_relocation": True},
        headers=auth(factory, ALICE),
    )

    reading = fit(client, factory, job_id, "location")
    assert reading["verdict"] == "MATCHES"
    assert "relocat" in reading["detail"]


def test_salary_is_reported_as_not_compared_rather_than_left_silent(
    client: TestClient, factory: TokenFactory
) -> None:
    """A dimension we decline to check has to say so.

    `jobs.salary_text` is free text — "competitive", nothing at all — and
    turning that into a number would be a guess presented as arithmetic. The
    honest failure is visible, not absent.
    """
    job_id = make_job(client, factory)
    client.patch(
        PREFERENCES,
        json={"salary_min": 30000, "salary_currency": "ils"},
        headers=auth(factory, ALICE),
    )

    reading = fit(client, factory, job_id, "salary")
    assert reading["verdict"] == "NOT_COMPARED"
    assert reading["detail"]


def test_every_dimension_is_always_returned(client: TestClient, factory: TokenFactory) -> None:
    """A short list of satisfied preferences reads as a clean bill of health.

    Omitting the ones with nothing to say would hide exactly the cases this
    slice exists to make visible.
    """
    job_id = make_job(client, factory)

    response = client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, ALICE))
    dimensions = {row["dimension"] for row in response.json()["data"]["preference_fit"]}

    assert dimensions == {"work_mode", "employment_type", "location", "role_family", "salary"}


def test_preferences_do_not_touch_the_match(client: TestClient, factory: TokenFactory) -> None:
    """Alignment is about evidence. A job in the wrong city does not fit your
    skills any less, and a score that moves when a preference changes would be
    reporting taste as measurement."""
    job_id = make_job(client, factory, work_mode="ONSITE")
    before = client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, ALICE)).json()["data"]

    client.patch(
        PREFERENCES,
        json={"work_modes": ["REMOTE"], "excluded_role_families": ["BACKEND"]},
        headers=auth(factory, ALICE),
    )
    after = client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, ALICE)).json()["data"]

    assert before["match"] == after["match"]


def test_the_reading_is_live_rather_than_frozen_at_match_time(
    client: TestClient, factory: TokenFactory
) -> None:
    """The reason this is computed on read.

    `job_matches.recommendation` is written once. Had the preference been baked
    in there, changing it tomorrow would leave every stored recommendation
    quietly stale with no path to re-derive it.
    """
    job_id = make_job(client, factory, work_mode="ONSITE")
    client.patch(PREFERENCES, json={"work_modes": ["REMOTE"]}, headers=auth(factory, ALICE))
    assert fit(client, factory, job_id, "work_mode")["verdict"] == "CONFLICTS"

    client.patch(PREFERENCES, json={"work_modes": ["ONSITE"]}, headers=auth(factory, ALICE))
    assert fit(client, factory, job_id, "work_mode")["verdict"] == "MATCHES"


def test_an_excluded_role_family_needs_an_analysis_to_be_read(
    client: TestClient, factory: TokenFactory
) -> None:
    """The one dimension with a closed vocabulary on both sides, and it lives on
    the analysis rather than the job row. Unanalysed means unknown, not clear."""
    job_id = make_job(client, factory)
    client.patch(
        PREFERENCES, json={"excluded_role_families": ["DEVOPS"]}, headers=auth(factory, ALICE)
    )

    assert fit(client, factory, job_id, "role_family")["verdict"] == "NOT_STATED"


def test_a_job_belonging_to_someone_else_is_not_readable(
    client: TestClient, factory: TokenFactory
) -> None:
    """The fit endpoint is the match endpoint, so its ownership check is the one
    that matters — reading a stranger's job to learn its location would be a
    leak wearing a new field name."""
    job_id = make_job(client, factory)

    assert client.get(f"{JOBS}/{job_id}/match", headers=auth(factory, BOB)).status_code == 404
    assert (
        client.get(f"{JOBS}/{uuid.uuid4()}/match", headers=auth(factory, ALICE)).status_code == 404
    )
