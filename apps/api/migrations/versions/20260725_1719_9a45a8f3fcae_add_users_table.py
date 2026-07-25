"""add users table

The internal user record. ``id`` is the platform's own UUID and is what every
user-owned foreign key will reference; the authentication provider's identifier
is confined to ``external_user_id``, scoped by ``auth_provider``.

The unique constraint on ``(auth_provider, external_user_id)`` is what makes
just-in-time provisioning idempotent: concurrent first requests race, one
inserts, the other is rejected and re-reads rather than creating a second
account for the same person. Scoping it by provider also means a future
migration can run with two issuers live instead of needing a flag day.

``email`` and ``display_name`` are nullable because many issuers — Clerk's
default session token among them — carry neither claim.

Revision ID: 9a45a8f3fcae
Revises: a1b2c3d4e5f6
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a45a8f3fcae"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("auth_provider", sa.String(length=50), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint(
            "auth_provider", "external_user_id", name="uq_users_external_identity"
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
