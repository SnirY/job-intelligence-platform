"""The reviewed-candidate mechanism, against a real database.

DEV-062, candidate 2. Two things are under test and the first matters more than
the feature: **re-resolving requirements against a catalogue that has grown.**
`f2a91c47d8e3` added thirty skills and nothing pointed the stored requirements
at them, so `HTML` sat unresolved while the skill it names was right there. On
the development data that was 21 of 44 distinct unresolved names.

The second is the queue itself — what a posting names that the catalogue still
cannot answer, and the three things a person can decide about it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
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
BASE = "/api/v1/skill-candidates"
ALICE = "user_alice"


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


@pytest.fixture
def engine(clean_database_url: str) -> Iterator[sqlalchemy.Engine]:
    created = sqlalchemy.create_engine(clean_database_url)
    yield created
    created.dispose()


def auth(factory: TokenFactory, subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory.token(subject=subject)}"}


def seed_requirements(engine: sqlalchemy.Engine, *names: str) -> None:
    """A job, an analysis, and one requirement per name.

    Built with SQL rather than through the API because **no route creates a
    requirement**. They arrive only from a model reading a posting, which is
    precisely the path this queue exists to catch — so there is nothing to call.

    The user row is created here too rather than by letting the first
    authenticated request provision it, so the seed does not depend on the
    order tests happen to hit the API in.
    """
    with engine.begin() as connection:
        user_id = connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO users (auth_provider, external_user_id, email)
                VALUES ('clerk', :sub, 'a@example.com')
                ON CONFLICT (auth_provider, external_user_id) DO UPDATE
                    SET email = EXCLUDED.email
                RETURNING id
                """
            ),
            {"sub": ALICE},
        ).scalar_one()

        job_id = connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO jobs (user_id, title, normalized_title, import_method, status)
                VALUES (:user_id, 'Engineer', 'engineer', 'MANUAL', 'ANALYZED')
                RETURNING id
                """
            ),
            {"user_id": user_id},
        ).scalar_one()

        analysis_id = connection.execute(
            sqlalchemy.text(
                """
                INSERT INTO job_analyses
                    (user_id, job_id, version, provider, model, parse_prompt_version,
                     input_hash, payload)
                VALUES (:user_id, :job_id, 1, 'test', 'test-model', 'job_parser_v1',
                        :input_hash, '{}'::jsonb)
                RETURNING id
                """
            ),
            {"user_id": user_id, "job_id": job_id, "input_hash": uuid.uuid4().hex},
        ).scalar_one()

        for order, name in enumerate(names):
            connection.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO job_requirements
                        (user_id, analysis_id, job_id, requirement_type, importance,
                         source_text, normalized_text, skill_name, source_order)
                    VALUES (:user_id, :analysis_id, :job_id, 'TECHNICAL_SKILL', 'REQUIRED',
                            :source_text, :normalized_text, :name, :order)
                    """
                ),
                {
                    "user_id": user_id,
                    "analysis_id": analysis_id,
                    "job_id": job_id,
                    "source_text": name,
                    "normalized_text": name,
                    "name": name,
                    "order": order,
                },
            )


def refresh(client: TestClient, factory: TokenFactory) -> list[dict[str, Any]]:
    response = client.post(f"{BASE}/refresh", headers=auth(factory, ALICE))
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["data"]
    return rows


def unresolved_count(engine: sqlalchemy.Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                sqlalchemy.text(
                    "SELECT count(*) FROM job_requirements "
                    "WHERE skill_id IS NULL AND skill_name IS NOT NULL"
                )
            ).scalar_one()
        )


# --- re-resolving against a catalogue that grew -------------------------------


def test_a_name_the_catalogue_already_holds_never_reaches_the_queue(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The defect that made this worth building.

    `Python` is seeded by `b71c4a90d2e5`. A requirement naming it and stored
    with a null `skill_id` is not an unknown technology — it is a resolution
    nobody re-ran.
    """
    seed_requirements(engine, "Python")
    assert unresolved_count(engine) == 1

    rows = refresh(client, factory)

    assert rows == []
    assert unresolved_count(engine) == 0


def test_a_composite_the_catalogue_fully_knows_is_not_a_gap(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """`Python/Java` is not a missing catalogue entry.

    Both halves are seeded. What the requirement cannot do is point at two of
    them, because `skill_id` is one column — the open half of DEV-055, and a
    schema problem rather than a vocabulary one.

    Queuing it anyway asks a reviewer to decide something already decided, and
    both available answers are wrong: add a `Python/Java` row to a catalogue
    that has both, or reject a name that is two real technologies. Eight of the
    development queue's entries were this shape.
    """
    seed_requirements(engine, "Python/Java")

    rows = refresh(client, factory)

    assert rows == []


def test_a_half_known_composite_is_still_a_gap(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The other side of the same rule, and the reason it checks every part.

    A composite where one half is catalogued and the other is not is a genuine
    absence wearing a slash. It stays in the queue, where somebody can add the
    half that is missing.
    """
    seed_requirements(engine, "Python/Kryptonite")

    rows = refresh(client, factory)

    assert [row["display_name"] for row in rows] == ["Python/Kryptonite"]


def test_an_alias_resolves_too(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """Canonical names first, aliases second — the order `resolve_known_skills`
    uses, and the one DEV-067 showed matters."""
    seed_requirements(engine, "React.js")

    assert refresh(client, factory) == []
    assert unresolved_count(engine) == 0


def test_a_posting_qualifier_is_stripped_before_resolving(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    seed_requirements(engine, "Strong Python experience")

    assert refresh(client, factory) == []
    assert unresolved_count(engine) == 0


# --- the queue ----------------------------------------------------------------


def test_an_unknown_name_is_queued_with_its_count(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    seed_requirements(engine, "Quantum Annealing", "Quantum Annealing", "Widgetron")

    rows = refresh(client, factory)

    assert [(row["display_name"], row["occurrences"]) for row in rows] == [
        ("Quantum Annealing", 2),
        ("Widgetron", 1),
    ]
    assert all(row["status"] == "PENDING" for row in rows)


def test_the_queue_is_ordered_by_use_not_by_name(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """DEV-040 is why. A list sorted alphabetically buries what matters under
    whatever begins with A."""
    seed_requirements(engine, "Aardvarkium", "Zebraflow", "Zebraflow", "Zebraflow")

    rows = refresh(client, factory)

    assert [row["display_name"] for row in rows] == ["Zebraflow", "Aardvarkium"]


def test_refreshing_twice_does_not_duplicate(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    seed_requirements(engine, "Widgetron")

    refresh(client, factory)
    rows = refresh(client, factory)

    assert len(rows) == 1


# --- the three decisions ------------------------------------------------------


def test_accepting_as_a_new_skill_resolves_the_requirement(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The decision has to reach the stored requirements, not only the
    catalogue. Otherwise the reviewer has fixed the future and left every
    posting already on file reading the old answer."""
    seed_requirements(engine, "Widgetron", "Widgetron")
    candidate = refresh(client, factory)[0]

    response = client.post(
        f"{BASE}/{candidate['id']}/accept-new",
        headers=auth(factory, ALICE),
        json={"category": "FRAMEWORK"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "ACCEPTED"
    assert response.json()["data"]["resolved_skill_id"] is not None
    assert unresolved_count(engine) == 0
    assert refresh(client, factory) == []


def test_a_corrected_spelling_still_resolves_the_posting_wording(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The reviewer fixes the name; the posting's own wording survives as an
    alias, or the requirement that raised the candidate would still not
    resolve."""
    seed_requirements(engine, "widgetron framework")
    candidate = refresh(client, factory)[0]

    response = client.post(
        f"{BASE}/{candidate['id']}/accept-new",
        headers=auth(factory, ALICE),
        json={"category": "FRAMEWORK", "canonical_name": "Widgetron"},
    )

    assert response.status_code == 201, response.text
    assert unresolved_count(engine) == 0


def test_accepting_as_an_alias_maps_onto_the_existing_skill(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    seed_requirements(engine, "Pythonic scripting")
    candidate = refresh(client, factory)[0]

    with engine.connect() as connection:
        python_id = connection.execute(
            sqlalchemy.text("SELECT id FROM skills WHERE normalized_name = 'python'")
        ).scalar_one()

    response = client.post(
        f"{BASE}/{candidate['id']}/accept-alias",
        headers=auth(factory, ALICE),
        json={"skill_id": str(python_id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["resolved_skill_id"] == str(python_id)
    assert unresolved_count(engine) == 0


def test_a_rejected_name_stays_rejected_across_refreshes(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The reason rejections are stored at all.

    "General-purpose programming language" appears six times in the development
    data and names no technology. Without a remembered decision the queue would
    propose it again every refresh, forever.
    """
    seed_requirements(engine, "General-purpose programming language")
    candidate = refresh(client, factory)[0]

    response = client.post(
        f"{BASE}/{candidate['id']}/reject",
        headers=auth(factory, ALICE),
        json={"note": "Not a technology."},
    )

    assert response.status_code == 200, response.text
    assert refresh(client, factory) == []
    assert unresolved_count(engine) == 1, "a rejection must not resolve the requirement"


def test_a_rejected_name_keeps_counting(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """How often a rejected term keeps appearing is the evidence for revisiting
    the rejection."""
    seed_requirements(engine, "Widgetron")
    candidate = refresh(client, factory)[0]
    client.post(f"{BASE}/{candidate['id']}/reject", headers=auth(factory, ALICE), json={})

    seed_requirements(engine, "Widgetron", "Widgetron")
    refresh(client, factory)

    rejected = client.get(f"{BASE}?status_filter=REJECTED", headers=auth(factory, ALICE)).json()[
        "data"
    ]
    assert [row["occurrences"] for row in rejected] == [3]


def test_a_second_decision_is_refused(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """409, not a silent overwrite. The catalogue is shared, and one reviewer's
    conclusion quietly replacing another's is how it acquires changes nobody
    remembers making."""
    seed_requirements(engine, "Widgetron")
    candidate = refresh(client, factory)[0]
    client.post(f"{BASE}/{candidate['id']}/reject", headers=auth(factory, ALICE), json={})

    again = client.post(
        f"{BASE}/{candidate['id']}/accept-new",
        headers=auth(factory, ALICE),
        json={"category": "TOOL"},
    )

    assert again.status_code == 409, again.text


def test_accepting_a_name_that_became_a_skill_meanwhile_is_not_an_error(
    client: TestClient, factory: TokenFactory, engine: sqlalchemy.Engine
) -> None:
    """The reviewer's intent is clear and the outcome already exists. Refusing
    would be pedantry that leaves the queue entry stuck."""
    seed_requirements(engine, "Widgetron")
    candidate = refresh(client, factory)[0]

    response = client.post(
        f"{BASE}/{candidate['id']}/accept-new",
        headers=auth(factory, ALICE),
        json={"category": "TOOL", "canonical_name": "Python"},
    )

    assert response.status_code == 201, response.text
    assert unresolved_count(engine) == 0


# --- access -------------------------------------------------------------------


def test_an_unknown_candidate_is_a_404(client: TestClient, factory: TokenFactory) -> None:
    response = client.post(f"{BASE}/{uuid.uuid4()}/reject", headers=auth(factory, ALICE), json={})

    assert response.status_code == 404


def test_unauthenticated_access_is_refused(client: TestClient) -> None:
    assert client.get(BASE).status_code == 401
    assert client.post(f"{BASE}/refresh").status_code == 401
    assert client.post(f"{BASE}/{uuid.uuid4()}/reject", json={}).status_code == 401
