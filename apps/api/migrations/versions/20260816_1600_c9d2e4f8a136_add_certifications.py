"""add certifications

DEV-052. `docs/01-product-requirements.md` lists certifications in the Career
Profile module beside skills, experience, education and projects.
`docs/03-domain-model.md` names `certification` as one of the six evidence
sources. `docs/06-resume-engine.md` names them twice as a resume section. One of
the three was built: a free-text box in the resume editor.

The cost was not the missing collection. `RequirementType` had no CERTIFICATION,
so a posting demanding one was classified EDUCATION — the job parser prompt said
in as many words that EDUCATION covers "degrees, fields of study,
certifications". `_match_education` then searched degree, institution and field
of study, found no overlap, and returned:

    "Your education does not appear to cover this."

**A user holding the certification was told their education does not cover it**,
and at CORE importance that GAP became a BLOCKER capping the whole match at 45.

Separate from `education` on purpose. A credential expires and carries an issuer
reference; a degree does neither. Storing them together would leave "is this
still valid?" unanswerable for the rows where it is the entire question.

Revision ID: c9d2e4f8a136
Revises: b3c8d1e7f204
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "c9d2e4f8a136"
down_revision: str | None = "b3c8d1e7f204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "certifications",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("issuer", sa.String(200), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("credential_id", sa.String(200), nullable=True),
        sa.Column("credential_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_certifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_certifications_name_not_blank")),
        sa.CheckConstraint(
            "length(trim(issuer)) > 0", name=op.f("ck_certifications_issuer_not_blank")
        ),
        sa.CheckConstraint(
            "expires_on IS NULL OR issued_on IS NULL OR expires_on >= issued_on",
            name=op.f("ck_certifications_expiry_after_issue"),
        ),
    )
    op.create_index(op.f("ix_certifications_user_id"), "certifications", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_certifications_user_id"), table_name="certifications")
    op.drop_table("certifications")
