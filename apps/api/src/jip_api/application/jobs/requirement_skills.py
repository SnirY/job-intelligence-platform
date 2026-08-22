"""Resolving a technology named in a posting to a canonical skill.

``docs/05-ai-and-matching.md`` defines the path: raw skill → alias lookup →
canonical skill. This module implements it for job requirements, and the one
thing it deliberately does **not** do is create canonical skills.

## Why job requirements do not extend the catalogue

:func:`jip_api.application.career.skills.resolve_skill` creates a canonical
skill when it finds none, and that is right for its caller: a person typing
"Rust" into their profile is asserting that Rust is a skill, and they will see
the result immediately and correct it.

A job requirement is different in every way that matters. The name came from a
model reading someone else's prose, nobody reviews it, and there are as many
requirements as there are postings. Letting that path write to a table shared by
every user would mean the catalogue accumulates "Rust (advantageous)",
"strong Rust", "Rust/Go", and "RUST" — the "uncontrolled duplicate strings" the
goal names, and each one a skill that will never match anything again.

## The documented rule

An unknown technology is recorded on the requirement in two forms: ``skill_name``
as the posting wrote it, and nothing in ``skill_id``. That is a complete,
queryable record — it is exactly what a later reviewed-candidate mechanism would
read from — and it costs the catalogue nothing.

Three ways a canonical skill still comes into existence, all of them through a
human:

1. The user adds the skill to their own profile by hand.
2. The user accepts a skill candidate in the resume review screen.
3. A seed migration adds it, as ``b71c4a90d2e5`` did for the common cases.

So a job asking for something nobody has ever claimed resolves to nothing today,
and starts resolving the moment any user claims it. That is the correct
direction: the catalogue grows from asserted facts, not from postings.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.domain.career.skills import Skill, SkillAlias, normalize_skill_name

logger = logging.getLogger(__name__)

_TRAILING_NOISE = re.compile(
    r"\s*[\(\[].*?[\)\]]\s*$"  # "Rust (advantageous)"
    r"|\s+(?:experience|skills?|knowledge|proficiency)$",
    re.IGNORECASE,
)
_LEADING_NOISE = re.compile(
    r"^(?:strong|solid|deep|excellent|good|basic|advanced|expert|hands[- ]on|"
    r"working|proven|extensive|some)\s+",
    re.IGNORECASE,
)


def clean_skill_name(raw: str) -> str:
    """Strip the qualifiers postings wrap around a technology's name.

    "Strong Kubernetes experience" and "Kubernetes (a plus)" both name
    Kubernetes. Cleaning is limited to affixes that are unambiguously not part
    of a name — it never touches the middle of the string, because "Node.js"
    and "C++" are names and a cleverer rule would break them.

    Returns the input stripped when nothing matched, so a name that is already
    clean passes through untouched.
    """
    cleaned = raw.strip()
    for _ in range(3):
        # Bounded rather than while-True: "strong solid deep Rust" is not real
        # input, and an unbounded loop on a pathological string is a worse bug
        # than an incompletely cleaned name.
        before = cleaned
        cleaned = _TRAILING_NOISE.sub("", cleaned).strip()
        cleaned = _LEADING_NOISE.sub("", cleaned).strip()
        if cleaned == before:
            break
    return cleaned or raw.strip()


ALTERNATIVE_SEPARATORS = re.compile(
    r"\s*/\s*|\s+(?:or|and/or)\s+",
    re.IGNORECASE,
)
"""What separates one offered skill from another.

A slash with optional spaces, or the words "or" / "and/or" **surrounded by
spaces**. The spaces are load-bearing: without them this splits `Fortran` into
`F` and `tran`, and `Terraform` into `Terraf` and `m`.
"""


def alternatives(name: str) -> list[str]:
    """The separate skills a composite requirement name offers.

    `Linux/Unix` is two, `C/C++` is two, `Node.js` is one — the split is on
    separators between words, and a dot inside a name is not one.

    Returns nothing for a name with no separator, so the ordinary case does no
    extra work and cannot be changed by this at all.

    Length-guarded: a requirement whose "skill name" is a whole sentence — "at
    least one programming or scripting language (e.g. Python, Go, Bash)" — is
    not repairable by splitting, and pretending otherwise would produce
    fragments that match nothing. That case needs the parse schema to carry a
    list, which is the other half of DEV-055 and is still open.

    Lives here rather than in the matcher because two callers need it and they
    ask different questions of it. The matcher asks "which of these does the
    profile hold". The candidate queue asks "does the catalogue already know all
    of them", which is how `GitHub/GitLab` stopped being proposed as a missing
    entry when both halves had been in the catalogue the whole time.
    """
    if len(name) > 40:
        return []
    parts = [part.strip() for part in ALTERNATIVE_SEPARATORS.split(name)]
    return [part for part in parts if part and part != name]


def resolve_known_skills(session: Session, names: list[str]) -> dict[str, Skill]:
    """Map each name to a canonical skill, where one already exists.

    Batched: a posting can name thirty technologies, and resolving them one at a
    time would be thirty round trips per analysis. Returns a dict keyed by the
    **original** name so the caller does not have to re-clean anything.

    Names with no canonical skill are simply absent from the result. That is a
    normal outcome, not an error — see this module's docstring.
    """
    normalized: dict[str, str] = {}
    for name in names:
        key = normalize_skill_name(clean_skill_name(name))
        if key:
            normalized[name] = key

    if not normalized:
        return {}

    keys = set(normalized.values())

    by_key: dict[str, Skill] = {}
    for skill in session.execute(select(Skill).where(Skill.normalized_name.in_(keys))).scalars():
        by_key[skill.normalized_name] = skill

    # Aliases second, and only for what the canonical names did not answer: a
    # name that is both a canonical skill and someone's alias must resolve to
    # the canonical one, or resolution would depend on query order.
    unresolved = keys - set(by_key)
    if unresolved:
        rows = session.execute(
            select(SkillAlias.normalized_alias, Skill)
            .join(Skill, Skill.id == SkillAlias.skill_id)
            .where(SkillAlias.normalized_alias.in_(unresolved))
        )
        for alias_key, skill in rows:
            by_key[alias_key] = skill

    resolved = {name: by_key[key] for name, key in normalized.items() if key in by_key}

    missing = len(normalized) - len(resolved)
    if missing:
        logger.info(
            "Job requirements named skills not in the catalogue",
            extra={"unresolved": missing, "resolved": len(resolved)},
        )
    return resolved
