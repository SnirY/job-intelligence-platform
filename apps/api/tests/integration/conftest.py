"""Fixtures for tests that need live PostgreSQL or Redis.

By default these tests skip when the infrastructure URLs are not configured, so
a developer without a local stack still gets a green unit-test run. CI sets
``JIP_REQUIRE_INTEGRATION=1``, which turns those skips into failures — otherwise
an infrastructure regression would show up as a silently shorter test run.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
import sqlalchemy
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.engine import URL, make_url

REQUIRE_INTEGRATION = os.environ.get("JIP_REQUIRE_INTEGRATION") == "1"

PROBE_TIMEOUT_SECONDS = 5
"""How long a healthy stack gets to answer before the run gives up on it."""


@pytest.fixture(autouse=True)
def no_live_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every integration test run with AI unconfigured.

    DEV-018. The repository root ``.env`` holds a working key, so a fixture that
    sets the database and auth variables but leaves ``JIP_AI_API_KEY`` alone
    lets any opportunistic AI call reach the live provider — slow, billed, and
    non-deterministic. ``docs/11-engineering-standards.md`` forbids live model
    calls in the normal suite outright.

    Autouse and here rather than repeated in each file, because the failure
    mode is silent: nothing about a test that quietly costs money looks wrong
    until you read the model name in an assertion diff. Tests that need a model
    inject a ``FakeLLMProvider`` directly, which this cannot affect.

    Applied before the per-file fixtures clear the settings cache, so the empty
    value is what they pick up.
    """
    monkeypatch.setenv("JIP_AI_API_KEY", "")


def _require(url: str | None, variable: str) -> str:
    if url:
        return url
    message = f"{variable} is not set; live infrastructure is unavailable."
    if REQUIRE_INTEGRATION:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """URL of a reachable PostgreSQL server.

    Reachable is checked, not assumed. This docstring claimed it for months
    while only the variable's presence was tested, and the difference is not
    academic: with the stack down, a run against a set-but-dead URL spent
    **43 minutes** timing out one connection per test before reporting five
    errors that said `ConnectionTimeout` rather than "start the stack".

    `redis_url` below has always pinged. The asymmetry was the whole defect.

    One probe, session-scoped, with a short deadline — long enough for a
    container that is still opening its port, short enough that a stack which
    is simply not running says so before anyone makes coffee. `psycopg` is used
    directly rather than through SQLAlchemy because `connect_timeout` is a
    driver argument and this needs to be the one connection that cannot hang.
    """
    url = _require(os.environ.get("JIP_TEST_DATABASE_URL"), "JIP_TEST_DATABASE_URL")

    try:
        with psycopg.connect(
            make_url(url).set(drivername="postgresql").render_as_string(hide_password=False),
            connect_timeout=PROBE_TIMEOUT_SECONDS,
        ):
            pass
    except psycopg.Error as exc:
        pytest.fail(
            f"PostgreSQL at {make_url(url).set(password=None)} did not respond "
            f"within {PROBE_TIMEOUT_SECONDS}s: {exc}\n"
            "The integration stack is not running. `docker compose up -d` in the "
            "repository root, then re-run."
        )

    return url


@pytest.fixture(scope="session")
def redis_url() -> str:
    """URL of a reachable Redis server."""
    url = _require(os.environ.get("JIP_TEST_REDIS_URL"), "JIP_TEST_REDIS_URL")

    client = Redis.from_url(url)
    try:
        client.ping()
    except RedisError as exc:
        pytest.fail(f"Redis at {url} did not respond: {exc}")
    finally:
        client.close()

    return url


@pytest.fixture
def clean_database_url(postgres_url: str) -> Iterator[str]:
    """Create an empty database, yield its URL, and drop it afterwards.

    Migration tests must start from a genuinely empty database; reusing a shared
    one would let a previous run's schema mask a broken migration.
    """
    base_url: URL = make_url(postgres_url)
    database_name = f"jip_test_{uuid.uuid4().hex[:12]}"

    admin_engine = sqlalchemy.create_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as connection:
            connection.execute(sqlalchemy.text(f'CREATE DATABASE "{database_name}"'))

        yield base_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(
                sqlalchemy.text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        admin_engine.dispose()


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[Redis]:
    """Redis client against a flushed database, cleaned up after the test."""
    client = Redis.from_url(redis_url)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()
