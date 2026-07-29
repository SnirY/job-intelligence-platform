"""add resumes, versions, sections, and items

The resume data model, with no tailoring tables. Slice 1 of Phase 7 ships a
hand-built base resume and nothing AI-driven, so the strategy, suggestion, and
claim tables arrive with the slices that use them rather than sitting empty.

Four tables, and the two constraints worth naming:

``resumes.job_id_matches_family`` — a JOB_SPECIFIC resume without a job is not
job-specific, and a MASTER or BASE resume pointing at one job contradicts its
own family. Expressed as an equality between two booleans so both directions
are enforced by the one check.

``resume_items.sourced_items_have_an_entity`` — anything claiming a career
source must say which row, or the reference cannot be followed and truth
validation in slice 4 has nothing to check against. MANUAL is the only source
allowed to point at nothing.

``resume_items.source_entity_id`` is deliberately not a foreign key: it points
at one of five career tables depending on ``source_type``, the same shape and
the same reason as ``job_match_evidence.entity_id``.

Revision ID: 1cb56d301646
Revises: e9907a86020f
Create Date: 2026-07-28 23:48:21.104500
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1cb56d301646"
down_revision: str | None = "e9907a86020f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("family", sa.String(length=20), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("parent_resume_id", sa.UUID(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "(family = 'JOB_SPECIFIC') = (job_id IS NOT NULL)",
            name=op.f("ck_resumes_job_id_matches_family"),
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_resumes_title_not_blank")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_resumes_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_resume_id"],
            ["resumes.id"],
            name=op.f("fk_resumes_parent_resume_id_resumes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_resumes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resumes")),
    )
    op.create_index(op.f("ix_resumes_job_id"), "resumes", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_resumes_parent_resume_id"), "resumes", ["parent_resume_id"], unique=False
    )
    op.create_index("ix_resumes_user_family", "resumes", ["user_id", "family"], unique=False)
    op.create_index(op.f("ix_resumes_user_id"), "resumes", ["user_id"], unique=False)
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resume_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("version > 0", name=op.f("ck_resume_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["resume_versions.id"],
            name=op.f("fk_resume_versions_parent_version_id_resume_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name=op.f("fk_resume_versions_resume_id_resumes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_versions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_versions")),
        sa.UniqueConstraint("resume_id", "version", name="uq_resume_versions_resume_version"),
    )
    op.create_index(
        op.f("ix_resume_versions_parent_version_id"),
        "resume_versions",
        ["parent_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_versions_resume_id"), "resume_versions", ["resume_id"], unique=False
    )
    op.create_index(
        "ix_resume_versions_resume_version",
        "resume_versions",
        ["resume_id", "version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_versions_user_id"), "resume_versions", ["user_id"], unique=False
    )
    op.create_table(
        "resume_sections",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_sections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["resume_versions.id"],
            name=op.f("fk_resume_sections_version_id_resume_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_sections")),
    )
    op.create_index(
        op.f("ix_resume_sections_user_id"), "resume_sections", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_resume_sections_version_id"), "resume_sections", ["version_id"], unique=False
    )
    op.create_index(
        "ix_resume_sections_version_order",
        "resume_sections",
        ["version_id", "display_order"],
        unique=False,
    )
    op.create_table(
        "resume_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=20), server_default="MANUAL", nullable=False),
        sa.Column("source_entity_id", sa.UUID(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading", sa.String(length=300), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
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
            "(source_type = 'MANUAL') OR (source_entity_id IS NOT NULL)",
            name=op.f("ck_resume_items_sourced_items_have_an_entity"),
        ),
        sa.CheckConstraint("length(trim(text)) > 0", name=op.f("ck_resume_items_text_not_blank")),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["resume_sections.id"],
            name=op.f("fk_resume_items_section_id_resume_sections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_items_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_items")),
    )
    op.create_index(
        op.f("ix_resume_items_section_id"), "resume_items", ["section_id"], unique=False
    )
    op.create_index(
        "ix_resume_items_section_order",
        "resume_items",
        ["section_id", "display_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_items_source_entity_id"), "resume_items", ["source_entity_id"], unique=False
    )
    op.create_index(op.f("ix_resume_items_user_id"), "resume_items", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_resume_items_user_id"), table_name="resume_items")
    op.drop_index(op.f("ix_resume_items_source_entity_id"), table_name="resume_items")
    op.drop_index("ix_resume_items_section_order", table_name="resume_items")
    op.drop_index(op.f("ix_resume_items_section_id"), table_name="resume_items")
    op.drop_table("resume_items")
    op.drop_index("ix_resume_sections_version_order", table_name="resume_sections")
    op.drop_index(op.f("ix_resume_sections_version_id"), table_name="resume_sections")
    op.drop_index(op.f("ix_resume_sections_user_id"), table_name="resume_sections")
    op.drop_table("resume_sections")
    op.drop_index(op.f("ix_resume_versions_user_id"), table_name="resume_versions")
    op.drop_index("ix_resume_versions_resume_version", table_name="resume_versions")
    op.drop_index(op.f("ix_resume_versions_resume_id"), table_name="resume_versions")
    op.drop_index(op.f("ix_resume_versions_parent_version_id"), table_name="resume_versions")
    op.drop_table("resume_versions")
    op.drop_index(op.f("ix_resumes_user_id"), table_name="resumes")
    op.drop_index("ix_resumes_user_family", table_name="resumes")
    op.drop_index(op.f("ix_resumes_parent_resume_id"), table_name="resumes")
    op.drop_index(op.f("ix_resumes_job_id"), table_name="resumes")
    op.drop_table("resumes")
