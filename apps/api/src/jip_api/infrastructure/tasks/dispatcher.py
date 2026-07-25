"""Task dispatching behind an abstraction.

``docs/04-system-architecture.md`` requires application code to enqueue work
through a ``TaskDispatcher`` rather than calling RQ directly, so the queue
implementation can change without touching callers.

Tasks are enqueued by dotted import path. The API therefore never imports the
worker package, and the dependency stays one-directional: both processes agree
on a string, not on shared Python objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from redis import Redis
from rq import Queue

from jip_config import get_settings


@dataclass(frozen=True, slots=True)
class DispatchedTask:
    """Identity of an enqueued task, returned to the caller for status lookups."""

    id: str
    queue: str


class TaskDispatcher(Protocol):
    """Enqueue background work."""

    def enqueue(
        self,
        task_path: str,
        *args: Any,
        queue: str | None = None,
        **kwargs: Any,
    ) -> DispatchedTask:
        """Schedule ``task_path`` for execution and return its identity."""
        ...


class RQTaskDispatcher:
    """:class:`TaskDispatcher` backed by Redis and RQ."""

    def __init__(self, redis: Redis, default_queue: str = "default") -> None:
        self._redis = redis
        self._default_queue = default_queue

    def enqueue(
        self,
        task_path: str,
        *args: Any,
        queue: str | None = None,
        **kwargs: Any,
    ) -> DispatchedTask:
        queue_name = queue or self._default_queue
        job = Queue(queue_name, connection=self._redis).enqueue(task_path, *args, **kwargs)
        return DispatchedTask(id=job.id, queue=queue_name)


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """Return the process-wide Redis client.

    Timeouts are bounded for the same reason as the database engine: an
    unreachable Redis must fail fast so readiness reports the outage.
    """
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.connect_timeout_seconds,
        socket_timeout=settings.connect_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_task_dispatcher() -> TaskDispatcher:
    """Return the configured dispatcher."""
    settings = get_settings()
    return RQTaskDispatcher(get_redis(), default_queue=settings.worker_queues[0])


def reset_task_caches() -> None:
    """Close the cached Redis client and drop the cached factories.

    Closing first releases the connection pool instead of leaving sockets for
    the garbage collector. Used by tests that reconfigure the Redis URL, and on
    process shutdown.
    """
    if get_redis.cache_info().currsize:
        get_redis().close()
    get_redis.cache_clear()
    get_task_dispatcher.cache_clear()
