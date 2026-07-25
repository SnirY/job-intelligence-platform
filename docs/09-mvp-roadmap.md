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
