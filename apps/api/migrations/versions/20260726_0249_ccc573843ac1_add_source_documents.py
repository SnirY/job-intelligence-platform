"""add source documents

Metadata and extracted text for uploaded files. The file itself lives in object
storage under ``storage_key``; nothing binary is stored here
(``docs/04-system-architecture.md``).

``extracted_text`` is kept verbatim so a later parser version can re-read the
document without asking the user to upload it again, and so a parsing failure
never costs them the upload (``GOAL.md``: failures must not destroy user work).

Revision ID: ccc573843ac1
Revises: 470fe5f58637
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ccc573843ac1"
down_revision: str | None = "470fe5f58637"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_source_documents_size_positive")),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name=op.f("ck_source_documents_sha256_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_source_documents_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_documents")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_source_documents_storage_key")),
    )
    op.create_index(
        op.f("ix_source_documents_user_id"), "source_documents", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_documents_user_id"), table_name="source_documents")
    op.drop_table("source_documents")
