"""Whether a qualification answers what a posting asked for.

DEV-060. `_match_education` compared a requirement to an education row by
counting shared words, and a **B.Sc. in Software Engineering** shares no word
with **"Bachelor's degree in Computer Science"**. The verdict was GAP, and
because such requirements are usually CORE, a BLOCKER — the strongest negative
signal the engine has, aimed at a qualification the user holds.

Two separate pieces of knowledge are needed and neither existed:

- **`B.Sc.` means Bachelor's degree.** An abbreviation, not a synonym, and there
  are only a handful that matter.
- **Software Engineering is not Computer Science, and answers a posting that
  asked for one.** The same relationship `transferable.py` already encodes for
  skills, which is why this file reads like it.

Deliberately small. This is not an ontology of higher education; it is the set
of equivalences that a software job posting actually relies on, and every entry
should be one somebody would defend out loud.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z.+#]+")

# Ordered, because a posting asking for a Bachelor's is answered by a Master's
# and not the other way round.
BACHELOR, MASTER, DOCTORATE = 1, 2, 3

DEGREE_LEVELS: dict[str, int] = {
    "bachelor": BACHELOR,
    "bachelors": BACHELOR,
    "b.sc.": BACHELOR,
    "b.sc": BACHELOR,
    "bsc": BACHELOR,
    "b.s.": BACHELOR,
    "b.a.": BACHELOR,
    "ba": BACHELOR,
    "b.eng.": BACHELOR,
    "beng": BACHELOR,
    "undergraduate": BACHELOR,
    "master": MASTER,
    "masters": MASTER,
    "m.sc.": MASTER,
    "m.sc": MASTER,
    "msc": MASTER,
    "m.s.": MASTER,
    "m.eng.": MASTER,
    "meng": MASTER,
    "mba": MASTER,
    "graduate": MASTER,
    "phd": DOCTORATE,
    "ph.d.": DOCTORATE,
    "doctorate": DOCTORATE,
    "doctoral": DOCTORATE,
}
"""Spellings that name a degree level.

`bs` and `ms` are deliberately absent: both are common English words in other
senses, and a false degree match is worse than a missed one here — it would
claim a qualification the user may not have.
"""

FIELD_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "computer science",
            "software engineering",
            "computer engineering",
            "information systems",
            "information technology",
            "computer sciences",
            "software development",
            "electrical engineering",
            "electronics engineering",
            "data science",
        }
    ),
)
"""Fields a software posting treats as answering each other.

One group, and it is not a claim that these degrees are the same. It is a claim
that **a posting asking for one of them is answered by another**, which is the
only question this module is asked. `docs/05-ai-and-matching.md` requires that
similarity never be reported as equivalence, and the caller honours that by
returning MATCH rather than STRONG_MATCH and by naming both sides.

Electrical and electronics engineering are in because Israeli software postings
routinely list them beside computer science. Data science is in for the same
reason. Mathematics and physics are **out**: they are common alternatives in
research postings and are a different enough training that including them would
start claiming things the user would not claim themselves.
"""


def degree_level(text: str) -> int | None:
    """The highest degree level named in ``text``, if any."""
    levels = [
        DEGREE_LEVELS[word] for word in _WORD.findall(text.casefold()) if word in DEGREE_LEVELS
    ]
    return max(levels) if levels else None


def fields_in(text: str) -> set[str]:
    """Every known field named in ``text``.

    Matched as phrases against the whole string rather than word by word, so
    "computer science" is one field and not two loose words that would also fire
    on "computer" alone.
    """
    lowered = text.casefold()
    return {field for group in FIELD_GROUPS for field in group if field in lowered}


def same_group(left: str, right: str) -> bool:
    """Whether two fields sit in the same group."""
    return any(left in group and right in group for group in FIELD_GROUPS)


_SUBJECT_AFTER = re.compile(r"\b(?:in|of)\s+([a-z][a-z\s&]{2,40})")

_NOT_A_SUBJECT = frozenset(
    {
        "a",
        "an",
        "the",
        "computer",
        "science",
        "engineering",
        "related",
        "relevant",
        "similar",
        "equivalent",
        "field",
        "fields",
        "discipline",
        "disciplines",
        "any",
        "some",
        "lieu",
        "addition",
        "practice",
        "depth",
        "order",
    }
)


def _names_an_unknown_field(requirement: str) -> bool:
    """Whether the requirement names a subject this module does not know.

    Distinguishes "Bachelor's degree" — answerable by any Bachelor's — from
    "Bachelor's degree in Law", which this module has no opinion about and must
    not pretend to.

    The filtered words are the ones that follow "in" without naming a subject:
    "in a related field", "in lieu of", "in depth". A requirement whose only
    such phrase is one of those has named no subject.
    """
    lowered = requirement.casefold()
    for match in _SUBJECT_AFTER.finditer(lowered):
        words = [w for w in match.group(1).split() if w not in _NOT_A_SUBJECT]
        if words:
            return True
    return False


def answers(requirement: str, held_degree: str, held_field: str) -> tuple[bool, str | None]:
    """Whether a held qualification answers ``requirement``.

    Returns the verdict and, when the fields differ, the held field — so the
    explanation can name both rather than asserting a bare "covers this".

    A requirement naming no degree level and no known field is not answerable
    here, and returns ``False`` so the caller falls back to reading words.
    """
    required_level = degree_level(requirement)
    required_fields = fields_in(requirement)
    if required_level is None and not required_fields:
        return False, None

    # A Master's answers a posting asking for a Bachelor's. The reverse is not
    # true, and treating it as true would be the module claiming a
    # qualification on the user's behalf.
    held_level = degree_level(held_degree) or degree_level(held_field)
    if required_level is not None and (held_level is None or held_level < required_level):
        return False, None

    if not required_fields:
        if _names_an_unknown_field(requirement):
            # A subject was named and this module does not recognise it. "Not
            # recognised" is not "does not match": returning True here would
            # answer a Law degree with a Software Engineering one. Fall back to
            # the caller's word comparison, which at least reads the words.
            return False, None
        # A degree level was asked for and met, with no subject named at all.
        # "A Bachelor's degree" is answered by any Bachelor's.
        return True, None

    held_fields = fields_in(held_field) or fields_in(held_degree)
    if not held_fields:
        return False, None

    for held in held_fields:
        if held in required_fields:
            return True, None
        if any(same_group(held, required) for required in required_fields):
            return True, held

    return False, None
