# ADR-0003 — Redis and RQ behind a TaskDispatcher abstraction

Status:
Accepted

Date:
2026-07-25

## Context

`docs/04-system-architecture.md` selects Redis and RQ for background processing
and requires application code to enqueue through a `TaskDispatcher` rather than
calling RQ directly. Phase 0 has to establish that boundary before any feature
needs the queue, because retrofitting it once several services enqueue directly
is a much larger change.

RQ also does not support Windows: its default worker forks a child process per
job. Local development happens on Windows.

## Decision

Redis and RQ as specified, reached only through `TaskDispatcher`
(`apps/api/src/jip_api/infrastructure/tasks/dispatcher.py`).

`TaskDispatcher` is a `Protocol` with a single `enqueue` method returning a
`DispatchedTask` (job id and queue name). `RQTaskDispatcher` implements it.
Tasks are addressed by dotted import path.

Worker class selection is platform-dependent: `SimpleWorker` on Windows, which
executes jobs in the worker process, and the default forking `Worker` elsewhere.

## Consequences

- Application services depend on a one-method protocol, so a fake dispatcher in
  a test is trivial and swapping RQ for another queue is contained.
- Enqueueing by string keeps the API free of any import of worker code, at the
  cost of a task path being unverified until execution.
- Windows development gets no process isolation between jobs: a task that
  corrupts process state or leaks memory affects the worker itself. Deployments
  run Linux and keep the forking worker, so this is a local-development
  difference — and one worth remembering when a task behaves differently in CI.
- `DispatchedTask` is deliberately thin. Job status tracking (the Processing
  Jobs API in `docs/10-api-contracts.md`) is a Phase 5 concern and needs
  persistence, not just a queue id.

## Alternatives considered

- **Calling `rq.Queue` directly from services** — less indirection, but it puts
  an infrastructure dependency inside the application layer, which
  `docs/11-engineering-standards.md` prohibits.
- **Celery** — more features (scheduling, chords, multiple brokers) and
  substantially more operational surface than a personal tool needs. RQ is what
  the architecture document selects.
- **Enqueueing callables rather than paths** — better typo safety through import
  checking, but it requires the API to import the worker package, which creates
  exactly the coupling this decision avoids.
