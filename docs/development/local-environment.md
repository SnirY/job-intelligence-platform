# Local Development Environment

How to run and verify the stack. Kept here rather than in the README because it
changes with the implementation, not with the product description.

## Option A — Docker Compose (everything)

```bash
cp .env.example .env
docker compose up --build
```

Brings up PostgreSQL, Redis, a one-shot migration run, the API, the worker, and
the web app. The API and worker wait for migrations to complete before starting,
so no process runs against an unmigrated database.

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/api/v1/health/ready |

## Option B — Host processes

Needs Python 3.12+, Node 20.11+, and reachable PostgreSQL and Redis instances.

```bash
# Backend
python -m venv .venv
.venv/Scripts/activate           # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements-dev.txt

# Frontend
npm install

cp .env.example .env             # then edit the URLs to match your services
```

Run each process in its own terminal:

```bash
# Migrations (from apps/api)
alembic upgrade head

# API
uvicorn jip_api.main:app --reload --port 8000

# Worker
jip-worker

# Web
npm run dev
```

## Checks

```bash
python scripts/run_checks.py                # everything except integration tests
python scripts/run_checks.py --integration  # adds tests needing live services
```

Or individually:

| Check | Command |
|---|---|
| Backend lint | `ruff check .` |
| Backend format | `ruff format --check .` |
| Backend types | `mypy` |
| Backend unit tests | `pytest -m "not integration"` |
| Backend integration tests | `pytest -m integration` |
| Frontend format | `npm run format:check` |
| Frontend lint | `npm run lint` |
| Frontend types | `npm run typecheck` |
| Frontend tests | `npm run test` |
| Frontend build | `npm run build` |

## Integration tests

They need live services, addressed through their own variables so a test run can
never point at the same database a developer is using by hand:

```bash
export JIP_TEST_DATABASE_URL=postgresql+psycopg://jip:jip_local_dev_only@localhost:55432/jip
export JIP_TEST_REDIS_URL=redis://localhost:6379/0
pytest -m integration
```

The port is `POSTGRES_PORT` from `.env`, not 5432. This said 5432 until
2026-08-08, from before the Compose service moved off the port the machine's own
PostgreSQL 17 already holds.

Without them the tests skip. CI sets `JIP_REQUIRE_INTEGRATION=1`, which turns a
skip into a failure — a missing service must not present as a green build.

Each migration test creates and drops its own database, so `JIP_TEST_DATABASE_URL`
needs permission to `CREATE DATABASE`.

Stop every worker first — the container and the host process both.

```bash
docker compose stop worker
```

`test_task_dispatch.py` enqueues onto `default` and drains it with an
in-process burst worker. Anything else consuming from the same queue on the same
Redis takes the job first, which surfaces as a job stuck in `queued` and reads
like a dispatcher bug.

The line above only covers the container. **Option B runs the worker as a host
process**, and `docker compose stop worker` does nothing to it — which cost a
run on 2026-08-08. Worse than a failure: the suite hangs, because the burst
worker waits for a job another process has already taken.

```bash
powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*jip-worker*' } | Select-Object ProcessId, CommandLine"
```

**`next build` has the same shape of conflict.** On Windows, `npm run dev` holds
`apps/web/.next/trace` and a concurrent build fails with `EPERM` on that file.
Stop the dev server before running the frontend checks, or let CI build.

## Windows notes

- RQ's default worker forks per job, which Windows cannot do. `jip-worker`
  selects `SimpleWorker` there automatically; jobs run in the worker process
  with no process isolation between them. Linux deployments keep the forking
  worker.
- Without Docker Desktop, a throwaway PostgreSQL cluster can be created from a
  local PostgreSQL installation without touching an existing one:

  ```bash
  initdb -D /path/to/scratch/pgdata -U jip -A trust -E UTF8
  pg_ctl -D /path/to/scratch/pgdata -o "-p 55432" start
  ```

- There is no equivalent trick for Redis. Install Docker Desktop or a
  Redis-compatible Windows server, or rely on CI (see DEV-003 in
  `known-issues.md`).

## Authentication setup (Clerk)

Required before sign-in works against a real instance. See
`docs/adr/0004-clerk-as-authentication-provider.md` for why Clerk, and
`docs/adr/0005-provider-neutral-identity-boundary.md` for why the API's settings
are named `JIP_AUTH_*` rather than after the vendor.

1. Create an application at [dashboard.clerk.com](https://dashboard.clerk.com).
2. From **API Keys**, copy the publishable key, the secret key, and the Frontend
   API URL (this is the token issuer).
3. Fill in `apps/web/.env.local` (copy from `apps/web/.env.example`):

   ```bash
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
   CLERK_SECRET_KEY=sk_test_...
   ```

4. Fill in the root `.env` for the API:

   ```bash
   JIP_AUTH_PROVIDER=clerk
   JIP_AUTH_ISSUER=https://your-app.clerk.accounts.dev
   JIP_AUTH_AUTHORIZED_PARTIES=http://localhost:3000
   ```

5. Restart both processes. Settings are read once per process.

Two things worth knowing:

- **The API needs no Clerk secret.** It verifies tokens against the public JWKS.
  If a Clerk secret key ever appears in the API's configuration, something has
  been wired wrong.
- **Leaving `JIP_AUTH_AUTHORIZED_PARTIES` empty disables the `azp` check**,
  which is what stops a token minted for a different application from being
  accepted here. Set it in every environment.

### Keyless mode

With no Clerk keys set, `next dev` runs in Clerk's keyless mode: it provisions a
temporary instance and prints a claim URL in the server output. Sign-in works
immediately, which is convenient for a first look, but the instance is not
yours until claimed and the API cannot verify its tokens (you have no issuer to
configure). Use real keys for anything beyond a smoke test.

### Where authorization actually happens

Three independent layers, in order of authority:

1. **`src/app/(app)/layout.tsx`** — checks the session before rendering any
   authenticated page. This is the frontend boundary. A page is protected
   because it lives under `(app)/`, not because a pattern matched.
2. **The API** — verifies the bearer token on every request, independently of
   anything the frontend did.
3. **`src/middleware.ts`** — attaches auth context only. It deliberately makes
   no authorization decisions: Clerk deprecated middleware path-matching for
   this because a path pattern can diverge from how Next.js routes a request,
   leaving a resource reachable with nothing logged.

## AI configuration

Resume import is the first feature that calls a model. Without a key, an import
still uploads and stores the file, then fails with a clear `PROVIDER_ERROR` —
the platform never returns invented results when AI is unavailable
(`docs/11-engineering-standards.md`).

```bash
JIP_AI_PROVIDER=anthropic
JIP_AI_API_KEY=sk-ant-...
JIP_AI_RESUME_PARSE_MODEL=claude-opus-5
```

Model routing is configuration, not code (`docs/05-ai-and-matching.md`), so a
cost or quality decision can be revisited without a deploy. `.env.example`
documents the rest: output-token ceiling, effort, attempt count, timeout, and
the input-character limit.

The key belongs to the **worker**, which is what actually makes the calls. The
API reads the same settings so its own configuration reporting stays truthful.

Job intelligence adds two more routable operations, because parsing a posting
and interpreting it are different tasks:

```bash
JIP_AI_JOB_PARSE_MODEL=
JIP_AI_JOB_ANALYSIS_MODEL=
```

Both fall back to `JIP_AI_RESUME_PARSE_MODEL` when empty, so adding them did
not change what an existing deployment runs. Their token ceilings differ
because their outputs do — a parse returns every requirement in a posting, an
analysis returns a handful of fields and its reasoning.

## Job URL import

Importing a job by link makes our server open a URL a user supplied, so the
worker is the process that needs the settings:

```bash
JIP_JOB_FETCH_TIMEOUT_SECONDS=15
JIP_JOB_FETCH_MAX_BYTES=3145728
```

Both are abuse controls first: a slow host must not tie up a worker, and a
large response must not be read into memory.

The SSRF rules are **not** configurable, deliberately. Schemes are limited to
HTTP and HTTPS, ports to 80, 443, 8080, and 8443, and every address DNS returns
must be public — loopback, link-local, private, and the cloud metadata address
are all refused, including through redirects. An operator cannot widen that
with an environment variable, because the one thing worse than no SSRF
protection is SSRF protection that a hurried change can switch off. See
`apps/api/src/jip_api/infrastructure/fetching/safety.py`.

Nothing here needs configuring for local development, and a job import works
with no key or credential of any kind — this phase calls no model.

## AI evaluations

`tests/evals/` runs offline by default and is part of the normal suite: each
fixture replays a recorded response through the fake provider, which exercises
prompt rendering, structured parsing, schema and business validation, and the
fabrication guards. That is where most of what can regress actually lives.

To measure the *model* rather than the code around it:

```bash
export JIP_RUN_AI_EVALS=1
export JIP_AI_API_KEY=sk-ant-...
pytest tests/evals -m live_ai
```

This costs money and is the only path in the repository that calls a live
model. `docs/11-engineering-standards.md` keeps it out of the normal run.

## Environment variables

Every backend variable is prefixed `JIP_`. `.env.example` documents all of them.
`JIP_DATABASE_URL` and `JIP_REDIS_URL` are required and have no defaults: a
process with an unset or wrong URL fails at startup rather than connecting
somewhere unintended.

Frontend variables must be `NEXT_PUBLIC_`-prefixed to reach the browser, which
means they are public. Nothing secret can be passed to the frontend this way;
route it through the API instead.
