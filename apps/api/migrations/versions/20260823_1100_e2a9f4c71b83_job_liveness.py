"""job liveness observations

Phase 12, Slice 2. Two nullable timestamps recording what a liveness check
observed about a posting: `last_seen_alive_at` when it last answered, and
`closed_detected_at` when it was first found gone.

Both are observations rather than state, and neither is authoritative over
`archived_at` — archiving stays a decision the user made about their own list.
A job can be closed and unarchived at the same time, which is a normal thing to
want to see.

Null keeps meaning *never observed*. A check that could not tell — a 403, a
timeout, a 5xx — writes nothing at all, so an unreachable server never leaves a
mark that reads like a verdict. See `application/jobs/liveness.py`.

No index. The obvious one would be `(user_id, closed_detected_at)` for a
"closed postings" filter, and no such filter exists yet; `active-task.md`
already carries an open question about whether the 88 existing indexes are the
right 88, so this adds none on speculation.

Revision ID: e2a9f4c71b83
Revises: a5f1c3e8b247
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a9f4c71b83"
down_revision: str | None = "a5f1c3e8b247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("last_seen_alive_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("closed_detected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "closed_detected_at")
    op.drop_column("jobs", "last_seen_alive_at")
