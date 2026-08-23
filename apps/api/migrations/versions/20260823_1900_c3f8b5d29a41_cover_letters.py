"""cover letters and their claims

The first of the capabilities the career-ops comparison recorded as deferred,
and the one closest to what already exists: a cover letter goes through the same
gate a resume rewrite does — a model proposes, `truth.py` decides whether the
profile supports it, a person clears it.

One difference shapes both tables. A resume rewrite is anchored: there is an
original line, and validation compares the two. **A letter has no original**, so
every number in it is invented unless it came from the profile. Validation runs
against an empty original, which is the strictest setting `truth.py` has.

`cover_letters.job_id` cascades on delete. Unlike an application, a letter
written for a role has no meaning once the role is gone.

`cover_letter_claims` mirrors `resume_claims` and exists for the same reason: a
verdict whose working the user cannot see is one they cannot argue with, and
`docs/06` wants a blocked claim quoted back rather than silently dropped.

Revision ID: c3f8b5d29a41
Revises: b7d4e9a2c015
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "c3f8b5d29a41"
down_revision: str | None = "b7d4e9a2c015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cover_letters",
        sa.Column(
            "id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("angle", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("angle_warning", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(60), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cover_letters_user_id", "cover_letters", ["user_id"])
    op.create_index("ix_cover_letters_user_job", "cover_letters", ["user_id", "job_id", "created_at"])

    op.create_table(
        "cover_letter_claims",
        sa.Column(
            "id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()
        ),
        sa.Column(
            "user_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cover_letter_id",
            PgUUID(as_uuid=True),
            sa.ForeignKey("cover_letters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_cover_letter_claims_user_id", "cover_letter_claims", ["user_id"])
    op.create_index("ix_cover_letter_claims_letter", "cover_letter_claims", ["cover_letter_id"])


def downgrade() -> None:
    op.drop_index("ix_cover_letter_claims_letter", table_name="cover_letter_claims")
    op.drop_index("ix_cover_letter_claims_user_id", table_name="cover_letter_claims")
    op.drop_table("cover_letter_claims")
    op.drop_index("ix_cover_letters_user_job", table_name="cover_letters")
    op.drop_index("ix_cover_letters_user_id", table_name="cover_letters")
    op.drop_table("cover_letters")
