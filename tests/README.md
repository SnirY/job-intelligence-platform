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

- `tests/e2e/` — browser journeys across web and API. **Still absent.** No
  browser journey is automated yet; see DEV-006 in
  `docs/development/known-issues.md`.
- `tests/evals/` — AI evaluation fixtures. **Built in Phase 3**, which turned
  out to be the first AI feature rather than Phase 5.

`tests/evals/` runs in the normal suite because it is offline by default: each
fixture replays a recorded model response, which exercises everything the
platform owns around the call. Only the `live_ai`-marked run makes real
requests, and it is skipped unless `JIP_RUN_AI_EVALS=1`. See
`tests/evals/README.md`.
