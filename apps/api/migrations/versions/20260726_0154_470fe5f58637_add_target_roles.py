"""add target roles

Roles the user is aiming for. These drive what the platform treats as relevant
in later phases — which jobs are worth surfacing, and which evidence matters
when tailoring a resume.

``(user_id, title)`` is unique so a double-submitted form cannot produce two
identical targets and skew every downstream count. ``is_active`` exists so a
target can be set aside without deleting the record of having pursued it.

Revision ID: 470fe5f58637
Revises: d9e9525f085e
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "470fe5f58637"
down_revision: str | None = "d9e9525f085e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_roles",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("role_family", sa.String(length=100), nullable=True),
        sa.Column("desired_seniority", sa.String(length=20), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "length(trim(title)) > 0", name=op.f("ck_target_roles_title_not_blank")
        ),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 1000", name=op.f("ck_target_roles_priority_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_target_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_roles")),
        sa.UniqueConstraint("user_id", "title", name="uq_target_roles_user_title"),
    )
    op.create_index(op.f("ix_target_roles_user_id"), "target_roles", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_target_roles_user_id"), table_name="target_roles")
    op.drop_table("target_roles")
