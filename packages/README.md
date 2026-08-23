# Packages

Shared code used by more than one application.

| Package | Language | Status | Purpose |
|---|---|---|---|
| `config/` | Python (`jip-config`) | Implemented | Settings and structured logging shared by the API and worker |
| `shared-types/` | TypeScript (`@jip/shared-types`) | Implemented | Response envelope and API contracts shared by the web app |
| `ai-core/` | Python (`jip-ai-core`) | Implemented | Provider abstraction, model router, structured outputs, retry classification, tracing |
| `prompts/` | Python (`jip-prompts`) | Implemented | Versioned prompt registry |
| `job-sources/` | Python (`jip-job-sources`) | Providers built; not yet wired | Reading public applicant-tracking boards into postings |

`ai-core/` and `prompts/` were deliberately absent until Phase 5, on the
argument that an empty package with no behaviour is scaffolding that has to be
redesigned once the real requirements exist. Both were built then. This table
said otherwise until 2026-08-23, which is the same drift `docs/12` exists to
catch and did not.

`job-sources/` is Phase 12, Slice 1. The package reads boards; nothing yet calls
it — see `docs/development/tasks/phase-12-job-discovery.md`.

## Why a package rather than a module in the API

The same argument ADR-0001 makes for `ai-core`. A provider boundary — several
vendors, one contract, and callers that must not know which one answered —
belongs behind a Protocol in its own package, where its tests can run without
the API and where nothing can quietly reach past the interface.

For `job-sources` there is a second reason, and it is the one worth keeping:
**a board is a source of text, never a source of judgement.** The package holds
no ORM model and imports nothing from `apps/api`, so there is nowhere in it for
a requirement, a score or a seniority to appear. A discovered posting goes
through the same `JOB_PARSE` and `JOB_ANALYSIS` a pasted one does, which is what
stops discovery becoming a second and quieter way of deciding what a job is.
