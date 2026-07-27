"""add job analysis, requirements, and responsibilities

Three tables, all additive. Nothing here touches ``jobs`` or ``job_imports``:
the original description and the import records stay exactly as Phase 4 wrote
them, and an analysis that disagrees with them is a new row rather than an edit.

``job_analyses`` is versioned per job, so reanalysis appends and the previous
interpretation stays readable. Requirements and responsibilities cascade from
their analysis, which is what makes deleting a bad version a single statement.

The one nullable foreign key worth noting is ``job_requirements.skill_id``: it
is ON DELETE SET NULL rather than CASCADE, because removing a canonical skill
must not silently delete the requirement that mentioned it. The requirement
still has ``skill_name``, which is what the posting actually said.

Revision ID: b75af8c6081d
Revises: 4a67324892dc
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b75af8c6081d"
down_revision: str | None = "4a67324892dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_analyses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("role_family", sa.String(length=30), nullable=True),
        sa.Column("secondary_role_family", sa.String(length=30), nullable=True),
        sa.Column("role_family_confidence", sa.SmallInteger(), nullable=True),
        sa.Column("role_family_reasoning", sa.Text(), nullable=True),
        sa.Column("seniority", sa.String(length=20), server_default="UNKNOWN", nullable=False),
        sa.Column("seniority_confidence", sa.SmallInteger(), nullable=True),
        sa.Column("seniority_reasoning", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=120), nullable=True),
        sa.Column("years_experience_min", sa.SmallInteger(), nullable=True),
        sa.Column("years_experience_max", sa.SmallInteger(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("parse_prompt_version", sa.String(length=60), nullable=False),
        sa.Column("analysis_prompt_version", sa.String(length=60), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
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
            "role_family_confidence IS NULL OR (role_family_confidence >= 0 AND role_family_confidence <= 100)",
            name=op.f("ck_job_analyses_role_family_confidence_range"),
        ),
        sa.CheckConstraint(
            "seniority_confidence IS NULL OR (seniority_confidence >= 0 AND seniority_confidence <= 100)",
            name=op.f("ck_job_analyses_seniority_confidence_range"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_job_analyses_version_positive")),
        sa.CheckConstraint(
            "years_experience_max IS NULL OR (years_experience_max >= 0 AND years_experience_max <= 80)",
            name=op.f("ck_job_analyses_years_max_range"),
        ),
        sa.CheckConstraint(
            "years_experience_min IS NULL OR (years_experience_min >= 0 AND years_experience_min <= 80)",
            name=op.f("ck_job_analyses_years_min_range"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_analyses_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_job_analyses_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_analyses")),
        sa.UniqueConstraint("job_id", "version", name="uq_job_analyses_job_version"),
    )
    op.create_index(op.f("ix_job_analyses_job_id"), "job_analyses", ["job_id"], unique=False)
    op.create_index(
        "ix_job_analyses_job_version", "job_analyses", ["job_id", "version"], unique=False
    )
    op.create_index(op.f("ix_job_analyses_user_id"), "job_analyses", ["user_id"], unique=False)
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("requirement_type", sa.String(length=30), nullable=False),
        sa.Column("importance", sa.String(length=20), nullable=False),
        sa.Column("explicitness", sa.String(length=20), server_default="EXPLICIT", nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.String(length=300), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), server_default="50", nullable=False),
        sa.Column("source_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=True),
        sa.Column("skill_name", sa.String(length=120), nullable=True),
        sa.Column("years_min", sa.SmallInteger(), nullable=True),
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
            "confidence >= 0 AND confidence <= 100",
            name=op.f("ck_job_requirements_confidence_range"),
        ),
        sa.CheckConstraint(
            "length(trim(normalized_text)) > 0",
            name=op.f("ck_job_requirements_normalized_text_not_blank"),
        ),
        sa.CheckConstraint(
            "length(trim(source_text)) > 0", name=op.f("ck_job_requirements_source_text_not_blank")
        ),
        sa.CheckConstraint(
            "years_min IS NULL OR (years_min >= 0 AND years_min <= 80)",
            name=op.f("ck_job_requirements_years_range"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["job_analyses.id"],
            name=op.f("fk_job_requirements_analysis_id_job_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_requirements_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("fk_job_requirements_skill_id_skills"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_job_requirements_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_requirements")),
    )
    op.create_index(
        op.f("ix_job_requirements_analysis_id"), "job_requirements", ["analysis_id"], unique=False
    )
    op.create_index(
        "ix_job_requirements_analysis_order",
        "job_requirements",
        ["analysis_id", "source_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_requirements_job_id"), "job_requirements", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_requirements_skill_id"), "job_requirements", ["skill_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_requirements_user_id"), "job_requirements", ["user_id"], unique=False
    )
    op.create_table(
        "job_responsibilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.SmallInteger(), server_default="50", nullable=False),
        sa.Column("source_order", sa.Integer(), server_default="0", nullable=False),
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
            "confidence >= 0 AND confidence <= 100",
            name=op.f("ck_job_responsibilities_confidence_range"),
        ),
        sa.CheckConstraint(
            "length(trim(text)) > 0", name=op.f("ck_job_responsibilities_text_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["job_analyses.id"],
            name=op.f("fk_job_responsibilities_analysis_id_job_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_responsibilities_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_job_responsibilities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_responsibilities")),
    )
    op.create_index(
        op.f("ix_job_responsibilities_analysis_id"),
        "job_responsibilities",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_responsibilities_analysis_order",
        "job_responsibilities",
        ["analysis_id", "source_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_responsibilities_job_id"), "job_responsibilities", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_responsibilities_user_id"), "job_responsibilities", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_responsibilities_user_id"), table_name="job_responsibilities")
    op.drop_index(op.f("ix_job_responsibilities_job_id"), table_name="job_responsibilities")
    op.drop_index("ix_job_responsibilities_analysis_order", table_name="job_responsibilities")
    op.drop_index(op.f("ix_job_responsibilities_analysis_id"), table_name="job_responsibilities")
    op.drop_table("job_responsibilities")
    op.drop_index(op.f("ix_job_requirements_user_id"), table_name="job_requirements")
    op.drop_index(op.f("ix_job_requirements_skill_id"), table_name="job_requirements")
    op.drop_index(op.f("ix_job_requirements_job_id"), table_name="job_requirements")
    op.drop_index("ix_job_requirements_analysis_order", table_name="job_requirements")
    op.drop_index(op.f("ix_job_requirements_analysis_id"), table_name="job_requirements")
    op.drop_table("job_requirements")
    op.drop_index(op.f("ix_job_analyses_user_id"), table_name="job_analyses")
    op.drop_index("ix_job_analyses_job_version", table_name="job_analyses")
    op.drop_index(op.f("ix_job_analyses_job_id"), table_name="job_analyses")
    op.drop_table("job_analyses")
