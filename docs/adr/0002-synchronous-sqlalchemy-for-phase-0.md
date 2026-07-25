# ADR-0002 — Synchronous SQLAlchemy, with sync route handlers

Status:
Accepted

Date:
2026-07-25

## Context

FastAPI is an async framework and SQLAlchemy 2.0 supports both synchronous and
asynchronous engines. Alembic's migration environment is synchronous, and the RQ
worker executes tasks in a synchronous call stack. Choosing async for the API
means the repository carries two database access styles from the start.

## Decision

Use a synchronous SQLAlchemy engine everywhere: API, worker, and migrations.

Route handlers that touch the database are declared with `def`, not `async def`.
Starlette runs sync handlers in a thread pool, so a blocking database call does
not stall the event loop. Declaring such a handler `async def` would be the
actual mistake — that blocks the loop for every concurrent request.

## Consequences

- One engine configuration, one session pattern, one set of repository idioms
  shared by the API, the worker, and Alembic.
- Concurrency for database-bound endpoints is bounded by Starlette's thread pool
  (40 threads by default) rather than by the connection pool alone. That is far
  above anything a personal tool will see, and the limit is raisable.
- Handlers must not be casually converted to `async def` later. A handler that
  awaits nothing but calls the database synchronously blocks the event loop, and
  the symptom (latency under concurrency) is much harder to trace than the
  cause.
- Moving to async later means `create_async_engine`, `AsyncSession`, and
  reworking every handler that touches the database. It is a real migration,
  which is why it is recorded here rather than assumed.

## Alternatives considered

- **Async SQLAlchemy from the start** — the eventual destination if the workload
  ever becomes I/O-bound at scale, but it needs a second synchronous setup for
  Alembic and the worker anyway, and it makes every early query more awkward to
  write for concurrency this application will not experience.
- **Async in the API, sync in the worker** — two idioms for the same tables,
  which is the cost of async without its benefit while there are no shared
  repositories to duplicate yet.
