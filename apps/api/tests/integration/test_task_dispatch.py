"""End-to-end proof that queued work reaches the worker and comes back.

This is the Phase 0 exit criterion "the worker processes a test background
task": the API-side dispatcher enqueues by dotted path, real Redis stores the
job, and a real RQ worker executes the worker package's task function.
"""

from __future__ import annotations

import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from rq.job import Job, JobStatus

from jip_api.infrastructure.tasks.dispatcher import RQTaskDispatcher

pytestmark = pytest.mark.integration

PING_TASK = "jip_worker.tasks.system.ping"


def _drain(redis: Redis, queue_name: str) -> None:
    """Run every queued job to completion in this process.

    ``SimpleWorker`` executes jobs inline rather than forking, which keeps the
    test deterministic and lets it run on Windows as well as Linux.
    """
    queue = Queue(queue_name, connection=redis)
    SimpleWorker([queue], connection=redis).work(burst=True)


def test_dispatched_task_is_executed_by_the_worker(redis_client: Redis) -> None:
    dispatcher = RQTaskDispatcher(redis_client)

    dispatched = dispatcher.enqueue(PING_TASK, "phase-0")
    assert dispatched.queue == "default"

    _drain(redis_client, dispatched.queue)

    job = Job.fetch(dispatched.id, connection=redis_client)
    assert job.get_status() == JobStatus.FINISHED

    result = job.return_value()
    assert result is not None, "the worker returned no result"
    assert result["task"] == "ping"
    assert result["echo"] == "phase-0"
    assert result["completed_at"]


def test_dispatcher_honours_an_explicit_queue(redis_client: Redis) -> None:
    dispatcher = RQTaskDispatcher(redis_client, default_queue="default")

    dispatched = dispatcher.enqueue(PING_TASK, queue="high")

    assert dispatched.queue == "high"
    assert Queue("high", connection=redis_client).count == 1
    assert Queue("default", connection=redis_client).count == 0


def test_failing_task_is_recorded_as_failed_not_silently_dropped(redis_client: Redis) -> None:
    """A task that raises must leave a failed job behind.

    Engineering standards forbid swallowing background failures; if RQ were
    configured to discard them, retries and diagnostics would be impossible.
    """
    queue = Queue("default", connection=redis_client)
    job = queue.enqueue("jip_worker.tasks.system.ping", unexpected_keyword="boom")

    _drain(redis_client, "default")

    assert Job.fetch(job.id, connection=redis_client).get_status() == JobStatus.FAILED
