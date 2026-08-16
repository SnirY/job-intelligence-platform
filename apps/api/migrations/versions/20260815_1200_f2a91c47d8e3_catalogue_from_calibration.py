"""grow the skill catalogue from the DEV-011 calibration postings

DEV-032 grew this from 30 rows to 141 based on two postings. Seven more,
read for the DEV-011 calibration, say it is still short — and short of things
nobody would defend leaving out.

**Measured across all seven: 42 of 191 skill-bearing requirements resolved to
nothing. Twenty-two per cent.**

A catalogue for software engineers that does not know **HTML** or **CSS**. It
also did not know JSON, NumPy, Pandas, scikit-learn, Selenium, Cypress,
Playwright, React Native, or GitHub — while knowing GitLab and GitHub Actions,
which is how `GitHub/GitLab` came to resolve to neither half of itself.

An unresolved skill is not an error, it is a null column, so this fails
silently: the requirement falls back to a weaker text comparison, usually lands
as a gap, and the user is told they lack something the catalogue simply never
learned. On posting 7 that cost `CSS`, `HTML` and `JSON` at REQUIRED weight and
`RESTful API` against a profile that holds `REST APIs`.

Three things this deliberately does **not** add:

- **Prose the parser mistook for a skill name.** "General-purpose programming
  language", "HTTP/APIs/client-server architecture", "Java/Python/C++/C#/Go/
  Rust/TypeScript (at least one)", "performance-critical software". These are
  sentences, not skills, and seeding them would make the catalogue agree with a
  parser defect. That is the open half of DEV-055.
- **Chip-design internals** — AXI, UCIe, DDR, PCIe, Lint/CDC tools. They came
  from one posting outside the product's audience, and adding them would not
  change a single verdict: a skill nobody holds scores the same resolved or
  not. ARM is in because embedded software work names it.
- **Composite names.** `Linux/Unix`, `MongoDB/SQL`, `React/Next.js/React Native`
  are handled by the matcher splitting them, which is where "either of these"
  belongs. Seeding them as skills would bake a posting's punctuation into a
  shared table.

Revision ID: f2a91c47d8e3
Revises: a71f3d0c5e84
Create Date: 2026-08-15
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a91c47d8e3"
down_revision: str | None = "a71f3d0c5e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")


def _normalize(raw: str) -> str:
    """Mirrors ``jip_api.domain.career.skills.normalize_skill_name``.

    Duplicated on purpose, for the reason the first seed gives: a migration has
    to keep producing the rows it produced when it first ran, even if the
    application's rule later changes.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip().replace(" ", "-")


# (canonical name, category, [aliases])
SEED: list[tuple[str, str, list[str]]] = [
    # --- the web fundamentals the catalogue did not know -------------------
    #
    # Nobody lists HTML beside React on a CV, which is exactly why a posting
    # asking for it must resolve: the gap it produces is against an assumption,
    # not against a fact.
    ("HTML", "LANGUAGE", ["HTML5"]),
    ("CSS", "LANGUAGE", ["CSS3", "SCSS", "Sass"]),
    ("JSON", "TOOL", []),
    ("Web Services", "DOMAIN", ["Webservices"]),
    # --- Python data and ML, absent while the eval fixtures assume them -----
    ("NumPy", "FRAMEWORK", ["Numpy"]),
    ("Pandas", "FRAMEWORK", []),
    ("Scikit-learn", "FRAMEWORK", ["sklearn", "scikit learn", "SciKit-Learn"]),
    ("SciPy", "FRAMEWORK", []),
    ("Matplotlib", "FRAMEWORK", []),
    ("Hugging Face", "PLATFORM", ["HuggingFace", "Transformers library"]),
    ("ONNX", "TOOL", []),
    # --- current AI vocabulary ---------------------------------------------
    #
    # These date faster than the rest of the catalogue. Included because seven
    # postings in one week named five of them, and a catalogue that lags the
    # market it reads is the failure this file exists to fix.
    ("Transformers", "PRACTICE", ["Transformer models"]),
    ("Autoencoders", "PRACTICE", []),
    ("Reinforcement Learning", "PRACTICE", ["RL", "Deep Reinforcement Learning", "DRL"]),
    ("Prompt Engineering", "PRACTICE", []),
    ("RAG", "PRACTICE", ["Retrieval-Augmented Generation", "Retrieval Augmented Generation"]),
    ("LLM", "PRACTICE", ["Large Language Models", "LLMs"]),
    ("Formal Verification", "PRACTICE", ["Assertion-based verification"]),
    # --- test automation, an entire discipline that was missing ------------
    ("Selenium", "TOOL", ["Selenium WebDriver"]),
    ("Cypress", "TOOL", []),
    ("Playwright", "TOOL", []),
    ("Appium", "TOOL", []),
    ("JUnit", "FRAMEWORK", []),
    ("TestNG", "FRAMEWORK", []),
    ("Jest", "FRAMEWORK", []),
    ("Pytest", "FRAMEWORK", ["py.test"]),
    ("QA Automation", "PRACTICE", ["Test automation", "Automated testing"]),
    # --- and the ones whose absence was hardest to justify -----------------
    #
    # The catalogue held GitLab and GitHub Actions and not GitHub, so
    # `GitHub/GitLab` resolved to neither half of itself even after the matcher
    # learned to split it.
    ("GitHub", "TOOL", ["Github"]),
    ("React Native", "FRAMEWORK", ["ReactNative"]),
    ("ARM", "PLATFORM", ["ARM processors", "ARM architecture"]),
]

# (alias, existing canonical name it belongs to)
#
# `REST APIs` was seeded with no aliases at all, so every posting writing
# "RESTful API" — the more common phrasing — missed a skill the catalogue
# already held.
COMPOUND_ALIASES: list[tuple[str, str]] = [
    ("RESTful API", "REST APIs"),
    ("RESTful APIs", "REST APIs"),
    ("REST API", "REST APIs"),
    ("RESTful services", "REST APIs"),
    # `Unix` is deliberately absent. It is already a canonical skill of its own
    # (seeded by `c4d7e1f9ab32`), so aliasing it here put the same normalized
    # name on both sides of the catalogue — and resolution checks canonical
    # names and aliases separately, so the answer would have depended on which
    # lookup ran first. `test_no_alias_shadows_a_canonical_name` exists for
    # exactly this and caught it.
    #
    # Removing it is also the right answer on the merits: Linux is Unix-*like*,
    # not Unix, and folding one into the other would tell a user who wrote
    # "Unix" that they hold Linux. If the two should count toward each other
    # that belongs in `transferable.py`, which has no OS group yet and is not
    # this migration's decision to make.
    ("Linux/Unix", "Linux"),
    ("OOP", "Object-Oriented Design"),
    ("Object-oriented programming", "Object-Oriented Design"),
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
            # An alias must never equal its own canonical name, or resolution
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

    for alias, canonical in COMPOUND_ALIASES:
        # Skipped rather than failing when the target is absent. This runs on
        # databases seeded by different migrations in different orders, and a
        # missing alias is a smaller problem than a migration that will not
        # apply.
        skill_id = connection.execute(
            sa.text("SELECT id FROM skills WHERE normalized_name = :normalized"),
            {"normalized": _normalize(canonical)},
        ).scalar_one_or_none()
        if skill_id is None:
            continue

        normalized_alias = _normalize(alias)
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
    """Remove only what this added, and only where nothing points at it.

    A skill the user has since claimed, or a requirement has resolved to, is no
    longer this migration's to delete — the row is now somebody's data. Leaving
    it is the safer failure.
    """
    connection = op.get_bind()

    for alias, _canonical in COMPOUND_ALIASES:
        connection.execute(
            sa.text("DELETE FROM skill_aliases WHERE normalized_alias = :normalized"),
            {"normalized": _normalize(alias)},
        )

    for canonical, _category, aliases in SEED:
        normalized = _normalize(canonical)
        for alias in aliases:
            connection.execute(
                sa.text("DELETE FROM skill_aliases WHERE normalized_alias = :normalized"),
                {"normalized": _normalize(alias)},
            )
        connection.execute(
            sa.text(
                """
                DELETE FROM skills s
                WHERE s.normalized_name = :normalized
                  AND NOT EXISTS (SELECT 1 FROM user_skills u WHERE u.skill_id = s.id)
                  AND NOT EXISTS (SELECT 1 FROM job_requirements r WHERE r.skill_id = s.id)
                  AND NOT EXISTS (SELECT 1 FROM skill_aliases a WHERE a.skill_id = s.id)
                """
            ),
            {"normalized": normalized},
        )
