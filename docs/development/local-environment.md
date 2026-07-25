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
export JIP_TEST_DATABASE_URL=postgresql+psycopg://jip:jip_local_dev_only@localhost:5432/jip
export JIP_TEST_REDIS_URL=redis://localhost:6379/0
pytest -m integration
```

Without them the tests skip. CI sets `JIP_REQUIRE_INTEGRATION=1`, which turns a
skip into a failure — a missing service must not present as a green build.

Each migration test creates and drops its own database, so `JIP_TEST_DATABASE_URL`
needs permission to `CREATE DATABASE`.

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
`docs/adr/0004-clerk-as-authentication-provider.md` for why Clerk, and how the
pieces fit.

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
   JIP_CLERK_ISSUER=https://your-app.clerk.accounts.dev
   JIP_CLERK_AUTHORIZED_PARTIES=http://localhost:3000
   ```

5. Restart both processes. Settings are read once per process.

Two things worth knowing:

- **The API needs no Clerk secret.** It verifies tokens against the public JWKS.
  If a Clerk secret key ever appears in the API's configuration, something has
  been wired wrong.
- **Leaving `JIP_CLERK_AUTHORIZED_PARTIES` empty disables the `azp` check**,
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

## Environment variables

Every backend variable is prefixed `JIP_`. `.env.example` documents all of them.
`JIP_DATABASE_URL` and `JIP_REDIS_URL` are required and have no defaults: a
process with an unset or wrong URL fails at startup rather than connecting
somewhere unintended.

Frontend variables must be `NEXT_PUBLIC_`-prefixed to reach the browser, which
means they are public. Nothing secret can be passed to the frontend this way;
route it through the API instead.
