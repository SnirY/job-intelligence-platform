"""Unit tests for worker tasks and worker selection."""

from __future__ import annotations

import datetime as dt
import os

from rq import SimpleWorker, Worker

from jip_worker.main import select_worker_class
from jip_worker.tasks.system import ping


def test_ping_echoes_the_message() -> None:
    result = ping("hello")

    assert result["task"] == "ping"
    assert result["echo"] == "hello"


def test_ping_timestamp_is_timezone_aware_utc() -> None:
    completed_at = dt.datetime.fromisoformat(ping()["completed_at"])

    assert completed_at.tzinfo is not None
    assert completed_at.utcoffset() == dt.timedelta(0)


def test_worker_class_matches_the_platform() -> None:
    """Windows has no fork(), so the forking worker cannot be used there."""
    expected = SimpleWorker if os.name == "nt" else Worker

    assert select_worker_class() is expected
