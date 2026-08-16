"""add skill_candidates, and re-resolve requirements the catalogue caught up with

DEV-062, candidate 2. `requirement_skills.py` refuses to let a job posting write
to the canonical catalogue, and says why at length. It also names the thing that
was missing — the unresolved name on the requirement is *"exactly what a later
reviewed-candidate mechanism would read from"*. `skill_candidates` is the queue
that mechanism reads into, and a person decides what leaves it.

**The backfill is the more immediately useful half.** `f2a91c47d8e3` grew the
catalogue by thirty skills yesterday and never re-resolved the requirements
already stored, because nothing in the codebase does that. So `HTML`, `CSS`,
`React Native`, `RESTful API` and seventeen others sat with `skill_id IS NULL`
while the skill they name was in the catalogue the whole time.

On the development database that is **21 of 44 distinct unresolved names** — not
a vocabulary gap at all, just a resolution nobody re-ran. Fixing it here shrinks
the queue to the names that genuinely need a human before anyone looks at it.

Revision ID: d4e7a2b91c58
Revises: c9d2e4f8a136
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision: str = "d4e7a2b91c58"
down_revision: str | None = "c9d2e4f8a136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_candidates",
        sa.Column(
            "id",
            PgUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("normalized_name", sa.String(120), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("occurrences", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_skill_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resolved_skill_id"],
            ["skills.id"],
            name=op.f("fk_skill_candidates_resolved_skill_id_skills"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(status = 'ACCEPTED' AND resolved_skill_id IS NOT NULL) OR status <> 'ACCEPTED'",
            name=op.f("ck_skill_candidates_accepted_names_a_skill"),
        ),
    )
    op.create_index(
        op.f("ix_skill_candidates_resolved_skill_id"), "skill_candidates", ["resolved_skill_id"]
    )
    op.create_index(op.f("ix_skill_candidates_status"), "skill_candidates", ["status"])

    _backfill_resolved_requirements()


def _backfill_resolved_requirements() -> None:
    """Point stored requirements at skills the catalogue has since gained.

    The normalisation is reproduced in SQL rather than imported from
    `normalize_skill_name`, for the reason every data migration in this tree
    gives: a migration must keep doing what it did on the day it ran, and
    importing application code makes its behaviour depend on a version of that
    code which may not exist any more.

    Kept in step with `_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")` — lowercase,
    collapse anything that is not alphanumeric or `+#` to a single hyphen, trim
    hyphens from the ends. `+` and `#` survive because merging them would make
    C, C++ and C# one skill.

    Canonical names first, aliases second and only for what canonical names did
    not answer, matching `resolve_known_skills`. A name that is both a canonical
    skill and someone's alias must resolve to the canonical one, or the answer
    depends on which statement ran first.
    """
    normalize = """
        trim(both '-' from regexp_replace(lower(skill_name), '[^a-z0-9+#]+', '-', 'g'))
    """

    op.execute(
        sa.text(
            f"""
            UPDATE job_requirements r
            SET skill_id = s.id
            FROM skills s
            WHERE r.skill_id IS NULL
              AND r.skill_name IS NOT NULL
              AND s.normalized_name = {normalize}
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE job_requirements r
            SET skill_id = a.skill_id
            FROM skill_aliases a
            WHERE r.skill_id IS NULL
              AND r.skill_name IS NOT NULL
              AND a.normalized_alias = {normalize}
            """
        )
    )


def downgrade() -> None:
    """Drops the queue. The backfill is deliberately not reversed.

    Reversing it would mean setting `skill_id` back to NULL on requirements that
    now correctly point at a real skill — throwing away a true fact to restore a
    false one. A downgrade is for undoing a schema change, not for making the
    data wrong again.
    """
    op.drop_index(op.f("ix_skill_candidates_status"), table_name="skill_candidates")
    op.drop_index(op.f("ix_skill_candidates_resolved_skill_id"), table_name="skill_candidates")
    op.drop_table("skill_candidates")
