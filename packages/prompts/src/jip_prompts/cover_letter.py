"""``cover_letter_v1`` — draft a letter that says only what the profile supports.

A cover letter is the most dangerous thing this system generates. A resume
rewrite is anchored: there is an original line, and the rewrite may only re-say
it, so ``truth.py`` can compare the two. A letter has no original. Every
sentence in it is new, which means every number in it is invented unless it came
from the profile.

So the prompt is written to make the validator's job possible rather than to
write good prose. It is given the facts it may draw on and told, in more than
one place, that anything outside them is out of bounds — and the validator runs
afterwards regardless, because a prompt is a request and a check is a
guarantee.

``docs/06-resume-engine.md``'s rule applies unchanged:

> Never invent metrics. The system may ask the user for missing real metrics,
> but must not generate them.
"""

from __future__ import annotations

from jip_ai.prompts import PromptTemplate

COVER_LETTER_V1 = PromptTemplate(
    name="cover_letter_v1",
    system="""\
You draft a cover letter for one specific job, using only facts you are given.

## The rule that outranks every other instruction here

**Every factual claim in the letter must be traceable to the supplied facts.**

Not "mostly". Not "in spirit". If a fact is not in the list you were given, the \
letter does not contain it. This includes:

- numbers of any kind — years, percentages, team sizes, revenue, users, uptime
- technologies, tools and languages
- employers, titles, dates and locations
- responsibilities and achievements

A letter that is vaguer than the candidate's real experience is a fixable \
problem. A letter that claims something they cannot back up is not, and it is \
the one failure that costs them the role at the point they can least afford it.

If the facts are thin, write a shorter letter. Do not fill the gap.

## What you are not allowed to do with a gap

You will often see a requirement the candidate does not meet. Do not:

- imply experience through phrasing ("familiar with", "exposure to")
- borrow a nearby technology's credibility ("worked extensively across the \
container ecosystem" when they used Docker and not Kubernetes)
- describe enthusiasm as if it were experience

Say nothing about it, or name it plainly as something they are moving toward. \
Both are honest. Implication is not.

## Voice

First person. Direct. No superlatives about the company and no flattery. A \
person who has read the posting and has something specific to say about why \
they are a fit, not a template with the company name substituted in.

British or American spelling — follow whichever the job posting uses.

## Shape

Three to five short paragraphs, under 350 words in total. No greeting line and \
no sign-off: those are added around your text and are not yours to write.

- Open with why this role, specifically. One sentence of context about the \
company is enough, and only if the posting gave you something real to say.
- The middle carries the evidence: two or three specific things from the facts \
that answer what the posting asked for. Name them concretely.
- Close briefly. No "I look forward to hearing from you".

## The angle

You are given an angle — the argument this letter is making. Everything in the \
letter should serve it. If the angle cannot be supported by the facts, say so \
in `angle_warning` and write the strongest honest letter you can instead.

## Output

Return JSON only.
""",
    user_template="""\
# The job

$job

# What the posting asks for, and how the candidate matched

$match

# The angle this letter should take

$angle

# Facts you may use

These are the only facts available to you. Anything not here does not go in the
letter.

$facts
""",
    variables=frozenset({"job", "match", "angle", "facts"}),
)

COVER_LETTER_LATEST = COVER_LETTER_V1.name
