# Domain Model & Data Model

## Design principle

Keep four data classes separate:

1. Raw source data
2. Structured extracted facts
3. Verified user facts
4. AI interpretations

AI interpretation must never overwrite raw or verified data.

## Core domains

```text
Identity
Career
Jobs
Matching
Resumes
Applications
Insights
```

## High-level relationships

```text
User
├── CareerProfile
│   ├── UserSkills ── Skills
│   ├── Experiences
│   ├── Projects
│   ├── Education
│   └── CareerPreferences
├── Resumes
│   └── ResumeVersions
├── Jobs
│   ├── JobImports
│   ├── JobRequirements
│   └── JobAnalyses
├── JobMatches
│   └── JobMatchItems
├── Applications
│   └── ApplicationEvents
└── Insights
```

## Key entities

### User

Fields include:

- id
- email
- display_name
- timezone
- locale
- timestamps

All user-owned entities must be scoped to `user_id`.

### CareerProfile

The professional source of truth.

Fields may include:

- headline
- professional_summary
- years_of_experience
- current_location
- links

### CareerPreferences

Includes:

- preferred work modes
- employment types
- locations
- salary preferences
- relocation
- excluded role types

### TargetRole

Fields:

- title
- role_family
- desired_seniority
- priority
- is_active

### Skill

Global canonical entity.

Fields:

- canonical_name
- normalized_name
- category
- description

### SkillAlias

Maps variants such as:

```text
JS → JavaScript
Postgres → PostgreSQL
React.js → React
```

### UserSkill

Fields:

- proficiency
- years
- last used
- confidence
- source type
- verification status
- notes

Verification states:

```text
UNVERIFIED
AI_INFERRED
USER_CONFIRMED
EVIDENCE_BACKED
```

### SkillEvidence

Links a user skill to:

- project
- experience
- education
- certification
- resume
- manual evidence

Built 2026-08-16 (DEV-054), having been specified here from the start and
missed by Phase 2. **The schema carries all six sources; only manual evidence
has anything writing it**, which was the source with no substitute and the
reason the issue was filed. RESUME and EDUCATION have a home and no producer;
CERTIFICATION waits on DEV-052, since there is no certification record for an
`entity_id` to address.

Two things about the table differ from the plain reading of the list above, and
both are deliberate:

**The link is a bare `entity_id`, not six foreign keys.** It addresses five
different tables depending on `source`. Five nullable columns with a check
constraint keeping four of them empty describes the same thing less clearly;
`ResumeItem.source_entity_id` already made this trade. MANUAL rows carry a note
and no entity, and a check constraint enforces exactly that split.

**`experience_skills` and `project_skills` are not folded into it.** A skill
used in a role is a property of the role. Copying it here would give one fact
two places to disagree, so the profile snapshot unions the two sources instead
and `skill_evidence` holds only what those cannot express.

### Certification

Built 2026-08-16 (DEV-052), specified here from the start as an evidence source
and never given an entity of its own. Holds:

- name, as the issuer writes it
- issuer
- issue date and expiry date, both optional
- credential id and verification URL

**A null expiry means the credential does not expire**, never that expiry is
unknown. Every layer reads it that way — matcher, API and profile screen —
because the other reading has the platform decide a certification has lapsed on
no evidence at all.

Deliberately not folded into `Education`. A credential expires and carries an
issuer reference; a degree does neither, and one table for both would leave "is
this still valid?" unanswerable for the rows where it is the entire question.

### Experience

Includes:

- company
- title
- employment type
- dates
- location
- description
- verification state

### ExperienceAchievement

Stores bullet-level reusable facts separately.

### Project

Fields:

- name
- descriptions
- type
- status
- dates
- GitHub/demo/docs links
- verification state

Project types:

```text
PERSONAL
ACADEMIC
PROFESSIONAL
OPEN_SOURCE
FREELANCE
RESEARCH
```

### ProjectSkill

Links projects to canonical skills.

### Capability

Represents broader demonstrated capabilities such as:

- backend API development
- system design
- computer vision
- database design
- cloud deployment
- research
- testing

### SourceDocument

Stores metadata for uploaded documents and extracted raw text.

### DocumentExtraction

Stores versioned AI extraction output.

Extraction does not become verified career data automatically.

### Job

Includes:

- title
- normalized title
- company
- role family
- seniority
- location
- work mode
- employment type
- source URL
- original description
- clean description
- processing status
- dates

### JobImport

Preserves original imported content and metadata.

### JobRequirement

Each requirement is stored separately with:

- original text
- normalized text
- requirement type
- importance
- explicitness
- confidence
- order

Types:

```text
TECHNICAL_SKILL
EXPERIENCE
EDUCATION
CERTIFICATION
LANGUAGE
DOMAIN_KNOWLEDGE
SOFT_SKILL
LOCATION
WORK_AUTHORIZATION
OTHER
```

`CERTIFICATION` was added 2026-08-16 (DEV-052). This document listed nine types
and, three sections above, named `certification` as an evidence source distinct
from `education` — so the list was already inconsistent with itself. The parser
prompt resolved the contradiction the wrong way, telling the model that
EDUCATION covers "degrees, fields of study, certifications", and a user holding
the credential a posting asked for was told their education did not cover it.

Importance:

```text
CORE
REQUIRED
PREFERRED
OPTIONAL
UNKNOWN
```

### JobAnalysis

Versioned AI interpretation containing:

- summary
- role family
- seniority assessment
- seniority reasoning
- domain
- structured output
- model metadata
- prompt version

### JobMatch

Versioned match result containing:

- overall score
- category scores
- recommendation
- confidence
- summary
- engine version

### JobMatchItem

Matches one exact requirement against evidence.

Statuses:

```text
STRONG_MATCH
MATCH
PARTIAL_MATCH
TRANSFERABLE_MATCH
GAP
BLOCKER
UNKNOWN
```

### JobMatchEvidence

Links a match item to evidence sources.

### Resume

Logical resume family:

```text
MASTER
BASE
JOB_SPECIFIC
```

### ResumeVersion

Immutable historical version with lineage.

Statuses:

```text
DRAFT
REVIEW
APPROVED
USED
ARCHIVED
```

### ResumeItem

Should reference source entities where possible.

### ResumeSuggestion

Types:

```text
REWRITE
REORDER
ADD_EXISTING_ITEM
REMOVE
SHORTEN
EMPHASIZE
```

Statuses:

```text
PENDING
ACCEPTED
REJECTED
EDITED
```

### Application

Separate from Job.

Stores:

- job
- resume version
- status
- applied date
- source
- notes

### ApplicationEvent

Every meaningful status change creates history.

### AIRun

Tracks:

- operation
- entity
- provider
- model
- prompt version
- input hash
- status
- latency
- token usage
- estimated cost

### ProcessingJob

Tracks async work.

Statuses:

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

## Historical data principle

Do not delete or overwrite:

- old match scores
- old resume versions
- old job analyses
- application status history

## JSONB principle

Use JSONB for flexible metadata and raw AI output.

Use structured columns for data that needs filtering, sorting, relationships, or analytics.

## Vector principle

Embeddings are retrieval aids, not truth.

Use them for:

- semantic matching
- duplicate detection
- relevant-project retrieval
- evidence retrieval

## MVP schema

Prioritize:

```text
users
career_profiles
career_preferences
skills
skill_aliases
user_skills
skill_evidence
experiences
experience_achievements
experience_skills
projects
project_skills
education
source_documents
document_extractions
jobs
job_imports
job_requirements
job_requirement_skills
job_analyses
job_matches
job_match_items
job_match_evidence
resumes
resume_versions
resume_sections
resume_items
resume_suggestions
applications
application_events
ai_runs
processing_jobs
```
