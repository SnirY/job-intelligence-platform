# Job Intelligence Platform

A personal AI-powered Job Search and Career Intelligence Platform. This repository contains the product, architecture, AI, UX, API, engineering, and development-continuity specifications, together with the implementation.

## Current state

**Phases 0–10 are complete. Phase 11 — Production Hardening — is in progress.**

The whole loop exists end to end: build a career profile or import one from a
resume, save a job, have the posting read into requirements, match it against
your profile with traceable evidence, tailor a resume, apply, track the outcome,
and see what your saved jobs keep asking for.

There is deliberately no phase table here. This section said "Phases 0–6" for
four phases after Phase 10 shipped, because a hand-written summary of something
recorded elsewhere goes stale and nothing notices. One sentence is the most this
file can keep true.

The per-phase, per-capability detail lives in
`docs/development/implementation-status.md`, which is the source of truth.
`docs/development/known-issues.md` records what is not yet verified, and
`docs/development/current-phase.md` says what is being worked on now.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Web at http://localhost:3000, API at http://localhost:8000, API docs at http://localhost:8000/docs.

For host-process development, running the checks, and the Windows notes, see `docs/development/local-environment.md`.

## Repository layout

```text
apps/
    web/        Next.js + TypeScript + Tailwind + shadcn/ui
    api/        FastAPI + SQLAlchemy + Alembic
    worker/     RQ background worker
packages/
    config/         shared backend settings and logging (jip-config)
    shared-types/   TypeScript API contracts (@jip/shared-types)
    ai-core/        provider abstraction, routing, retry, tracing (jip-ai)
    prompts/        versioned prompt registry (jip-prompts)
docs/
infra/          Dockerfiles
scripts/
tests/
    evals/      AI evaluation fixtures, offline by default
```

## Start here

1. Read `GOAL.md`.
2. Read the current development state in `docs/development/`.
3. Read the specification documents relevant to the active phase.
4. Read the architecture decisions in `docs/adr/`.

## Documentation map

- `docs/00-product-vision.md` — product vision and differentiation
- `docs/01-product-requirements.md` — product scope and MVP
- `docs/02-user-flows.md` — user journeys and flows
- `docs/03-domain-model.md` — entities, relationships, and data rules
- `docs/04-system-architecture.md` — technical architecture
- `docs/05-ai-and-matching.md` — AI architecture and matching engine
- `docs/06-resume-engine.md` — career profile and resume intelligence
- `docs/07-applications-and-career-intelligence.md` — tracker, analytics, and insights
- `docs/08-ui-ux.md` — UI/UX and visualization direction
- `docs/09-mvp-roadmap.md` — phased development roadmap
- `docs/10-api-contracts.md` — API and internal technical interfaces
- `docs/11-engineering-standards.md` — coding, testing, and Codex rules
- `docs/12-project-tracking.md` — tracking and continuity rules
- `docs/adr/` — architecture decision records
- `docs/development/local-environment.md` — running and verifying the stack
- `docs/development/manual-verification-checklist.md` — what automated tests cannot establish

The project should be developed one reliable vertical slice at a time.
