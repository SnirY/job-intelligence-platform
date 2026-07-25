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
    """Start consuming queued tasks. Blocks until the worker is stopped."""
    settings = get_settings()
    configure_logging(settings.log_level)

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
