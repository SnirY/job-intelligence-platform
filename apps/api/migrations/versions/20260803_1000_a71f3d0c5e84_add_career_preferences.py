"""add career preferences

DEV-035. `CareerPreferences` is defined in `docs/03-domain-model.md` and
`career_preferences` is in its MVP schema list; `docs/01` puts career
preferences inside the Career Profile module; `docs/02` ends onboarding with
"Set Preferences"; `docs/05` names user preferences among the inputs a
recommendation considers. None of it was ever built.

One row per user, enforced by a unique constraint rather than by convention —
the same choice `career_profiles` makes and for the same reason.

Every list defaults to empty and every scalar to null, because absent has to
mean *no constraint*. A default that narrowed anything would turn a user who
has not opened the screen into one who has declined everything.

Revision ID: a71f3d0c5e84
Revises: e8b3f2a91c47
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a71f3d0c5e84"
down_revision: str | None = "e8b3f2a91c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "career_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "work_modes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "employment_types",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "locations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("open_to_relocation", sa.Boolean(), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "excluded_role_families",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_career_preferences"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_career_preferences_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", name="uq_career_preferences_user_id"),
        sa.CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="ck_salary_min_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("career_preferences")
