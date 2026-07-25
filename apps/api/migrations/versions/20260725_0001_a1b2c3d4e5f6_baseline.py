"""Baseline revision

Establishes the migration chain and the ``alembic_version`` bookkeeping table on
a clean database. Phase 0 is infrastructure only, so there is no schema to
create yet; the first domain migration will chain from this revision.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
