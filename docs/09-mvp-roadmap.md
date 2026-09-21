# MVP Scope, Prioritization & Development Roadmap

## Product goal

The MVP must support:

```text
Create Career Profile
↓
Add Job
↓
Understand Job
↓
Analyze Match
↓
Decide Whether To Apply
↓
Tailor Resume
↓
Export Resume
↓
Track Application
↓
See Initial Career Insights
```

## Priority levels

### P0 — Required

- authentication
- career profile
- resume import
- job management
- job intelligence
- matching engine
- resume tailoring
- PDF export
- application tracking
- dashboard

### P1 — Important after the core loop is stable

- advanced insights
- career-gap analysis
- resume-gap analysis
- role-family analysis
- job comparison
- application table view
- project-upgrade recommendations
- follow-up suggestions
- multiple base resumes
- career progress timeline

### P2 — Deferred

- automatic job discovery
- full job-board crawling
- browser extension
- email integration
- calendar integration
- auto-apply
- recruiter automation
- interview simulator
- complex multi-agent systems
- personalized ML ranking
- native mobile app

## Development strategy

Use vertical slices.

A slice should include, when relevant:

```text
Database
+
Backend
+
Business Logic
+
API
+
Frontend
+
Validation
+
Tests
```

### The slice lists below are not authoritative

They are a plan, written early, and they have been wrong twice in the same way:
shorter than the module they claim to cover.

Phase 2 names six slices against the eleven elements `docs/01` lists for the
Career Profile module. Two of the missing five were real omissions — career
preferences (DEV-035, found nine phases late) and certifications (DEV-052, found
after that). Phase 7 built all eight items on its list and never turned the
"Approved statement library" section of `docs/06` into an item at all (DEV-053).

**Before marking any phase DONE, run the phase exit protocol in
`docs/12-project-tracking.md`**: compare the phase against the specification
module it implements rather than against its own slice list, and account for
every element as built, deferred with a reason, or filed.

A phase closed against its own list can only confirm that the list was
completed. It cannot notice that the list was short.

## Phases

### Phase 0 — Project Foundation

Deliver:

- monorepo
- web
- API
- worker
- PostgreSQL
- Redis
- Docker Compose
- config
- linting
- formatting
- type checking
- testing foundations
- CI

Exit criteria:

- web runs
- API runs
- database works
- Redis works
- migrations work
- frontend calls API
- worker processes a test task
- tests run
- CI foundation works

Do not build domain features.

### Phase 1 — Authentication & Application Shell

Deliver:

- sign up
- login
- logout
- protected routes
- user scoping
- main navigation shell

### Phase 2 — Career Profile

Slices:

- profile basics
- target roles
- skills
- projects
- experience
- education

Exit criteria:

The user can manually build a complete career profile without AI.

### Phase 3 — Resume Import

```text
Upload
↓
Store
↓
Extract
↓
Parse
↓
Review
↓
Approve
↓
Update Profile
```

### Phase 4 — Job Workspace

Build:

- paste description first
- URL import second
- jobs list
- job detail
- archive

### Phase 5 — Job Intelligence

Build:

- structured parsing
- requirements
- responsibilities
- role family
- seniority
- summary

### Phase 6 — Matching Engine

Slices:

- deterministic skill match
- alias match
- evidence match
- semantic transferability
- scoring
- recommendation
- match UI

Milestone A:

```text
Career Profile
+
Job Intelligence
+
Matching
```

### Phase 7 — Resume Intelligence

Build:

- resume data model
- base resume editor
- strategy
- suggestions
- truth validation
- diff review
- job-specific version
- PDF rendering

Milestone B:

The product can move from job discovery to application-ready resume.

### Phase 8 — Application Tracker

Build:

- application creation
- status management
- Kanban
- timeline
- exact resume attachment
- notes

Milestone C:

```text
Add Job
↓
Analyze
↓
Match
↓
Tailor Resume
↓
Apply
↓
Track
```

### Phase 9 — Dashboard

Build:

- current pipeline
- top opportunities
- next best actions
- recent activity
- basic career gap

### Phase 10 — Career Insights

Build:

- skill demand
- recurring gaps
- resume gaps
- role analysis
- application funnel

MVP visualizations:

- match breakdown
- application funnel
- skill demand
- gap impact matrix

### Phase 11 — Production Hardening

Focus:

- retry flows
- failure recovery
- security
- observability
- performance
- UX polish
- accessibility

Slices:

- settings and career preferences

Settings is listed as a screen in `docs/02-user-flows.md` and
`docs/08-ui-ux.md`, and no phase ever claimed it. That omission was invisible
for eleven phases because the page renders a placeholder, which looks
deliberate.

It is not a new feature. `CareerPreferences` is defined in
`docs/03-domain-model.md`, `career_preferences` is in the MVP schema there,
`docs/01-product-requirements.md` lists career preferences inside the Career
Profile module, Flow 1 ends onboarding with "Set Preferences", and
`docs/05-ai-and-matching.md` names user preferences among the inputs a
recommendation considers. All of that was written and none of it was built —
see DEV-035.

Phase 2's slice list is where it should have been, and this is the first phase
after noticing.

Exit criteria:

Work mode, employment type, location, salary, relocation and excluded role
types are stored, editable, and read by whatever claims to read them. A
preference the product records and then ignores is worse than one it never
offered, because the user believes it was taken into account.

### Phase 12 — Job Discovery and Posting Trust

Added 2026-08-23, after this roadmap had run to Phase 11. It is the first phase
here that did not come from the specification documents: it came from
the career-ops comparison, which compared this
platform against the most-starred open-source project in the same space and
found exactly one capability where it was unambiguously ahead.

The finding, in one sentence: **the platform evaluated postings well and could
not find them.** Import existed and was properly built — a person supplied a
link or pasted text. Discovery did not exist at all.

Focus:

- reading public applicant-tracking boards
- whether a saved posting is still open
- whether a posting is what it claims to be

Slices:

- public-ATS ingestion, into a review list a person promotes from
- liveness checking
- posting legitimacy

Three rules shaped it, and each is the reason a slice is built the way it is:

**A discovered posting is a candidate, not a job.** Scans write to
`discovered_postings`; only a person creates a `Job`. The job library is the one
list whose contents mean "I am interested in this", and a scan writing there
would change what every count on the dashboard means with nothing on screen
saying so.

**Unknown is not gone.** A liveness check admits only 404 and 410 as evidence a
posting closed. A refusal, a timeout and a server fault all mean we could not
look, and an inconclusive check writes nothing at all.

**A concern never touches the score.** Legitimacy produces typed, evidenced
concerns and no number, so there is nothing for a later change to average into
the match. A role can be an excellent match and a suspicious posting at once.

Exit criteria:

A configured board returns real postings; a re-scan offers nothing already
decided about; a closed posting is marked closed and an unreachable one is not;
and a job can carry a legitimacy concern while its match score is unchanged.

## Codex task size

Do not assign giant tasks such as “Build Phase 6.”

Prefer small coherent units.

Example:

1. Implement deterministic skill matching.
2. Persist requirement-level results.
3. Expose match API.
4. Build match UI.

## Task template

Every significant task should include:

- Context
- Objective
- Scope
- Relevant docs
- Out of scope
- Acceptance criteria
- Tests required

## AI feature gate

An AI feature is incomplete without:

- output schema
- validation
- failure handling
- prompt version
- AI run trace
- evaluation fixture

## Matching feature gate

Matching is incomplete if it has only an overall score.

It must include requirement-level results and evidence.

## Resume feature gate

Resume tailoring is incomplete if one model call rewrites the whole document.

It requires:

- strategy
- suggestions
- truth validation
- review
- versioning

## Signature visualization rollout

MVP:

- match breakdown
- funnel
- skill demand
- gap impact matrix

V1.1:

- career opportunity map

V1.2:

- career evidence map

## Real-world testing set

Use real jobs during development.

Suggested initial set:

- 10 backend roles
- 5 general software roles
- 5 AI / computer-vision roles

Evaluate:

- parsing
- match honesty
- missed evidence
- gap detection
- resume-strategy differences

## First agent timing

Do not build the first agent until reliable application services exist.

The first recommended agent is a Career Advisor after Phase 10.

## Post-MVP direction

V1.1:

- Career Advisor
- Project Intelligence
- Improved Gap Analysis
- Opportunity Map
- Job Comparison

V1.2:

- Browser Extension
- Mobile Share
- Job Discovery
- Company Research

V1.3:

- Interview Intelligence
- Email integration
- Follow-up workflows
- Calendar integration

## Final principle

At every stage, the repository should contain a more useful working product.

Do not spend months building infrastructure before the first usable workflow.
