# Cross-cutting tests

Tests that belong to a single package live with that package:

```text
packages/config/tests/     shared settings
apps/api/tests/unit/       API behaviour without live infrastructure
apps/api/tests/integration/  migrations, readiness, task dispatch
apps/worker/tests/         worker tasks
apps/web/src/**/*.test.tsx  frontend units
```

This directory is reserved for tests that span applications and therefore have
no single owner:

- `tests/e2e/` — browser journeys across web and API (Phase 1 onward, once
  there is a user-facing flow to walk through)
- `tests/evals/` — AI evaluation suites, kept separate from the normal test run
  because they call live models (Phase 5 onward, per
  `docs/11-engineering-standards.md`)

Neither exists yet. Phase 0 has no cross-application behaviour to cover, and
creating the directories early would only add empty scaffolding.
