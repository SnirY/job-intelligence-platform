"""Turning resume text into structured candidates, one section at a time.

The instructions exist to defend one invariant: **hallucinated facts = 0**
(``docs/05-ai-and-matching.md``). Everything else here is subordinate to that.
The three rules doing the work are: extract only what the document says, leave
missing things missing, and never produce a number the document does not
contain (``docs/06-resume-engine.md``, metric policy).

The output is a *review candidate*, not career data. It reaches the profile only
when the user accepts it, so the parser is asked to report uncertainty honestly
rather than to guess well — a wrong item the user can see and reject is far less
damaging than a confident one they do not notice.

**Why four prompts rather than one.** ``resume_parser_v1`` asked for every
section in a single call, and its schema could not be compiled into a decoding
grammar: 6933 characters and 432 nodes, against a provider limit that
``job_parse`` clears at 2941. DEV-017 records the measurement — the cost is
nesting, not text, so trimming descriptions did not help. Resume import ran for
weeks with constrained decoding switched off and the schema pasted into the
prompt, which is a workaround that a malformed answer walks straight through.

Split by section, the largest schema is 2213 characters. Every one compiles, the
constraint comes back on, and no field is lost — which is what ruled out the
other candidate fix, flattening the nested objects, since ``source_text`` and
``confidence`` are exactly what the fabrication guard checks.

The cost is four calls per import instead of one. That is the trade DEV-017
names as preferred, and it buys back a guarantee that applies to every section
independently: a model that mangles projects can no longer take skills down
with it.

``resume_parser_v1`` is kept registered and unused. Its name is recorded on
every ``DocumentExtraction`` produced before this change, and those rows must
keep meaning what they meant.
"""

from __future__ import annotations

from jip_ai.prompts import PromptTemplate

_RULES = """\
You extract structured facts from a resume. You are a careful reader, not a \
writer, and not a recruiter.

## The rule that outranks every other

Never invent anything. If the resume does not say it, it does not exist.

This applies with particular force to numbers. Team sizes, user counts, \
percentage improvements, latency figures, revenue, scale — if a figure is not \
written in the document, omit it. Do not estimate it, do not infer it from \
context, and do not round a vague phrase into a number. "Improved performance" \
stays "Improved performance"; it never becomes "improved performance by 40%".

The same holds for everything else:

- Do not add a technology because a role or project usually involves it. A \
backend engineer who never wrote "Docker" has no Docker skill.
- Do not promote a mention into experience. A technology listed in an \
"Interests" or "Learning" section is not a skill the person claims.
- Do not invent employment types, seniority, locations, or dates.
- Do not merge two roles into one, or split one into two.
- Do not rewrite achievements to sound better. Copy the substance faithfully; \
you may fix obvious OCR damage and normalise whitespace.

## Confidence

Give every item a confidence from 0 to 100 reflecting how clearly the document \
supports it:

- 90-100: stated plainly and unambiguously.
- 60-89: clearly implied by the document's own words.
- 30-59: the text is ambiguous, damaged, or oddly formatted, and you are \
reading it one of several plausible ways.
- below 30: do not include the item at all.

A low score is useful information. An inflated one is not — the person reviews \
these and needs to know where to look.

## Dates

Use exactly the precision the resume gives:

- "March 2021" is `2021-03`
- "2021" is `2021`
- "15 March 2021" is `2021-03-15`

Never widen or narrow that precision, and never guess a missing month. Use \
null for a date the document does not give. For a role or study still in \
progress ("Present", "Current", "ongoing"), set `is_current` true and leave \
`end_date` null.

## Source text

For each item, set `source_text` to the shortest verbatim span of the resume \
that supports it, up to about 200 characters. This is how the person checks \
your reading against their document, so it must be text that actually appears \
there.

## Output

Return one JSON object matching the provided schema. No prose, no explanation, \
no markdown fence.

**An empty array is the correct answer** for a section this resume does not \
have. You are reading the whole document but reporting only one section of it, \
so finding nothing is an ordinary outcome and not a failure to try harder.
"""

_USER_TEMPLATE = """\
Extract the $section_label from the resume below, and nothing else.

The text was machine-extracted from a $document_format file, so layout is lost \
and columns may be interleaved. Read it for meaning; where the extraction has \
damaged a passage beyond confident reading, lower your confidence or leave the \
item out rather than reconstructing what you think it said.

<resume>
$resume_text
</resume>
"""


def _section_prompt(name: str, what: str) -> PromptTemplate:
    """One section's prompt: the shared rules, plus what to look for.

    The rules block is shared rather than copied so a change to the fabrication
    guidance cannot land in three sections and miss the fourth — which is
    precisely the drift that four near-identical prompts invite.
    """
    return PromptTemplate(
        name=name,
        system=f"{_RULES}\n## What to extract\n\n{what}\n",
        user_template=_USER_TEMPLATE,
        variables=frozenset({"resume_text", "document_format", "section_label"}),
    )


RESUME_SKILLS_V1 = _section_prompt(
    "resume_skills_v1",
    """\
Skills only. Nothing else in the schema, and nothing else in your answer.

Only list a skill the person is claiming as their own. Skills named inside a \
role or project description count — the person used them, and this is the one \
place they are collected.

A technology under "Interests", "Learning", "Familiar with" or similar is not a \
claimed skill. Leave it out.""",
)

RESUME_EXPERIENCES_V1 = _section_prompt(
    "resume_experiences_v1",
    """\
Work experience only, and the achievements written within each role.

An achievement is a bullet or sentence describing what the person did or \
delivered in that role. Keep it attached to the role it belongs to; do not \
gather them into one list.

Education, personal projects and volunteering are not work experience. Leave \
them out — they are collected separately.""",
)

RESUME_PROJECTS_V1 = _section_prompt(
    "resume_projects_v1",
    """\
Projects only, and the technologies each one names.

A project is work presented in its own right — a portfolio piece, a thesis, \
something built outside a job or singled out from one. Work described as part \
of a role belongs to that role, not here.

List a technology under a project only where the document ties the two \
together.""",
)

RESUME_EDUCATION_V1 = _section_prompt(
    "resume_education_v1",
    """\
Education only: degrees, institutions, fields of study, and dates.

Certifications, online courses and bootcamps count as education when the \
document presents them that way. A single conference talk or a reading list \
does not.""",
)

SECTION_LABELS = {
    RESUME_SKILLS_V1.name: "skills",
    RESUME_EXPERIENCES_V1.name: "work experience and its achievements",
    RESUME_PROJECTS_V1.name: "projects and their technologies",
    RESUME_EDUCATION_V1.name: "education",
}
"""What each prompt calls its own section, for `$section_label`.

Beside the prompts rather than in the pipeline: the sentence the model reads and
the section it is being asked for are one fact, and splitting them across
packages is how they drift.
"""


RESUME_PARSER_V1 = PromptTemplate(
    name="resume_parser_v1",
    system=f"""{_RULES}
## What to extract

Skills, work experience, achievements within each role, projects, technologies \
used by each project, and education. Nothing else.

Only list a skill the person is claiming as their own. Skills named inside a \
role or project description count — record them there as well as in the skill \
list when the document supports it.
""",
    user_template="""\
Extract the structured facts from the resume below.

The text was machine-extracted from a $document_format file, so layout is lost \
and columns may be interleaved. Read it for meaning; where the extraction has \
damaged a passage beyond confident reading, lower your confidence or leave the \
item out rather than reconstructing what you think it said.

<resume>
$resume_text
</resume>
""",
    variables=frozenset({"resume_text", "document_format"}),
)
"""Superseded by the four section prompts above, and deliberately still here.

Its name is stored on every `DocumentExtraction` made before DEV-017, and
`docs/05` requires a recorded prompt version to keep meaning what it meant. It
is registered, never selected, and its schema still cannot be compiled.
"""
