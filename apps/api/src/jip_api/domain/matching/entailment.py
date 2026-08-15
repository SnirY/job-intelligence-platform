"""Skills that are implied by other skills, and by a degree.

DEV-064. Four postings in ten reported a gap in something the profile plainly
has, because nobody writes it down:

| Posting | Reported as absent |
|---|---|
| 5 | Object-oriented programming |
| 6 | Data structures |
| 7 | HTML, CSS |
| 8 | Object-oriented programming, data structures, algorithms |

Every one is mechanically correct — the skill resolved, the profile is silent —
and every one is a gap against an assumption rather than against a fact. Posting
8 carried three at once and scored 33%, seventeen points below the human
reading and the second-lowest in the set.

**This is entailment, not similarity, and it is not transferability.** React is
not *like* HTML; React cannot be written without it. A Software Engineering
degree does not *resemble* a data structures course; it contains one.

Which is why this is a separate table from `transferable.py`. That module
answers "would this experience carry over" and returns TRANSFERABLE_MATCH. This
one answers "does holding that mean holding this", and the answer is stronger —
but it is still an inference the user has not made themselves, so the caller
reports PARTIAL_MATCH and names where it came from.

**Deliberately small, and every entry defensible out loud.** The test is not
"are these related" but "could someone hold the first and genuinely not have
the second". Where the answer is yes, it does not belong here.
"""

from __future__ import annotations

# skill -> the held skills that imply it
#
# Read as: anyone who has written React has written HTML. Not "React is a bit
# like HTML", which would be false and belongs nowhere.
IMPLIED_BY_SKILL: dict[str, frozenset[str]] = {
    "html": frozenset({"react", "angular", "vue.js", "next.js", "svelte", "css"}),
    "css": frozenset({"react", "angular", "vue.js", "next.js", "svelte", "tailwind css"}),
    "object-oriented design": frozenset({"java", "c#", "c++", "kotlin", "scala", "swift"}),
    "rest apis": frozenset({"fastapi", "django", "flask", "express.js", "spring boot", ".net"}),
    "git": frozenset({"github", "gitlab", "github actions"}),
    "sql": frozenset({"postgresql", "mysql", "sqlite", "microsoft sql server", "oracle database"}),
}
"""What one skill guarantees about another.

`object-oriented design` lists the strongly object-oriented languages only.
Python and JavaScript are multi-paradigm and someone can write a great deal of
either without designing a class hierarchy, so they are **out** — that is the
"could they genuinely not have it" test doing its job.

`css` implies `html` and not the reverse: styling something means there was
something to style, while plenty of HTML is written without a stylesheet.
"""

# skill -> the fields of study whose degree contains it
IMPLIED_BY_DEGREE: dict[str, frozenset[str]] = {
    "data structures": frozenset(
        {"computer science", "software engineering", "computer engineering", "computer sciences"}
    ),
    "algorithms": frozenset(
        {"computer science", "software engineering", "computer engineering", "computer sciences"}
    ),
    "object-oriented design": frozenset(
        {"computer science", "software engineering", "computer engineering", "computer sciences"}
    ),
}
"""What a degree in a field guarantees.

Three entries, and each is a course every accredited curriculum in those fields
contains. Nothing here is inferred from a job title, a project, or a length of
service — only from a qualification the user recorded and a person awarded.

`docs/05-ai-and-matching.md` is careful about inference, and this is the shape
it warns about: concluding a skill from something that is not that skill. Two
things keep it honest. The table is hand-written and auditable rather than
produced by a model, and the caller must say which held item did the implying,
so the reader can disagree with the specific claim rather than with a verdict.

Information systems and information technology are **out**, though `education.py`
groups them with computer science for degree-equivalence. Answering "do you have
a relevant degree" is a lower bar than "did your degree teach you algorithms",
and the two questions deserve different tables.
"""


def implied_by(required: str, held_skills: list[str], fields_of_study: list[str]) -> str | None:
    """What the profile holds that guarantees ``required``, if anything.

    Returns the held skill or field of study that implies it — never a bare
    ``True`` — because the caller has to name it. A verdict reading "you have
    this" is an assertion; "your React implies it, though you have not listed
    it" is an argument the reader can reject.

    Skills are checked before degrees: a demonstrated tool is better evidence
    than a curriculum, and produces a more convincing sentence.
    """
    target = required.strip().casefold()

    implying_skills = IMPLIED_BY_SKILL.get(target)
    if implying_skills:
        for held in held_skills:
            if held.strip().casefold() in implying_skills:
                return held

    implying_fields = IMPLIED_BY_DEGREE.get(target)
    if implying_fields:
        for field in fields_of_study:
            if field.strip().casefold() in implying_fields:
                return field

    return None
