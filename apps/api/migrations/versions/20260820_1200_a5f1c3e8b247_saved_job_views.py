"""add saved_job_views

A named set of list filters. Reaching a subset of the jobs list is already
cheap; returning to one costs re-deriving the whole combination from memory,
and the combinations that matter are the ones people invented — "remote, no
blockers", "companies to watch", "career change".

`filters` is JSONB rather than a column each, which is the opposite of the
choice `job_match_items` made and for the reason that one gives: its fields are
columns because insights query *across* them. Nothing asks a question across
saved views. One is only ever read whole, by the person who owns it, and a
column per filter would mean a migration every time the list grows one.

The unique constraint is on `(user_id, name)`. Two views called "Remote" is a
list nobody can navigate, and the second one silently wins.

Revision ID: a5f1c3e8b247
Revises: d4e7a2b91c58
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "a5f1c3e8b247"
down_revision: str | None = "d4e7a2b91c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_job_views",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_job_views_user_name"),
        sa.CheckConstraint("length(trim(name)) > 0", name="saved_view_name_not_blank"),
    )
    op.create_index("ix_saved_job_views_user_id", "saved_job_views", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_job_views_user_id", table_name="saved_job_views")
    op.drop_table("saved_job_views")
