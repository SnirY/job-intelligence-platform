"""add skill_evidence

DEV-054. `docs/03-domain-model.md` lists `skill_evidence` in the MVP schema and
it was never built. Evidence existed only as a dataclass assembled in memory
during a match, from `experience_skills` and `project_skills`, and discarded
afterwards.

Two consequences, and the second is the one that mattered:

- **Four of the six sources the specification names had nowhere to live** —
  education, certification, resume, and manual evidence.
- **"I know this, and here is why" could not be said at all.** A skill learned
  outside employment could be claimed and never demonstrated, and the matcher
  scores a demonstrated skill higher than a listed one. The DEV-011 calibration
  found the consequence four times over in another form (DEV-064): postings
  asking for things the profile plainly has and does not record.

This table is **additive**. `experience_skills` and `project_skills` stay where
they are — a skill used in a role is a property of the role, and copying that
here would give one fact two places to disagree. The profile snapshot unions
the two.

Revision ID: b3c8d1e7f204
Revises: f2a91c47d8e3
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "b3c8d1e7f204"
down_revision: str | None = "f2a91c47d8e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_evidence",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("user_skill_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("entity_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_skill_evidence_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_skill_id"],
            ["user_skills.id"],
            name=op.f("fk_skill_evidence_user_skill_id_user_skills"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(source = 'MANUAL' AND entity_id IS NULL AND note IS NOT NULL "
            "AND length(trim(note)) > 0) OR (source <> 'MANUAL' AND entity_id IS NOT NULL)",
            name=op.f("ck_skill_evidence_evidence_has_a_source"),
        ),
        sa.UniqueConstraint(
            "user_skill_id",
            "source",
            "entity_id",
            name=op.f("uq_skill_evidence_skill_source_entity"),
        ),
    )
    op.create_index(
        op.f("ix_skill_evidence_user_skill_id"), "skill_evidence", ["user_skill_id"]
    )
    op.create_index(op.f("ix_skill_evidence_entity_id"), "skill_evidence", ["entity_id"])
    op.create_index(op.f("ix_skill_evidence_user_id"), "skill_evidence", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_skill_evidence_user_id"), table_name="skill_evidence")
    op.drop_index(op.f("ix_skill_evidence_entity_id"), table_name="skill_evidence")
    op.drop_index(op.f("ix_skill_evidence_user_skill_id"), table_name="skill_evidence")
    op.drop_table("skill_evidence")
