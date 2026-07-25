"""add career profile

One row per user, holding the free-form parts of the profile: headline, summary,
years of experience, location, and links.

``user_id`` is unique rather than merely indexed, which makes the one-to-one
relationship a database guarantee instead of an application convention. The
cascade means deleting a user removes the profile in the same statement rather
than leaving an orphan for a cleanup job nobody writes.

``links`` is JSONB because nothing filters, sorts, or joins on it. The check
constraint on ``years_of_experience`` refuses nonsense regardless of which
caller wrote it.

Revision ID: d9e9525f085e
Revises: 9a45a8f3fcae
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e9525f085e"
down_revision: str | None = "9a45a8f3fcae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "career_profiles",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("headline", sa.String(length=200), nullable=True),
        sa.Column("professional_summary", sa.Text(), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("current_location", sa.String(length=200), nullable=True),
        sa.Column(
            "links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "years_of_experience IS NULL OR "
            "(years_of_experience >= 0 AND years_of_experience <= 80)",
            name=op.f("ck_career_profiles_years_of_experience_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_career_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_career_profiles_user_id")),
    )


def downgrade() -> None:
    op.drop_table("career_profiles")
