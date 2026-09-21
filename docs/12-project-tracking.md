# Project Tracking & Development Continuity

## Purpose

Maintain lightweight but reliable development tracking so a new session can answer:

- What are we building now?
- What is complete?
- What is partial?
- What is blocked?
- What should happen next?
- Which important decisions have been made?

Tracking should preserve continuity without becoming bureaucracy.

> The tracking files this document describes are working notes. They are kept
> alongside the code during development and are not part of the published
> repository.

## Mandatory tracking files

```text
docs/development/current-phase.md
docs/development/implementation-status.md
docs/development/active-task.md
docs/development/known-issues.md
```

Use:

```text
docs/development/tasks/
```

for large multi-session work.

Use:

```text
docs/adr/
```

for significant architectural decisions.

## current-phase.md

Keep concise.

Include:

- Current Phase
- Current Milestone
- Phase Goal
- Completed Work
- Work In Progress
- Next Planned Slice
- Phase Exit Criteria

## implementation-status.md

Use high-level statuses:

```text
NOT_STARTED
PLANNED
IN_PROGRESS
PARTIALLY_IMPLEMENTED
BLOCKED
DONE
DEFERRED
```

Never mark something `DONE` when:

- important TODOs remain
- production behavior is mocked
- persistence is missing
- required tests are missing
- acceptance criteria are unmet

## active-task.md

Use for the currently active task.

Suggested structure:

- Objective
- User Value
- Relevant Documentation
- Scope
- Out of Scope
- Implementation Plan
- Progress
- Acceptance Criteria
- Tests
- Current Problems
- Next Step

During long Codex runs, update progress at meaningful checkpoints.

Do not update after every tiny edit.

## known-issues.md

Track meaningful unresolved issues.

For each issue include:

- ID
- Title
- Severity
- Affected Area
- Description
- Impact
- Workaround
- Status

Do not use it as a dump for every minor TODO.

## Task files

Create detailed task documents only when work:

- spans multiple sessions
- has several independent sub-parts
- would be expensive to reconstruct after interruption

## ADRs

Create an ADR for long-term architectural decisions such as:

- auth provider
- task queue
- storage provider
- resume-rendering architecture
- major domain-model changes
- moving away from modular monolith

Do not create ADRs for minor implementation choices.

## No duplicate logs

Do not maintain both a generic `decisions.md` and ADRs for the same purpose.

Do not maintain a detailed manual changelog during early development unless releases make it useful.

Git history remains the technical change history.

## Session start protocol

Before significant work:

1. Read `GOAL.md`.
2. Read `current-phase.md`.
3. Read `implementation-status.md`.
4. Read `active-task.md`.
5. Read `known-issues.md`.
6. Inspect git status.
7. Inspect recent commits.
8. Read relevant docs.
9. Inspect implementation and tests.

## Session end protocol

Before ending significant work:

1. Run relevant tests.
2. Review changes.
3. Update `active-task.md`.
4. Update `current-phase.md` when relevant.
5. Update `implementation-status.md` when project capability changed.
6. Update `known-issues.md` when meaningful issues changed.
7. Record significant decisions in ADRs.
8. Summarize completed and remaining work honestly.

## Automatic tracking responsibility

Codex is responsible for recognizing when tracking files need updates.

The user should not need to explicitly ask for progress-file maintenance after every task.

## Tracking and Definition of Done

Implementation and tracking must describe the same reality.

A task is not fully complete when code is finished but repository tracking still says “Not Started.”

## Phase exit protocol — read the specification, not the slice list

Before marking a phase DONE, compare it against the **specification module it
implements**, not against its own list of slices.

The slice list is the thing most likely to be wrong. It was written once, early,
and a phase that closes against it can only ever confirm that the list was
completed — never that the list was right.

### The check

1. Open the module in `docs/01-product-requirements.md` that the phase covers,
   and any section of `docs/03`, `docs/05`, `docs/06` or `docs/07` describing
   the same area.
2. List every element they name.
3. Mark each one: **built**, **deliberately deferred**, or **missed**.
4. Nothing may be left unmarked. A deferral needs a reason recorded; a miss
   needs a `known-issues.md` entry or a slice in a later phase.
5. Do the same for the MVP schema list in `docs/03-domain-model.md`. A table
   named there and absent from the migrations is either a decision or a drift,
   and the difference has to be written down.

Record the result in `implementation-status.md` beside the phase.

### Why this exists

It has been run twice and found four things both times together.

**2026-08-03 — DEV-035.** `docs/01` lists eleven elements in the Career Profile
module. Phase 2's slice list named six. `CareerPreferences` was defined in
`docs/03`, named in Flow 1 of `docs/02`, listed among the inputs a
recommendation considers in `docs/05`, and scheduled in no phase. Phase 2 closed
DONE against a list that was already short, and `/settings` rendered a
placeholder for nine phases — a placeholder being indistinguishable from a page
whose turn has not come, which is why nobody asked.

**2026-08-15 — DEV-052, DEV-053, DEV-054, DEV-055.** The same reading, repeated
because the first one suggested it should be. The same six-against-eleven gap in
Phase 2 had dropped **certifications** as well, which the matcher turns into a
wrong answer rather than a missing feature. Phase 7 built all eight items on its
list and never turned an entire section of `docs/06` into an item at all. Two
tables in the MVP schema were implemented as something else, both defensibly,
neither recorded.

Three of those four came through the same seam: **a phase whose slice list was
shorter than the module it claimed to cover.**

### What makes it worth doing

It costs one careful reading and it has a base rate. Both runs found something;
the second found three things the first missed, in phases already marked DONE.

The failure it catches is specifically hard to see any other way. Tests cannot
find a feature nobody wrote — there is nothing to assert against. A walkthrough
cannot find it either: an absent screen looks like a screen whose phase has not
arrived. Only reading the specification against the code surfaces it, and only
if someone does it deliberately.

## Partial work

Use `PARTIALLY_IMPLEMENTED` and document exactly what exists and what remains.

## Blocked work

Record:

- why it is blocked
- what has been tried
- what dependency is missing
- what can continue independently

Do not rediscover the same blocker in later sessions.

## Long autonomous runs

Maintain enough progress state to recover from interruption.

Useful checkpoints:

- database complete
- backend flow complete
- frontend integration complete
- testing in progress

## Additional tracking files

Codex may create additional files under `docs/development/` only when they add real value.

Examples:

- migration-plan.md
- evaluation-status.md
- release-checklist.md
- mvp-readiness.md

Before creating one, check whether an existing file already covers the purpose.

## Tracking hierarchy

```text
GOAL.md
→ Long-term mission and operating rules

docs/09-mvp-roadmap.md
→ Planned development path

current-phase.md
→ Current location

implementation-status.md
→ Overall implementation state

active-task.md
→ Current work

known-issues.md
→ Important unresolved problems

tasks/*
→ Large multi-session work

adr/*
→ Long-term architecture decisions
```

Avoid duplicating the same information everywhere.

## Final principle

Tracking exists so a new engineering session can quickly understand:

```text
Where are we?
What works?
What does not?
What are we doing now?
What should happen next?
```

If the tracking system answers those reliably, it is sufficient.
