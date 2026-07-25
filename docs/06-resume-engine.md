# Resume Engine & Career Profile Intelligence

## Core concept

```text
Career Profile = Source of Truth
Resume = Selected Representation
```

The system should not repeatedly reconstruct the user from a PDF.

## Master Career Profile

The profile can contain much more information than any single resume:

- skills
- experience
- projects
- education
- certifications
- achievements
- research
- open-source work
- evidence
- verified statements

## Verified facts

Only verified or explicitly confirmed facts can be used automatically in final resume claims.

Sources may include:

- user confirmation
- project data
- experience data
- repository evidence
- imported resume
- other documents

## Explicit skills vs inferred capabilities

Example:

```text
Explicit skill: FastAPI
Inferred capability: REST API Development
```

The system may use inferred capability for matching but must not pretend the user owns a technology they never used.

## Resume hierarchy

```text
Master Resume
↓
Base Resume
↓
Job-Specific Resume
```

Examples of base resumes:

- General Software Engineer
- Backend Developer
- AI / Computer Vision
- Full Stack

## Resume lineage

Every job-specific version should preserve its parent version.

Used resume versions should be immutable.

## Structured resume

Store resume content as structured sections and items, not only as a PDF blob.

Sections may include:

- header
- summary
- skills
- experience
- projects
- education
- certifications

Resume items should reference source entities where possible.

## Approved statement library

Statements previously approved by the user can become reusable verified variants.

Support variants such as:

- concise
- technical
- backend-focused
- AI-focused
- general

## Resume strategy

Before rewriting, generate a strategy that answers:

- what to emphasize
- what to reduce
- what to reorder
- which projects to prioritize
- which evidence is missing from the resume
- which real career gaps remain

## Resume constraints

Possible user preferences:

- maximum pages
- language
- preferred style
- whether to include summary
- project count
- bullet count

MVP defaults:

- 1 page preferred
- 2 pages allowed
- no unsupported claims

## Content selection

Rank resume content by:

- job requirement coverage
- skill relevance
- role relevance
- evidence strength
- uniqueness
- value per line

The objective is:

> Maximize relevant, truthful evidence within limited resume space.

## Project selection

Rank projects by:

- skill overlap
- role relevance
- technical depth
- evidence strength
- freshness
- uniqueness

Do not assume Experience always outranks Projects for junior users.

## Skill section

Only verified skills may be included.

Order skills by relevance and evidence strength.

## Keyword alignment

Equivalent terminology can be aligned with the job description when truthful.

Do not inflate meaning.

## Summary generation

Summaries must be:

- truthful
- specific
- short
- relevant

Avoid generic filler.

## Rewrite pipeline

```text
Original Statement
↓
Source Facts
↓
Job Context
↓
Rewrite Candidate
↓
Claim Extraction
↓
Truth Validation
↓
Style Validation
↓
User Review
```

## Metric policy

Never invent metrics.

The system may ask the user for missing real metrics, but must not generate them.

## Suggestion risk

```text
LOW
MEDIUM
HIGH
```

Low risk:

- grammar
- shortening
- reordering
- equivalent terminology

High risk:

- new technology
- new responsibility
- new scale
- new achievement

## Diff review

Every suggestion supports:

- Accept
- Reject
- Edit
- Generate alternative

Medium/high-risk suggestions require review.

## Career gap vs resume gap

### Career gap

The user genuinely lacks evidence.

### Resume gap

Evidence exists but is not visible in the selected resume.

The system must distinguish these.

## Resume generation

```text
Structured Resume Content
+
Template
=
Rendered Resume
```

Keep content and design separate.

## MVP templates

Start with one excellent ATS-friendly template before adding more.

Possible later templates:

- Modern Single Column
- Compact Technical

## Layout validation

Do not solve overflow by shrinking text to unreadable sizes.

Prefer:

- shortening low-value content
- removing low-relevance content
- reducing unnecessary detail

## Resume quality checks

Before finalization:

- truth check
- spelling
- duplicate content
- keyword relevance
- page length
- contact information

## Usage tracking

Applications must reference the exact resume version sent.

Later analytics may show outcome associations, but never claim causation without evidence.

## Progressive profile enrichment

The system should ask targeted questions only when useful.

Do not create a 100-question onboarding process.

## Rejected-assumption memory

When the user rejects an inferred claim, preserve that correction so the system does not repeat the same mistake.

## MVP scope

Implement:

- resume upload
- parsing
- review
- career-profile creation
- master resume
- base resume
- job-specific resume
- strategy
- content prioritization
- rewrite suggestions
- truth validation
- diff review
- PDF export
