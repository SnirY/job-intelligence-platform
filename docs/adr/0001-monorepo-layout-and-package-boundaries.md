# ADR-0001 — Monorepo layout and package boundaries

Status:
Accepted

Date:
2026-07-25

## Context

`docs/04-system-architecture.md` specifies a monorepo containing a Next.js web
app, a FastAPI API, an RQ worker, and shared packages. The repository mixes two
ecosystems, and each needs a dependency mechanism that the other does not
understand. Phase 0 has to pick one that keeps the API and worker from drifting
apart on configuration while preventing a dependency cycle between them.

## Decision

Two independent workspace mechanisms, one per ecosystem:

- **TypeScript** — npm workspaces declared in the root `package.json`, covering
  `apps/web` and `packages/shared-types`. `@jip/shared-types` ships TypeScript
  source rather than a build artifact; Next compiles it through
  `transpilePackages`, so there is no build-ordering step between them.
- **Python** — three distributions installed editable into one virtual
  environment: `jip-config` (`packages/config`), `jip-api` (`apps/api`), and
  `jip-worker` (`apps/worker`). `requirements-dev.txt` lists them in dependency
  order so pip resolves `jip-config` to the local path instead of PyPI.

Lint, format, type-check, and test settings for all Python code live in a single
root `pyproject.toml` that declares no `[project]` table, so it configures the
repository without being installable itself.

The API must not import the worker. The API enqueues tasks by dotted import path
through `TaskDispatcher`; the two processes agree on a string, not on shared
Python objects. Without this the dependency graph would become cyclic as soon as
the worker needed anything the API owns.

`apps/api/src/jip_api/` contains `api/`, `core/`, and `infrastructure/`.
`application/` and `domain/` are deliberately absent until the first domain
module exists — empty layers are scaffolding, and the boundary is documented
here rather than mimed by empty directories.

`packages/ai-core/` and `packages/prompts/` are named in the architecture
document and are likewise absent until Phase 5.

## Consequences

- One `pip install -r requirements-dev.txt` and one `npm install` set up the
  whole repository.
- Shared backend configuration has exactly one definition, so the API and worker
  cannot disagree about what `JIP_DATABASE_URL` means.
- Enqueueing by string means a typo in a task path fails at execution time
  rather than import time. The integration test in
  `apps/api/tests/integration/test_task_dispatch.py` covers the path that
  matters; task paths added later need the same coverage.
- Publishing any package to a registry would need a real build and version
  strategy. Nothing here depends on that yet.

## Alternatives considered

- **Nx or Turborepo** — meaningful caching and task orchestration, but they
  solve a problem this repository does not have at two frontend packages, and
  neither manages the Python side.
- **A single Python distribution containing API and worker** — simpler
  packaging, but it deploys the API's web dependencies into the worker image and
  removes the structural barrier that keeps the API from importing worker code.
- **Separate repositories per app** — rejected by
  `docs/04-system-architecture.md`, which specifies a modular monolith.
