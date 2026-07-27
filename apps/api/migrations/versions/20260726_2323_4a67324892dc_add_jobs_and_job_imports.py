"""add jobs and job imports

Two tables, deliberately separate.

``jobs`` is the working record: what the user sees, edits, filters, and — from
Phase 6 — matches against. ``job_imports`` is the receipt, holding the content
exactly as it arrived and never updated afterwards.

The split is what makes source preservation a schema property rather than a
convention. A posting is usually taken down within weeks, and the original is
the only evidence of what was actually advertised (``GOAL.md``: preserve raw
inputs; do not overwrite meaningful historical state).

Nothing here is AI output. ``role_family``, ``seniority``, and the rest hold
what the *user* typed; Phase 5 writes its inferences to their own versioned
tables so an inference can never overwrite a person's answer.

Revision ID: 4a67324892dc
Revises: 3efa7771ea98
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a67324892dc"
down_revision: str | None = "3efa7771ea98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("work_mode", sa.String(length=20), nullable=True),
        sa.Column("employment_type", sa.String(length=20), nullable=True),
        sa.Column("seniority", sa.String(length=20), nullable=True),
        sa.Column("role_family", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("normalized_source_url", sa.String(length=2000), nullable=True),
        sa.Column("import_method", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("salary_text", sa.String(length=200), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetch_error", sa.Text(), nullable=True),
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
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "content_hash IS NULL OR length(content_hash) = 64",
            name=op.f("ck_jobs_content_hash_length"),
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_jobs_title_not_blank")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_company"), "jobs", ["company"], unique=False)
    op.create_index(op.f("ix_jobs_content_hash"), "jobs", ["content_hash"], unique=False)
    op.create_index(op.f("ix_jobs_normalized_title"), "jobs", ["normalized_title"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_user_content_hash", "jobs", ["user_id", "content_hash"], unique=False)
    op.create_index("ix_jobs_user_created", "jobs", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    op.create_index(
        "ix_jobs_user_normalized_url", "jobs", ["user_id", "normalized_source_url"], unique=False
    )
    op.create_table(
        "job_imports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("import_method", sa.String(length=30), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("content_bytes", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.String(length=2000), nullable=True),
        sa.Column(
            "redirect_chain",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_imports_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_job_imports_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_imports")),
    )
    op.create_index(op.f("ix_job_imports_job_id"), "job_imports", ["job_id"], unique=False)
    op.create_index(op.f("ix_job_imports_user_id"), "job_imports", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_imports_user_id"), table_name="job_imports")
    op.drop_index(op.f("ix_job_imports_job_id"), table_name="job_imports")
    op.drop_table("job_imports")
    op.drop_index("ix_jobs_user_normalized_url", table_name="jobs")
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index("ix_jobs_user_created", table_name="jobs")
    op.drop_index("ix_jobs_user_content_hash", table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_normalized_title"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_content_hash"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_company"), table_name="jobs")
    op.drop_table("jobs")
