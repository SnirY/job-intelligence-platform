# Job Intelligence Platform

A personal AI-powered Job Search and Career Intelligence Platform. This repository contains the product, architecture, AI, UX, API, engineering, and development-continuity specifications, together with the implementation.

**Current state: Phases 0–5 are complete. Phase 6 (Matching Engine) has not been started.**

| Phase | State | What it delivered |
|---|---|---|
| 0 — Project Foundation | Done | Monorepo, FastAPI, Next.js, PostgreSQL, Redis, RQ, Compose, CI |
| 1 — Authentication & Shell | Done | Clerk, the `users` table, offline JWKS verification, the app shell |
| 2 — Career Profile | Done | Profile, target roles, skills, experience, projects, education — no AI |
| 3 — Resume Import | Done | Upload → extract → parse → review → approve, plus `jip-ai` and `jip-prompts` |
| 4 — Job Workspace | Done | Add a job by paste, link, or hand; the original source preserved; list and detail |
| 5 — Job Intelligence | Done | Versioned analyses: requirements, responsibilities, role family, seniority |
| 6 — Matching Engine | Not started | — |

`docs/development/implementation-status.md` has the per-capability detail, and
`docs/development/known-issues.md` records what is not yet verified.

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

The project should be developed one reliable vertical slice at a time.
