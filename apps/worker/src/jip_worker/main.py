"""Worker entrypoint.

Run with ``jip-worker`` (installed console script) or
``python -m jip_worker.main``.
"""

from __future__ import annotations

import logging
import os
import sys

from redis import Redis
from rq import Queue, SimpleWorker, Worker
from rq.worker import BaseWorker

from jip_api.infrastructure.db.schema_version import (
    SchemaVersionMismatch,
    verify_schema_version,
)
from jip_api.infrastructure.db.session import get_engine
from jip_config import configure_logging, get_settings

logger = logging.getLogger(__name__)


def select_worker_class() -> type[BaseWorker]:
    """Return the worker class appropriate for this platform.

    RQ's default worker forks a child process per job, which POSIX provides and
    Windows does not. ``SimpleWorker`` runs jobs in the worker process itself, so
    developers on Windows get a usable local worker. Deployments run on Linux
    and get the forking worker with its process-level job isolation.
    """
    return SimpleWorker if os.name == "nt" else Worker


def build_worker(redis: Redis, queue_names: list[str]) -> BaseWorker:
    """Construct a worker bound to ``queue_names``.

    Requires a reachable Redis: RQ resolves worker identity against the server
    during construction.
    """
    queues = [Queue(name, connection=redis) for name in queue_names]
    return select_worker_class()(queues, connection=redis)


def main() -> int:
    """Start consuming queued tasks. Blocks until the worker is stopped.

    Returns 1 without consuming anything if the database is not at the revision
    this build expects — see :func:`verify_schema_version`.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    # DEV-051, and it goes before Redis on purpose. A worker that has already
    # registered with RQ is a worker that can be handed a job, and the whole
    # point is to refuse before anything can be taken off the queue.
    #
    # Exits rather than raising: a traceback ending in a KeyError about a
    # revision is the kind of thing people scroll past, and this failure is one
    # sentence that deserves to be read.
    try:
        verify_schema_version(get_engine())
    except SchemaVersionMismatch as mismatch:
        logger.error("%s", mismatch)
        return 1

    redis = Redis.from_url(settings.redis_url)
    worker = build_worker(redis, settings.worker_queues)

    logger.info(
        "Starting worker",
        extra={
            "queues": settings.worker_queues,
            "worker_class": type(worker).__name__,
            "environment": settings.environment.value,
        },
    )
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
