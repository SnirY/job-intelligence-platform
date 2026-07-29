"""add resume strategies, suggestions, and claims

The tailoring tables, staged the way docs/09-mvp-roadmap.md requires: a
strategy says what to do, a suggestion proposes one concrete change to one
item, and a claim records whether that change is supported by evidence. No
model output reaches a resume without passing all three.

resume_strategies.match_id is a foreign key in one direction only. A strategy
reads a match and never writes to one - the matching engine stays deterministic
and this is a consumer of it.

resume_claims.source_entity_id is again a loose reference to one of five career
tables, matching job_match_evidence and resume_items.

Revision ID: 4ccd785309cd
Revises: 1cb56d301646
Create Date: 2026-07-29 00:35:26.112629
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4ccd785309cd"
down_revision: str | None = "1cb56d301646"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_strategies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("match_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "emphasize",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "reduce", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("reorder_note", sa.Text(), nullable=True),
        sa.Column(
            "priority_projects",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "missing_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "career_gaps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "selection",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=60), nullable=True),
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
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
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.CheckConstraint("version > 0", name=op.f("ck_resume_strategies_version_positive")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_resume_strategies_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["job_matches.id"],
            name=op.f("fk_resume_strategies_match_id_job_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_strategies_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["resume_versions.id"],
            name=op.f("fk_resume_strategies_version_id_resume_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_strategies")),
    )
    op.create_index(
        op.f("ix_resume_strategies_job_id"), "resume_strategies", ["job_id"], unique=False
    )
    op.create_index(
        "ix_resume_strategies_job_version", "resume_strategies", ["job_id", "version"], unique=False
    )
    op.create_index(
        op.f("ix_resume_strategies_match_id"), "resume_strategies", ["match_id"], unique=False
    )
    op.create_index(
        op.f("ix_resume_strategies_user_id"), "resume_strategies", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_resume_strategies_version_id"), "resume_strategies", ["version_id"], unique=False
    )
    op.create_table(
        "resume_suggestions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("strategy_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("suggestion_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("risk", sa.String(length=10), server_default="LOW", nullable=False),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("suggested_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "length(trim(suggested_text)) > 0",
            name=op.f("ck_resume_suggestions_suggested_text_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["resume_items.id"],
            name=op.f("fk_resume_suggestions_item_id_resume_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["resume_strategies.id"],
            name=op.f("fk_resume_suggestions_strategy_id_resume_strategies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_suggestions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_suggestions")),
    )
    op.create_index(
        op.f("ix_resume_suggestions_item_id"), "resume_suggestions", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_resume_suggestions_strategy_id"),
        "resume_suggestions",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        "ix_resume_suggestions_strategy_order",
        "resume_suggestions",
        ["strategy_id", "display_order"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_suggestions_user_id"), "resume_suggestions", ["user_id"], unique=False
    )
    op.create_table(
        "resume_claims",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("suggestion_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=True),
        sa.Column("source_entity_id", sa.UUID(), nullable=True),
        sa.Column("confidence", sa.SmallInteger(), server_default="50", nullable=False),
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
            "confidence >= 0 AND confidence <= 100", name=op.f("ck_resume_claims_confidence_range")
        ),
        sa.CheckConstraint("length(trim(text)) > 0", name=op.f("ck_resume_claims_text_not_blank")),
        sa.ForeignKeyConstraint(
            ["suggestion_id"],
            ["resume_suggestions.id"],
            name=op.f("fk_resume_claims_suggestion_id_resume_suggestions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_resume_claims_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_claims")),
    )
    op.create_index("ix_resume_claims_suggestion", "resume_claims", ["suggestion_id"], unique=False)
    op.create_index(
        op.f("ix_resume_claims_suggestion_id"), "resume_claims", ["suggestion_id"], unique=False
    )
    op.create_index(op.f("ix_resume_claims_user_id"), "resume_claims", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_resume_claims_user_id"), table_name="resume_claims")
    op.drop_index(op.f("ix_resume_claims_suggestion_id"), table_name="resume_claims")
    op.drop_index("ix_resume_claims_suggestion", table_name="resume_claims")
    op.drop_table("resume_claims")
    op.drop_index(op.f("ix_resume_suggestions_user_id"), table_name="resume_suggestions")
    op.drop_index("ix_resume_suggestions_strategy_order", table_name="resume_suggestions")
    op.drop_index(op.f("ix_resume_suggestions_strategy_id"), table_name="resume_suggestions")
    op.drop_index(op.f("ix_resume_suggestions_item_id"), table_name="resume_suggestions")
    op.drop_table("resume_suggestions")
    op.drop_index(op.f("ix_resume_strategies_version_id"), table_name="resume_strategies")
    op.drop_index(op.f("ix_resume_strategies_user_id"), table_name="resume_strategies")
    op.drop_index(op.f("ix_resume_strategies_match_id"), table_name="resume_strategies")
    op.drop_index("ix_resume_strategies_job_version", table_name="resume_strategies")
    op.drop_index(op.f("ix_resume_strategies_job_id"), table_name="resume_strategies")
    op.drop_table("resume_strategies")
