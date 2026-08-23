"""watched boards and discovered postings

Phase 12, Slice 1. Two tables behind board discovery.

`watched_boards` is which companies to scan, per user. These endpoints are
per-company — there is no global search across Greenhouse — so discovery means
"watch these boards", and this is that list. `paused_at` rather than deletion,
so a board can leave a scan without taking the postings found through it.
`last_error` sits per board rather than per run because "we read four of your
five" is only actionable if the screen can name the fifth.

`discovered_postings` is what those boards returned, and it is deliberately not
`jobs`. A discovered posting is a candidate nobody chose; the job library is the
list whose contents are supposed to mean "I am interested in this". Mixing them
would change what every count on the dashboard means with nothing on screen
saying so. A scan writes here, a person promotes, and promotion creates the job
— the same boundary the career profile draws between an AI proposal and a
confirmed fact.

The unique constraint on `(user_id, provider, board, external_id)` is what makes
a re-scan idempotent. Without it every run offers the same postings again and
the review list is unusable by the second week.

`first_seen_at` never moves once written. It is the only thing that can later
answer "has this company been reposting the same role for four months", which is
Slice 3's strongest legitimacy signal and costs nothing to keep now.

No change to `jobs`. `JobImportMethod.DISCOVERED` needs no migration because
`StrEnumType` stores these values as VARCHAR precisely so that adding a member
does not need one.

Revision ID: b7d4e9a2c015
Revises: e2a9f4c71b83
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "b7d4e9a2c015"
down_revision: str | None = "e2a9f4c71b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watched_boards",
        sa.Column(
            "id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("token", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "provider", "token", name="uq_watched_board"),
    )
    op.create_index("ix_watched_boards_user_id", "watched_boards", ["user_id"])

    op.create_table(
        "discovered_postings",
        sa.Column(
            "id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("board", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "promoted_job_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id", "provider", "board", "external_id", name="uq_discovered_posting"
        ),
    )
    op.create_index("ix_discovered_postings_user_id", "discovered_postings", ["user_id"])
    op.create_index(
        "ix_discovered_user_first_seen", "discovered_postings", ["user_id", "first_seen_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_discovered_user_first_seen", table_name="discovered_postings")
    op.drop_index("ix_discovered_postings_user_id", table_name="discovered_postings")
    op.drop_table("discovered_postings")
    op.drop_index("ix_watched_boards_user_id", table_name="watched_boards")
    op.drop_table("watched_boards")
