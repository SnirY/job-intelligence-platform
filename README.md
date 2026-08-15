# Job Intelligence Platform

**Reads a job posting into structured requirements, matches it against a
verified career profile with traceable evidence, and writes a tailored résumé
that cannot make a claim your profile does not support.**

A personal full-stack project: FastAPI, Next.js, PostgreSQL, Redis, Docker.
~46,000 lines, 86 REST endpoints, 1,655 automated tests in CI.

---

## The idea

Most job tools score a résumé against a posting and hand back a number. This one
is built on the assumption that **the number is the least useful part**.

What matters is *why*. Every verdict here is traceable to a specific row of the
user's own career data — this role, that project, this bullet — and anything the
system cannot evidence, it says so about rather than guessing.

Three rules shaped almost every technical decision:

1. **Never fabricate.** A generated résumé line containing a figure that appears
   nowhere in the user's data is blocked, quoted back, and shown for review.
2. **AI never controls verified facts.** Model output lands in a review table and
   stops there. Only a person turns a proposal into a career fact.
3. **Separate what was said from what we concluded.** The posting's own words are
   preserved and quoted; every judgement is labelled as a reading and carries its
   reasoning.

## What it does

```text
Build a profile  →  Save a job  →  Read the posting  →  Match with evidence
                                        →  Tailor a résumé  →  Apply  →  Track
```

- **Career profile** — skills, experience, projects, education, preferences,
  built by hand or imported from a résumé PDF and reviewed proposal by proposal.
- **Job intelligence** — a posting parsed into typed requirements with an
  importance the model must not overstate, plus role family and seniority.
- **Matching** — requirement-level verdicts, each linked to the evidence behind
  it, with a recommendation stored separately from the score so the two can
  disagree.
- **Résumé tailoring** — strategy, then suggestions, then truth validation, then
  a review, then a version. Five stages, five requests, never one call rewriting
  a document.
- **Applications and insights** — an append-only application history, and what
  the user's own saved jobs keep asking for.

## The parts worth reading

If you are evaluating this as engineering work rather than as a product, these
are the files where the thinking is:

| | |
|---|---|
| [`application/matching/matcher.py`](apps/api/src/jip_api/application/matching/matcher.py) | The scoring engine. **Deterministic and versioned — no model call anywhere in it.** Eight verdicts, including `NO_EVIDENCE`, which is excluded from the average rather than scored zero: an incomplete profile must not quietly lower the number |
| [`application/resumes/truth.py`](apps/api/src/jip_api/application/resumes/truth.py) | The fabrication guard. Refuses invented figures, flags introduced terminology, and classifies risk |
| [`packages/ai-core`](packages/ai-core) | The provider boundary: JSON-schema constrained decoding, schema validation, retry classified by failure type, and a trace per attempt with token cost |
| [`docs/adr/`](docs/adr) | Six architecture decisions, each with the alternative that was rejected and why |
| [`docs/development/known-issues.md`](docs/development/known-issues.md) | Every defect found, what caused it, and what was done. Including the ones that were embarrassing |

## Engineering

**Tests.** 1,655 across three layers, all run in CI:

| | |
|---|---|
| Backend unit + offline AI evaluations | 870 |
| Integration, against real PostgreSQL and Redis | 466 |
| Frontend | 319 |

Plus a live-model evaluation suite that runs on request, because it costs money.

**Checks.** `mypy --strict` over 245 files, TypeScript `strict` with
`noUncheckedIndexedAccess`, ruff, eslint, prettier, an Alembic
`upgrade head → downgrade base` round-trip, and a Docker Compose stack brought up
from scratch. All on every pull request.

**AI is treated as an untrusted input**, not as a library call. Every operation
has a typed output schema, schema validation, a versioned prompt, a persisted
run trace, and an evaluation fixture. Failures are classified: a permanent one
is never retried, and a retry is never offered where it cannot work.

**Verification that automated tests cannot do** is written down rather than
assumed. [`manual-verification-checklist.md`](docs/development/manual-verification-checklist.md)
records what a person walked, on what date, and what it found. Twelve stages have
been walked and eleven found a defect the suite did not — nearly all of them a
screen saying the wrong thing about a correct calculation. That ratio is why the
file exists.

## Running it

```bash
cp .env.example .env
docker compose up --build
```

Web on `:3000`, API on `:8000`, API docs on `:8000/docs`.

The AI features need an API key in `.env`; everything else runs without one. For
host-process development, the checks, and the Windows notes, see
[`local-environment.md`](docs/development/local-environment.md).

## Layout

```text
apps/
    web/        Next.js 15 · TypeScript · Tailwind · shadcn/ui
    api/        FastAPI · SQLAlchemy · Alembic
    worker/     RQ background worker
packages/
    config/         shared settings and logging
    shared-types/   TypeScript API contracts
    ai-core/        provider abstraction, routing, retry, tracing
    prompts/        versioned prompt registry
docs/           specification, ADRs, and development tracking
tests/evals/    AI evaluation fixtures, offline by default
```

## Status

The full loop works end to end. Phases 0–10 are complete; Phase 11, production
hardening, is in progress.

Deliberately not claimed: this is not deployed and has one user. It is a
personal project built to be correct rather than to scale, and the tracking
documents say plainly what is unverified —
[`implementation-status.md`](docs/development/implementation-status.md) for
capability, [`known-issues.md`](docs/development/known-issues.md) for what is
still open.

## Documentation

Twelve specification documents were written before the code and have been
maintained alongside it. They are the part of this repository I would point at
first.

- [`00-product-vision.md`](docs/00-product-vision.md) — vision and differentiation
- [`01-product-requirements.md`](docs/01-product-requirements.md) — scope and MVP
- [`02-user-flows.md`](docs/02-user-flows.md) — journeys
- [`03-domain-model.md`](docs/03-domain-model.md) — entities and data rules
- [`04-system-architecture.md`](docs/04-system-architecture.md) — architecture
- [`05-ai-and-matching.md`](docs/05-ai-and-matching.md) — AI boundaries and the matching model
- [`06-resume-engine.md`](docs/06-resume-engine.md) — career truth and tailoring
- [`07-applications-and-career-intelligence.md`](docs/07-applications-and-career-intelligence.md) — tracker and analytics
- [`08-ui-ux.md`](docs/08-ui-ux.md) — UI direction
- [`09-mvp-roadmap.md`](docs/09-mvp-roadmap.md) — phased plan
- [`10-api-contracts.md`](docs/10-api-contracts.md) — API contracts
- [`11-engineering-standards.md`](docs/11-engineering-standards.md) — coding and testing rules
- [`12-project-tracking.md`](docs/12-project-tracking.md) — continuity process

Two written for a redesign, and useful on their own:
[`ui-invariants.md`](docs/development/ui-invariants.md) — the rules a screen must
keep no matter how it looks — and
[`screen-inventory.md`](docs/development/screen-inventory.md).
