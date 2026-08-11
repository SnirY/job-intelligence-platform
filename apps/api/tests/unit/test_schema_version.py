"""The start-up schema gate, and the constant it depends on.

DEV-051. The first test here is the one that matters: it is what stops
``EXPECTED_SCHEMA_REVISION`` from becoming the next thing that quietly disagrees
with reality.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from jip_api.infrastructure.db.schema_version import (
    EXPECTED_SCHEMA_REVISION,
    SchemaVersionMismatch,
    read_database_revision,
    verify_schema_version,
)

API_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    """The project's Alembic config, resolved absolutely.

    `alembic.ini` sets ``script_location = migrations``, which Alembic resolves
    against the working directory rather than the file. That works for the
    `alembic` CLI, which is always run from `apps/api`, and not for pytest,
    which runs from the repository root.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return config


def test_the_expected_revision_is_the_real_head() -> None:
    """The constant against the migration tree it stands in for.

    ``EXPECTED_SCHEMA_REVISION`` is hand-maintained because the migration
    scripts are not in the wheel and a deployed process cannot read them. That
    is only safe while something checks it, and this is that something: add a
    migration without bumping the constant and this fails, in CI, on the same
    pull request.
    """
    script = ScriptDirectory.from_config(_alembic_config())

    assert script.get_heads() == [EXPECTED_SCHEMA_REVISION], (
        "EXPECTED_SCHEMA_REVISION in schema_version.py no longer matches the "
        "migrations. Update it in the commit that adds the migration."
    )


def test_a_single_head_is_still_true() -> None:
    """Two heads mean two branches of history and no single answer to "what
    revision is this code for". The gate assumes one; this asserts it."""
    script = ScriptDirectory.from_config(_alembic_config())

    assert len(script.get_heads()) == 1


# --- the gate itself, against a real (SQLite) database -------------------------
#
# SQLite rather than PostgreSQL: the gate reads one column from one table and
# asks the dialect whether that table exists. Neither is Postgres-specific, and
# a unit test that needs a container is one people stop running.


@pytest.fixture
def engine() -> Engine:
    return create_engine("sqlite://")


def _stamp(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("create table alembic_version (version_num varchar(32))"))
        connection.execute(text("insert into alembic_version values (:r)"), {"r": revision})


def test_a_matching_database_starts(engine: Engine) -> None:
    _stamp(engine, EXPECTED_SCHEMA_REVISION)

    verify_schema_version(engine)  # does not raise


def test_a_database_ahead_of_this_build_is_refused(engine: Engine) -> None:
    """DEV-051 exactly: the worker's code predates the database.

    This is the one that ran for thirteen days. It is also the harmless-looking
    direction — an extra table the old code never queries — which is why it
    survived so long.
    """
    _stamp(engine, "a71f3d0c5e84")

    with pytest.raises(SchemaVersionMismatch) as caught:
        verify_schema_version(engine, expected="e8b3f2a91c47")

    assert "a71f3d0c5e84" in str(caught.value)
    assert "e8b3f2a91c47" in str(caught.value)


def test_a_database_behind_this_build_is_refused(engine: Engine) -> None:
    """The deploy-ordering direction: new code, migrations not yet applied."""
    _stamp(engine, "e8b3f2a91c47")

    with pytest.raises(SchemaVersionMismatch):
        verify_schema_version(engine, expected="a71f3d0c5e84")


def test_the_message_names_both_causes_and_what_to_do(engine: Engine) -> None:
    """The gate's whole value is the message. A refusal that does not say which
    of the two happened has moved the confusion rather than removed it."""
    _stamp(engine, "a71f3d0c5e84")

    with pytest.raises(SchemaVersionMismatch) as caught:
        verify_schema_version(engine, expected="e8b3f2a91c47")

    message = str(caught.value)
    assert "docker compose build" in message
    assert "alembic upgrade head" in message


def test_a_database_that_has_never_migrated_is_refused(engine: Engine) -> None:
    """No `alembic_version` table at all. Starting here means the first job to
    touch a missing table fails halfway through the work instead of before it."""
    with pytest.raises(SchemaVersionMismatch, match="no schema"):
        verify_schema_version(engine)


def test_an_unmigrated_database_reports_no_revision(engine: Engine) -> None:
    assert read_database_revision(engine) is None


def test_an_empty_version_table_reports_no_revision(engine: Engine) -> None:
    """Alembic leaves the table in place after a full downgrade. A row-less
    table is not a revision, and reading `None` here is what turns that into
    the "never migrated" message rather than an IndexError."""
    with engine.begin() as connection:
        connection.execute(text("create table alembic_version (version_num varchar(32))"))

    assert read_database_revision(engine) is None
