"""add job matches, items, and evidence

Three tables, all additive. Nothing here touches the job, its analysis, or any
career row: a match is a derived opinion about them, and derived data must not
be able to edit its own inputs.

``job_matches`` is versioned per job, so recalculating appends and the previous
verdict stays readable — Phase 10's insights need the series, and a user who
disagrees with today's reading should still be able to see last week's.

``job_match_evidence.entity_id`` is deliberately not a foreign key: it points at
one of five career tables depending on ``evidence_type``. The label and detail
beside it are copies taken at match time, so a historical match still reads
correctly after the underlying row is edited.

Revision ID: e9907a86020f
Revises: b75af8c6081d
Create Date: 2026-07-27 16:23:54.828313
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9907a86020f"
down_revision: str | None = "b75af8c6081d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_matches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("profile_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("overall_score", sa.SmallInteger(), nullable=True),
        sa.Column("alignment_label", sa.String(length=40), nullable=True),
        sa.Column("score_cap", sa.SmallInteger(), nullable=True),
        sa.Column("score_cap_reason", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(length=20), nullable=False),
        sa.Column(
            "recommendation_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("confidence", sa.SmallInteger(), server_default="50", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "category_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "status_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("has_blockers", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("scored_requirements", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_requirements", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
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
            "confidence >= 0 AND confidence <= 100", name=op.f("ck_job_matches_confidence_range")
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name=op.f("ck_job_matches_overall_score_range"),
        ),
        sa.CheckConstraint(
            "scored_requirements >= 0 AND total_requirements >= scored_requirements",
            name=op.f("ck_job_matches_requirement_counts_sane"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_job_matches_version_positive")),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["job_analyses.id"],
            name=op.f("fk_job_matches_analysis_id_job_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_matches_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_job_matches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_matches")),
        sa.UniqueConstraint("job_id", "version", name="uq_job_matches_job_version"),
    )
    op.create_index(
        op.f("ix_job_matches_analysis_id"), "job_matches", ["analysis_id"], unique=False
    )
    op.create_index(op.f("ix_job_matches_job_id"), "job_matches", ["job_id"], unique=False)
    op.create_index(
        "ix_job_matches_job_version", "job_matches", ["job_id", "version"], unique=False
    )
    op.create_index(op.f("ix_job_matches_user_id"), "job_matches", ["user_id"], unique=False)
    op.create_table(
        "job_match_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("match_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), server_default="50", nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("is_blocker", sa.Boolean(), server_default="false", nullable=False),
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
            name=op.f("ck_job_match_items_confidence_range"),
        ),
        sa.CheckConstraint(
            "length(trim(explanation)) > 0", name=op.f("ck_job_match_items_explanation_not_blank")
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name=op.f("ck_job_match_items_score_range")
        ),
        sa.CheckConstraint("weight >= 0", name=op.f("ck_job_match_items_weight_not_negative")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_match_items_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["job_matches.id"],
            name=op.f("fk_job_match_items_match_id_job_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["job_requirements.id"],
            name=op.f("fk_job_match_items_requirement_id_job_requirements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_job_match_items_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_match_items")),
        sa.UniqueConstraint(
            "match_id", "requirement_id", name="uq_job_match_items_match_requirement"
        ),
    )
    op.create_index(op.f("ix_job_match_items_job_id"), "job_match_items", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_job_match_items_match_id"), "job_match_items", ["match_id"], unique=False
    )
    op.create_index(
        "ix_job_match_items_match_order",
        "job_match_items",
        ["match_id", "source_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_match_items_requirement_id"),
        "job_match_items",
        ["requirement_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_match_items_user_id"), "job_match_items", ["user_id"], unique=False
    )
    op.create_table(
        "job_match_evidence",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("match_item_id", sa.UUID(), nullable=False),
        sa.Column("evidence_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("relevance", sa.SmallInteger(), server_default="50", nullable=False),
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
            "length(trim(label)) > 0", name=op.f("ck_job_match_evidence_label_not_blank")
        ),
        sa.CheckConstraint(
            "relevance >= 0 AND relevance <= 100",
            name=op.f("ck_job_match_evidence_relevance_range"),
        ),
        sa.ForeignKeyConstraint(
            ["match_item_id"],
            ["job_match_items.id"],
            name=op.f("fk_job_match_evidence_match_item_id_job_match_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_job_match_evidence_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_match_evidence")),
    )
    op.create_index(
        "ix_job_match_evidence_item_relevance",
        "job_match_evidence",
        ["match_item_id", "relevance"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_match_evidence_match_item_id"),
        "job_match_evidence",
        ["match_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_match_evidence_user_id"), "job_match_evidence", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_match_evidence_user_id"), table_name="job_match_evidence")
    op.drop_index(op.f("ix_job_match_evidence_match_item_id"), table_name="job_match_evidence")
    op.drop_index("ix_job_match_evidence_item_relevance", table_name="job_match_evidence")
    op.drop_table("job_match_evidence")
    op.drop_index(op.f("ix_job_match_items_user_id"), table_name="job_match_items")
    op.drop_index(op.f("ix_job_match_items_requirement_id"), table_name="job_match_items")
    op.drop_index("ix_job_match_items_match_order", table_name="job_match_items")
    op.drop_index(op.f("ix_job_match_items_match_id"), table_name="job_match_items")
    op.drop_index(op.f("ix_job_match_items_job_id"), table_name="job_match_items")
    op.drop_table("job_match_items")
    op.drop_index(op.f("ix_job_matches_user_id"), table_name="job_matches")
    op.drop_index("ix_job_matches_job_version", table_name="job_matches")
    op.drop_index(op.f("ix_job_matches_job_id"), table_name="job_matches")
    op.drop_index(op.f("ix_job_matches_analysis_id"), table_name="job_matches")
    op.drop_table("job_matches")
