"""Refusing to run against a schema this code was not built for.

DEV-051. A worker container built from a thirteen-day-old image ran for
thirteen days beside a database that had moved on without it, taking real jobs
off the same queue as an up-to-date worker. Nothing anywhere said so. The
mismatch was found by accident, and which jobs ran on which code is not
recoverable.

The defect was never the stale image — images go stale, that is what images do.
The defect was that a process could disagree with its own database about what
the schema is, and start anyway.

**The revision is a constant here, not read from the migration scripts.** Those
are not in the wheel — `apps/api/pyproject.toml` packages `src/jip_api` and
nothing else — so at runtime, in a container, the only reliable copy of "what
this code expects" is one compiled into the code. `test_schema_version.py` reads
the real migration tree and fails if this constant drifts from it, which is what
makes a hand-maintained value safe: it cannot be wrong for longer than one CI
run.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

EXPECTED_SCHEMA_REVISION = "f2a91c47d8e3"
"""The Alembic head this code is written against.

Update it in the same commit as the migration that moves the head.
`test_the_expected_revision_is_the_real_head` fails until you do.
"""


class SchemaVersionMismatch(RuntimeError):
    """The database is not at the revision this process was built for."""


def read_database_revision(engine: Engine) -> str | None:
    """The revision the database reports, or ``None`` if it has never migrated.

    ``None`` covers both an empty database and one whose `alembic_version` table
    does not exist. Neither is a state a worker should start in: the first job
    to touch a missing table fails in the middle of the work rather than before
    it.
    """
    with engine.connect() as connection:
        if not connection.dialect.has_table(connection, "alembic_version"):
            return None
        row = connection.execute(text("select version_num from alembic_version")).fetchone()
    return str(row[0]) if row else None


def verify_schema_version(engine: Engine, *, expected: str = EXPECTED_SCHEMA_REVISION) -> None:
    """Raise :class:`SchemaVersionMismatch` unless the database agrees.

    Called at start-up, before any queue is consumed, so a mismatch costs
    nothing. Called mid-job it would abandon work halfway, which is the failure
    mode `GOAL.md` spends most of its words on.
    """
    actual = read_database_revision(engine)
    if actual == expected:
        logger.info("Schema version confirmed", extra={"revision": actual})
        return

    raise SchemaVersionMismatch(_explain(expected=expected, actual=actual))


def _explain(*, expected: str, actual: str | None) -> str:
    """The message someone reads at 2am, so it says what to do rather than what
    is wrong.

    Both causes are named because this cannot tell them apart. Distinguishing
    them needs the migration scripts, which are exactly what a deployed process
    does not have — and the person reading knows in one glance which of the two
    they just did.
    """
    if actual is None:
        return (
            "Refusing to start: this database has no schema. "
            f"This build expects Alembic revision {expected}, and the database has "
            "never been migrated.\n"
            "  Run the migrations first:  alembic upgrade head"
        )

    return (
        f"Refusing to start: this build expects Alembic revision {expected}, "
        f"and the database is at {actual}.\n"
        "One of two things is true:\n"
        f"  - This process is old. Its image or checkout predates {actual}. "
        "Rebuild or pull:  docker compose build api worker migrate\n"
        f"  - The migrations have not run. The database is behind {expected}. "
        "Apply them:  alembic upgrade head\n"
        "Starting anyway is what DEV-051 was: thirteen days of a worker quietly "
        "running code that disagreed with its own database."
    )
