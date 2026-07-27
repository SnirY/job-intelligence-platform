"""The job workspace end to end, against a real database.

Create, list, read, source, update, archive — with the real migrations, real
ownership scoping, and a recording dispatcher standing in for the queue.

The properties worth protecting here, in order:

- the preserved original is never overwritten by an edit;
- a possible duplicate is reported with enough detail to act on, not dropped;
- a failed URL import leaves a job the user can still finish by hand;
- another user's jobs are unreachable through every route.
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
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks
from tests.integration.resume_fixtures import RecordingDispatcher

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/v1/jobs"
ALICE = "user_alice"
BOB = "user_bob"

DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to work on our shipment platform. "
    "You will build REST services in Python and FastAPI, own the PostgreSQL "
    "schema behind carrier reconciliation, and help move the remaining Flask "
    "endpoints across. We work hybrid from Lisbon, two days in the office."
) * 2


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


def create(
    client: TestClient,
    factory: TokenFactory,
    body: dict[str, Any],
    subject: str = ALICE,
    expect: int = 201,
) -> dict[str, Any]:
    response = client.post(BASE, headers=auth(factory, subject), json=body)
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload["data"] if expect < 400 else payload


def paste(title: str = "Senior Backend Engineer", **overrides: Any) -> dict[str, Any]:
    return {
        "import_method": "PASTED_DESCRIPTION",
        "title": title,
        "description": DESCRIPTION,
        **overrides,
    }


# --- creation -----------------------------------------------------------------


def test_creates_a_job_from_a_pasted_description(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, paste(company="Verdant Logistics"))

    assert job["title"] == "Senior Backend Engineer"
    assert job["company"] == "Verdant Logistics"
    assert job["import_method"] == "PASTED_DESCRIPTION"
    assert job["status"] == "RAW"


def test_creates_a_manual_job_without_a_description(
    client: TestClient, factory: TokenFactory
) -> None:
    """A job heard about in conversation still belongs in the list."""
    job = create(
        client,
        factory,
        {
            "import_method": "MANUAL",
            "title": "Platform Engineer",
            "company": "Tidewater",
            "work_mode": "REMOTE",
            "employment_type": "FULL_TIME",
            "seniority": "SENIOR",
        },
    )

    assert job["description"] is None
    assert job["work_mode"] == "REMOTE"
    assert job["seniority"] == "SENIOR"


def test_a_pasted_job_requires_a_description(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(
        BASE,
        headers=auth(factory),
        json={"import_method": "PASTED_DESCRIPTION", "title": "Engineer"},
    )

    assert response.status_code == 422


def test_a_manual_job_requires_a_title(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(BASE, headers=auth(factory), json={"import_method": "MANUAL"})

    assert response.status_code == 422


def test_a_url_import_requires_a_url(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(BASE, headers=auth(factory), json={"import_method": "URL"})

    assert response.status_code == 422


def test_a_url_import_is_queued_and_starts_fetching(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    """202-style behaviour on a 201: the job exists immediately, the fetch runs
    in the background. A remote request must not hold the response open."""
    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/1"},
    )

    assert job["status"] == "FETCHING"
    assert job["source_url"] == "https://jobs.example.com/role/1"
    assert dispatcher.calls == [("jip_worker.tasks.jobs.run_job_url_import", (job["id"],))]


def test_a_queue_outage_keeps_the_job(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    """GOAL.md: a failure must not destroy user work. The job and its link
    survive so the user can retry or paste."""
    dispatcher.fail = True

    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/2"},
    )

    fetched = client.get(f"{BASE}/{job['id']}", headers=auth(factory)).json()["data"]
    assert fetched["status"] == "FAILED"
    assert fetched["source_url"] == "https://jobs.example.com/role/2"
    assert "try again" in (fetched["fetch_error"] or "").lower()


# --- source preservation ------------------------------------------------------


def test_the_original_description_is_preserved(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, paste())

    source = client.get(f"{BASE}/{job['id']}/source", headers=auth(factory)).json()["data"]

    assert source["original_description"] == DESCRIPTION
    assert source["import_method"] == "PASTED_DESCRIPTION"
    assert len(source["imports"]) == 1
    assert source["imports"][0]["imported_at"] is not None


def test_editing_the_description_leaves_the_original_alone(
    client: TestClient, factory: TokenFactory
) -> None:
    """The rule this whole two-table split exists to guarantee."""
    job = create(client, factory, paste())

    client.patch(
        f"{BASE}/{job['id']}", headers=auth(factory), json={"description": "My own summary."}
    )

    current = client.get(f"{BASE}/{job['id']}", headers=auth(factory)).json()["data"]
    source = client.get(f"{BASE}/{job['id']}/source", headers=auth(factory)).json()["data"]

    assert current["description"] == "My own summary."
    assert source["original_description"] == DESCRIPTION
    assert source["raw_content"] == DESCRIPTION


def test_the_import_record_keeps_the_method_and_timestamp(
    client: TestClient, factory: TokenFactory
) -> None:
    job = create(
        client,
        factory,
        {"import_method": "MANUAL", "title": "Platform Engineer"},
    )

    source = client.get(f"{BASE}/{job['id']}/source", headers=auth(factory)).json()["data"]

    assert source["imports"][0]["import_method"] == "MANUAL"
    assert source["imports"][0]["imported_at"] is not None


# --- duplicates ---------------------------------------------------------------


def test_the_same_url_is_reported_as_a_duplicate(client: TestClient, factory: TokenFactory) -> None:
    first = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/7"},
    )

    conflict = create(
        client,
        factory,
        # A tracking parameter and a trailing slash: the same posting.
        {
            "import_method": "URL",
            "source_url": "https://jobs.example.com/role/7/?utm_source=newsletter",
        },
        expect=409,
    )

    assert conflict["error"]["code"] == "CONFLICT"
    assert conflict["error"]["details"]["existing_job_id"] == first["id"]
    assert conflict["error"]["details"]["reason"] == "SAME_URL"


def test_the_same_description_is_reported_as_a_duplicate(
    client: TestClient, factory: TokenFactory
) -> None:
    """The same posting reached through two different links."""
    first = create(client, factory, paste())

    conflict = create(client, factory, paste(title="Backend Engineer"), expect=409)

    assert conflict["error"]["details"]["existing_job_id"] == first["id"]
    assert conflict["error"]["details"]["reason"] == "SAME_CONTENT"


def test_the_conflict_names_the_existing_job(client: TestClient, factory: TokenFactory) -> None:
    """A bare 409 would leave the user unable to find the job they supposedly
    already have."""
    create(client, factory, paste(title="Senior Backend Engineer"))

    conflict = create(client, factory, paste(title="Something else"), expect=409)

    assert conflict["error"]["details"]["existing_title"] == "Senior Backend Engineer"


def test_a_duplicate_is_not_silently_discarded(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, paste())
    create(client, factory, paste(title="Backend Engineer"), expect=409)

    listed = client.get(BASE, headers=auth(factory)).json()

    assert listed["meta"]["total"] == 1, "the refused submission must not have been saved"


def test_create_anyway_is_honoured(client: TestClient, factory: TokenFactory) -> None:
    """The explicit override. Two genuinely different openings can share a
    description, and the user is the one who knows."""
    create(client, factory, paste())

    second = create(client, factory, paste(title="Backend Engineer", allow_duplicate=True))

    assert second["title"] == "Backend Engineer"
    assert client.get(BASE, headers=auth(factory)).json()["meta"]["total"] == 2


def test_another_users_job_is_not_a_duplicate(client: TestClient, factory: TokenFactory) -> None:
    """Duplicate detection is per user. Bob's list must not leak through a 409
    telling Alice a job she cannot see already exists."""
    create(client, factory, paste(), subject=BOB)

    job = create(client, factory, paste(), subject=ALICE)

    assert job["title"] == "Senior Backend Engineer"


def test_a_short_description_is_not_a_duplicate_signal(
    client: TestClient, factory: TokenFactory
) -> None:
    """Two jobs whose descriptions are both "TBC" are not the same job."""
    create(client, factory, {"import_method": "MANUAL", "title": "One", "description": "TBC"})
    second = create(
        client, factory, {"import_method": "MANUAL", "title": "Two", "description": "TBC"}
    )

    assert second["title"] == "Two"


# --- listing ------------------------------------------------------------------


def seed(client: TestClient, factory: TokenFactory, count: int = 3) -> list[dict[str, Any]]:
    return [
        create(
            client,
            factory,
            {
                "import_method": "MANUAL",
                "title": f"Engineer {index}",
                "company": "Alpha" if index % 2 == 0 else "Beta",
                "work_mode": "REMOTE" if index % 2 == 0 else "ONSITE",
            },
        )
        for index in range(count)
    ]


def test_the_list_starts_empty(client: TestClient, factory: TokenFactory) -> None:
    listed = client.get(BASE, headers=auth(factory)).json()

    assert listed["data"] == []
    assert listed["meta"] == {"page": 1, "page_size": 20, "total": 0, "total_pages": 0}


def test_the_list_returns_created_jobs(client: TestClient, factory: TokenFactory) -> None:
    seed(client, factory, 3)

    listed = client.get(BASE, headers=auth(factory)).json()

    assert listed["meta"]["total"] == 3
    assert len(listed["data"]) == 3


def test_the_list_omits_the_description(client: TestClient, factory: TokenFactory) -> None:
    """Fifty jobs would otherwise ship a megabyte of text nothing displays."""
    create(client, factory, paste())

    row = client.get(BASE, headers=auth(factory)).json()["data"][0]

    assert "description" not in row
    assert row["has_description"] is True


def test_search_matches_title_company_and_description(
    client: TestClient, factory: TokenFactory
) -> None:
    create(client, factory, paste(title="Senior Backend Engineer", company="Verdant"))
    create(client, factory, {"import_method": "MANUAL", "title": "Designer"})

    for term in ("Backend", "Verdant", "shipment platform"):
        listed = client.get(BASE, headers=auth(factory), params={"search": term}).json()
        assert listed["meta"]["total"] == 1, f"search for {term!r}"


def test_search_wildcards_are_escaped(client: TestClient, factory: TokenFactory) -> None:
    """Without escaping, a search for "%" matches everything and reads as a
    broken search rather than a clever one."""
    seed(client, factory, 3)

    listed = client.get(BASE, headers=auth(factory), params={"search": "%"}).json()

    assert listed["meta"]["total"] == 0


@pytest.mark.parametrize(
    ("param", "value", "expected"),
    [("company", "Alpha", 2), ("work_mode", "REMOTE", 2), ("work_mode", "ONSITE", 2)],
)
def test_filters_narrow_the_list(
    client: TestClient, factory: TokenFactory, param: str, value: str, expected: int
) -> None:
    seed(client, factory, 4)

    listed = client.get(BASE, headers=auth(factory), params={param: value}).json()

    assert listed["meta"]["total"] == expected


def test_sorting_by_title(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, {"import_method": "MANUAL", "title": "Zebra Engineer"})
    create(client, factory, {"import_method": "MANUAL", "title": "Alpha Engineer"})

    listed = client.get(BASE, headers=auth(factory), params={"sort": "TITLE"}).json()

    assert [row["title"] for row in listed["data"]] == ["Alpha Engineer", "Zebra Engineer"]


def test_sorting_newest_first_by_default(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, {"import_method": "MANUAL", "title": "First"})
    create(client, factory, {"import_method": "MANUAL", "title": "Second"})

    listed = client.get(BASE, headers=auth(factory)).json()

    assert listed["data"][0]["title"] == "Second"


def test_pagination_splits_the_results(client: TestClient, factory: TokenFactory) -> None:
    seed(client, factory, 5)

    first = client.get(BASE, headers=auth(factory), params={"page_size": 2}).json()
    second = client.get(BASE, headers=auth(factory), params={"page_size": 2, "page": 2}).json()

    assert first["meta"] == {"page": 1, "page_size": 2, "total": 5, "total_pages": 3}
    assert len(first["data"]) == 2
    assert len(second["data"]) == 2
    assert {row["id"] for row in first["data"]}.isdisjoint({row["id"] for row in second["data"]})


def test_the_count_respects_the_filters(client: TestClient, factory: TokenFactory) -> None:
    """Counting an unfiltered set would give a pager promising results the
    filtered query cannot show."""
    seed(client, factory, 4)

    listed = client.get(
        BASE, headers=auth(factory), params={"company": "Alpha", "page_size": 1}
    ).json()

    assert listed["meta"]["total"] == 2
    assert listed["meta"]["total_pages"] == 2


def test_page_size_is_capped(client: TestClient, factory: TokenFactory) -> None:
    response = client.get(BASE, headers=auth(factory), params={"page_size": 5000})

    assert response.status_code == 422


def test_companies_are_offered_for_the_filter(client: TestClient, factory: TokenFactory) -> None:
    seed(client, factory, 4)

    companies = client.get(f"{BASE}/companies", headers=auth(factory)).json()["data"]

    assert companies == ["Alpha", "Beta"]


# --- lifecycle ----------------------------------------------------------------


def test_a_job_can_be_updated(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    updated = client.patch(
        f"{BASE}/{job['id']}",
        headers=auth(factory),
        json={"company": "Verdant", "notes": "Referred by Sam."},
    ).json()["data"]

    assert updated["company"] == "Verdant"
    assert updated["notes"] == "Referred by Sam."
    assert updated["title"] == "Engineer", "an omitted field must be left alone"


def test_archiving_removes_a_job_from_the_active_list(
    client: TestClient, factory: TokenFactory
) -> None:
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    client.post(f"{BASE}/{job['id']}/archive", headers=auth(factory))

    assert client.get(BASE, headers=auth(factory)).json()["meta"]["total"] == 0
    archived = client.get(BASE, headers=auth(factory), params={"archived": "ARCHIVED"}).json()
    assert archived["meta"]["total"] == 1


def test_archiving_is_not_deleting(client: TestClient, factory: TokenFactory) -> None:
    """docs/11-engineering-standards.md forbids silently dropping user history."""
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    client.post(f"{BASE}/{job['id']}/archive", headers=auth(factory))

    fetched = client.get(f"{BASE}/{job['id']}", headers=auth(factory))
    assert fetched.status_code == 200
    assert fetched.json()["data"]["archived_at"] is not None


def test_archiving_twice_keeps_the_first_timestamp(
    client: TestClient, factory: TokenFactory
) -> None:
    """That timestamp is when the decision was actually made."""
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    first = client.post(f"{BASE}/{job['id']}/archive", headers=auth(factory)).json()["data"]
    second = client.post(f"{BASE}/{job['id']}/archive", headers=auth(factory)).json()["data"]

    assert first["archived_at"] == second["archived_at"]


def test_timestamps_are_serialised_as_utc(client: TestClient, factory: TokenFactory) -> None:
    """docs/10-api-contracts.md: ISO 8601 UTC.

    A `timestamptz` reloaded from PostgreSQL arrives in the *server's* local
    zone unless the connection is pinned to UTC, so the same instant would be
    sent as "…04:44:35Z" fresh and "…07:44:35+03:00" once reloaded. Both are
    correct instants, which is exactly what makes it easy to miss.
    """
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    reloaded = client.get(f"{BASE}/{job['id']}", headers=auth(factory)).json()["data"]

    assert reloaded["created_at"].endswith("Z")
    assert reloaded["created_at"] == job["created_at"]


def test_a_job_can_be_unarchived(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})
    client.post(f"{BASE}/{job['id']}/archive", headers=auth(factory))

    client.post(f"{BASE}/{job['id']}/unarchive", headers=auth(factory))

    assert client.get(BASE, headers=auth(factory)).json()["meta"]["total"] == 1


def test_the_all_filter_shows_both(client: TestClient, factory: TokenFactory) -> None:
    jobs = seed(client, factory, 2)
    client.post(f"{BASE}/{jobs[0]['id']}/archive", headers=auth(factory))

    listed = client.get(BASE, headers=auth(factory), params={"archived": "ALL"}).json()

    assert listed["meta"]["total"] == 2


def test_a_job_can_be_deleted(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, {"import_method": "MANUAL", "title": "Engineer"})

    assert client.delete(f"{BASE}/{job['id']}", headers=auth(factory)).status_code == 204
    assert client.get(f"{BASE}/{job['id']}", headers=auth(factory)).status_code == 404


def test_jobs_persist_across_requests(client: TestClient, factory: TokenFactory) -> None:
    """The plainest completion criterion: a refresh still shows the job."""
    job = create(client, factory, paste())

    again = client.get(f"{BASE}/{job['id']}", headers=auth(factory)).json()["data"]

    assert again["id"] == job["id"]
    assert again["description"] == DESCRIPTION


# --- the manual fallback ------------------------------------------------------


def test_a_failed_import_can_be_finished_by_hand(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    """The documented fallback. The job and its link survived the failure."""
    dispatcher.fail = True
    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/9"},
    )

    filled = client.post(
        f"{BASE}/{job['id']}/description",
        headers=auth(factory),
        json={"description": DESCRIPTION},
    ).json()["data"]

    assert filled["status"] == "RAW"
    assert filled["fetch_error"] is None
    assert filled["description"] == DESCRIPTION
    assert filled["source_url"] == "https://jobs.example.com/role/9"


def test_a_hand_supplied_description_becomes_the_original(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    """For a failed fetch there was never an original, so what the user pastes
    now *is* the source."""
    dispatcher.fail = True
    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/10"},
    )

    client.post(
        f"{BASE}/{job['id']}/description",
        headers=auth(factory),
        json={"description": DESCRIPTION},
    )

    source = client.get(f"{BASE}/{job['id']}/source", headers=auth(factory)).json()["data"]
    assert source["original_description"] == DESCRIPTION


def test_editing_a_failed_job_clears_the_failure(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    dispatcher.fail = True
    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/11"},
    )

    updated = client.patch(
        f"{BASE}/{job['id']}", headers=auth(factory), json={"description": DESCRIPTION}
    ).json()["data"]

    assert updated["status"] == "RAW"
    assert updated["fetch_error"] is None


def test_a_failed_import_can_be_retried(
    client: TestClient, factory: TokenFactory, dispatcher: RecordingDispatcher
) -> None:
    dispatcher.fail = True
    job = create(
        client,
        factory,
        {"import_method": "URL", "source_url": "https://jobs.example.com/role/12"},
    )
    dispatcher.fail = False

    retried = client.post(f"{BASE}/{job['id']}/retry-import", headers=auth(factory))

    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "FETCHING"
    assert len(dispatcher.calls) == 1


def test_retrying_a_job_with_no_link_is_refused(client: TestClient, factory: TokenFactory) -> None:
    job = create(client, factory, paste())

    assert client.post(f"{BASE}/{job['id']}/retry-import", headers=auth(factory)).status_code == 409


# --- ownership ----------------------------------------------------------------


def test_the_list_is_scoped_to_the_caller(client: TestClient, factory: TokenFactory) -> None:
    create(client, factory, paste(), subject=ALICE)

    assert client.get(BASE, headers=auth(factory, ALICE)).json()["meta"]["total"] == 1
    assert client.get(BASE, headers=auth(factory, BOB)).json()["meta"]["total"] == 0


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("get", ""),
        ("get", "/source"),
        ("patch", ""),
        ("post", "/archive"),
        ("post", "/unarchive"),
        ("post", "/description"),
        ("post", "/retry-import"),
        ("delete", ""),
    ],
)
def test_another_user_cannot_reach_the_job(
    client: TestClient, factory: TokenFactory, method: str, suffix: str
) -> None:
    """docs/10-api-contracts.md: every user-owned query enforces ownership, and
    the answer is identical whether the job is missing or simply not theirs."""
    job = create(client, factory, paste(), subject=ALICE)
    url = f"{BASE}/{job['id']}{suffix}"

    # Only the body-carrying verbs get one; TestClient.get/delete refuse a
    # `json` keyword outright.
    kwargs: dict[str, Any] = {"headers": auth(factory, BOB)}
    if suffix == "/description":
        kwargs["json"] = {"description": DESCRIPTION}
    elif method == "patch":
        kwargs["json"] = {"title": "Hijacked"}

    response = getattr(client, method)(url, **kwargs)

    assert response.status_code == 404


def test_a_missing_job_answers_the_same_as_a_forbidden_one(
    client: TestClient, factory: TokenFactory
) -> None:
    """Distinguishing them would let a caller enumerate what others own."""
    missing = client.get(f"{BASE}/{uuid.uuid4()}", headers=auth(factory))

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, json=paste()).status_code == 401
