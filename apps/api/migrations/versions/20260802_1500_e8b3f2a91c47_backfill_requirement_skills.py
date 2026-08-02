"""resolve requirements against the grown skill catalogue

DEV-032 grew the catalogue from 30 rows to 141. It did not touch the
requirements already stored, and `job_requirements.skill_id` is written once,
at analysis time, from whatever the catalogue knew then.

So the fix applied only to postings analysed after it. On a real account the
Insights screen still showed "Object-oriented design", "Algorithms", "AI/ML"
and "Data structures" as uncatalogued — all four now seeded, none of them
resolved, because their rows were written days earlier:

    AWS                     resolved     (in the original seed)
    Object-oriented design  unresolved   (seeded by DEV-032)
    Algorithms              unresolved
    Data structures         unresolved
    AI/ML                   unresolved

Re-analysing every job would fix it and would cost two model calls per posting
to recompute something already correct. This resolves the names that are
already stored, which is the same operation `resolve_known_skills` performs and
the same lookup order: canonical name first, then alias.

Only fills nulls. A requirement that already resolved keeps what it has —
nothing here reinterprets a past reading, it only finishes one that could not
be completed at the time.

Revision ID: e8b3f2a91c47
Revises: c4d7e1f9ab32
Create Date: 2026-08-02
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3f2a91c47"
down_revision: str | None = "c4d7e1f9ab32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")


def _normalize(raw: str) -> str:
    """Mirrors ``jip_api.domain.career.skills.normalize_skill_name``.

    Duplicated for the reason both skill migrations give: a migration has to
    keep producing what it produced when it first ran.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip().replace(" ", "-")


def upgrade() -> None:
    connection = op.get_bind()

    unresolved = connection.execute(
        sa.text(
            """
            SELECT DISTINCT skill_name
            FROM job_requirements
            WHERE skill_id IS NULL AND skill_name IS NOT NULL
            """
        )
    ).scalars()

    for name in unresolved:
        key = _normalize(name)
        skill_id = connection.execute(
            sa.text(
                """
                SELECT id FROM skills WHERE normalized_name = :key
                UNION ALL
                SELECT skill_id FROM skill_aliases WHERE normalized_alias = :key
                LIMIT 1
                """
            ),
            {"key": key},
        ).scalar_one_or_none()

        if skill_id is None:
            # Correct outcome for a phrase that is not a skill — "General-purpose
            # programming language", "performance-critical software". Left null
            # rather than forced onto the nearest match, because a wrong
            # canonical skill would put a candidate's Python against a
            # requirement that never asked for Python.
            continue

        connection.execute(
            sa.text(
                """
                UPDATE job_requirements
                SET skill_id = :skill_id
                WHERE skill_id IS NULL AND skill_name = :name
                """
            ),
            {"skill_id": skill_id, "name": name},
        )


def downgrade() -> None:
    """Nothing.

    The rows this filled are indistinguishable from ones written correctly at
    analysis time, and clearing them would undo resolutions that never depended
    on this migration. An irreversible data repair is honest about being one.
    """
