"""seed canonical skills and their common aliases

Reference data, not user data. ``docs/05-ai-and-matching.md`` defines skill
resolution as raw name -> alias lookup -> canonical skill, and
``docs/03-domain-model.md`` names exactly these examples: JS -> JavaScript,
Postgres -> PostgreSQL, React.js -> React.

Normalization alone cannot do this job. It collapses case, spacing, and
separators, so "React" and "react" already agree — but "React.js" is a different
string by any mechanical rule, and only a mapping says the two mean the same
thing. Without that mapping a job asking for React finds no evidence in a
profile that says React.js, which is precisely the failure Phase 6 exists to
avoid.

The list is deliberately short: only variants that are unambiguous and common.
It is a starting point that grows from real job descriptions in Phase 5, not an
attempt to enumerate a taxonomy up front.

Revision ID: b71c4a90d2e5
Revises: ce623c8513ea
Create Date: 2026-07-26
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b71c4a90d2e5"
down_revision: str | None = "ce623c8513ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")


def _normalize(raw: str) -> str:
    """Mirrors jip_api.domain.career.skills.normalize_skill_name.

    Duplicated on purpose: a migration must keep producing the same rows it
    produced when it first ran, even if the application's rule later changes.
    Importing the live function would make this migration's output drift.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip().replace(" ", "-")


# (canonical name, category, [aliases])
SEED: list[tuple[str, str, list[str]]] = [
    ("JavaScript", "LANGUAGE", ["JS", "ECMAScript"]),
    ("TypeScript", "LANGUAGE", ["TS"]),
    ("Python", "LANGUAGE", ["Python3", "Py"]),
    ("PostgreSQL", "DATABASE", ["Postgres", "psql"]),
    ("React", "FRAMEWORK", ["React.js", "ReactJS"]),
    ("Node.js", "PLATFORM", ["Node", "NodeJS"]),
    ("Kubernetes", "PLATFORM", ["K8s"]),
    ("Amazon Web Services", "PLATFORM", ["AWS"]),
    ("Continuous Integration", "PRACTICE", ["CI"]),
    ("Machine Learning", "DOMAIN", ["ML"]),
    ("Computer Vision", "DOMAIN", ["CV"]),
]


def upgrade() -> None:
    connection = op.get_bind()

    for canonical, category, aliases in SEED:
        skill_id = connection.execute(
            sa.text(
                """
                INSERT INTO skills (canonical_name, normalized_name, category)
                VALUES (:canonical, :normalized, :category)
                ON CONFLICT (normalized_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                RETURNING id
                """
            ),
            {"canonical": canonical, "normalized": _normalize(canonical), "category": category},
        ).scalar_one()

        for alias in aliases:
            normalized_alias = _normalize(alias)
            # An alias must never collide with a canonical name, or resolution
            # would depend on which lookup ran first.
            if normalized_alias == _normalize(canonical):
                continue
            connection.execute(
                sa.text(
                    """
                    INSERT INTO skill_aliases (skill_id, alias, normalized_alias)
                    VALUES (:skill_id, :alias, :normalized_alias)
                    ON CONFLICT (normalized_alias) DO NOTHING
                    """
                ),
                {"skill_id": skill_id, "alias": alias, "normalized_alias": normalized_alias},
            )


def downgrade() -> None:
    """Remove only the seeded rows, and only where nobody has claimed them.

    A user who added "Python" now points at a seeded row. Deleting it would
    break their claim, so seeded skills still in use are left alone — the
    aliases go, the shared skills stay.
    """
    connection = op.get_bind()

    for canonical, _category, aliases in SEED:
        for alias in aliases:
            connection.execute(
                sa.text("DELETE FROM skill_aliases WHERE normalized_alias = :normalized"),
                {"normalized": _normalize(alias)},
            )

        connection.execute(
            sa.text(
                """
                DELETE FROM skills
                WHERE normalized_name = :normalized
                  AND NOT EXISTS (SELECT 1 FROM user_skills WHERE skill_id = skills.id)
                  AND NOT EXISTS (SELECT 1 FROM project_skills WHERE skill_id = skills.id)
                  AND NOT EXISTS (SELECT 1 FROM experience_skills WHERE skill_id = skills.id)
                """
            ),
            {"normalized": _normalize(canonical)},
        )
