# User Flows

## Main navigation

```text
Home
Jobs
Applications
Resumes
Career Profile
Insights
Settings
```

## Flow 1 — First-time onboarding

```text
Welcome
↓
Define Career Goals
↓
Import Resume
↓
Review Extracted Profile
↓
Complete Missing Information
↓
Set Preferences
↓
Dashboard
```

The user should reach first value quickly: profile created, first job added, first match generated.

## Flow 2 — Add job

Entry points:

- Dashboard
- Jobs page
- global `+ Add Job`

Options:

- URL
- pasted description
- manual entry

### URL flow

```text
Paste URL
↓
Fetch Page
↓
Extract Main Content
↓
Duplicate Check
↓
Parse Job
↓
User Review
↓
Save & Analyze
```

Fallback:

```text
URL extraction failed
↓
Paste job description manually
```

## Flow 3 — Job processing

```text
RAW
↓
PARSING
↓
PARSED
↓
ANALYZING
↓
MATCHING
↓
READY
```

Failure states must not delete the job.

## Flow 4 — Job detail

Page structure:

- Job header
- opportunity overview
- match summary
- requirements
- evidence
- gaps
- resume strategy
- application status
- original description

## Flow 5 — Match review

```text
Job Requirements
+
Career Profile
↓
Structured Match
↓
Semantic Match
↓
Reasoning Layer
↓
Final Match Report
```

User sees:

- overall alignment
- category breakdown
- strong matches
- partial matches
- transferable matches
- gaps
- blockers
- evidence
- recommendation

## Flow 6 — Should I apply?

Possible recommendations:

```text
STRONG_APPLY
APPLY
CONSIDER
LOW_PRIORITY
PROBABLY_SKIP
```

Each recommendation includes reasons, risks, confidence, and suggested preparation.

## Flow 7 — Prepare application

```text
Select Resume Base
↓
Analyze Resume Against Job
↓
Generate Resume Strategy
↓
Review Suggestions
↓
Create Tailored Version
↓
Final Review
↓
Ready To Apply
```

## Flow 8 — Resume review

Suggestions appear as diffs:

- Accept
- Reject
- Edit
- Generate alternative

Unsupported claims are blocked or require confirmation.

## Flow 9 — Apply

```text
Resume Ready
↓
Open Application
↓
Mark As Applied
↓
Save Applied Date
↓
Save Exact Resume Version
```

## Flow 10 — Track application

Views:

- Kanban
- table

Every status change creates an event.

## Flow 11 — Rejection

Optional fields:

- stage
- known reason
- feedback

Known employer feedback and system inference must remain separate.

## Flow 12 — Profile updates

When profile evidence changes, affected job matches become stale and can be recalculated.

## Flow 13 — Insights

After enough relevant jobs:

- most requested skills
- most common career gaps
- resume gaps
- best matching role families
- application funnel
- next best actions

## Core UX rule

AI failure must never block manual usage.

The user can always preserve data, edit it, retry, and continue where practical.
