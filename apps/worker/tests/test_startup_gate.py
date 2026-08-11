"""The worker refuses to start against a schema it was not built for.

DEV-051. The unit tests for the check itself live in
``apps/api/tests/unit/test_schema_version.py``; these are about the wiring —
that `main` consults it, that it does so *before* Redis, and that a mismatch
exits rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from jip_api.infrastructure.db.schema_version import SchemaVersionMismatch
from jip_config import Environment
from jip_worker import main as worker_main


@dataclass(frozen=True)
class _Settings:
    """Only the four attributes `main` reads.

    Real settings come from the environment, and CI has none — the first
    version of this file called the real `get_settings()` and passed locally
    off the developer's `.env` while failing in CI on two missing fields. A
    unit test of the start-up *ordering* should not need a configured
    environment to run.
    """

    log_level: str = "INFO"
    redis_url: str = "redis://localhost:6379/0"
    worker_queues: list[str] = field(default_factory=lambda: ["default"])
    environment: Environment = Environment.TEST


@pytest.fixture(autouse=True)
def _no_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate is what these tests drive; settings and the engine are not."""
    monkeypatch.setattr(worker_main, "get_settings", _Settings)
    monkeypatch.setattr(worker_main, "get_engine", lambda: object())


def test_a_mismatch_exits_without_touching_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering is the point, not an implementation detail.

    A worker that has reached Redis has registered with RQ, and a registered
    worker can be handed a job. Refusing after that would still have let the
    thing DEV-051 is about happen — once.
    """
    touched: list[str] = []

    def refuse(_engine: Any) -> None:
        raise SchemaVersionMismatch("this build expects abc, the database is at xyz")

    class _Redis:
        @staticmethod
        def from_url(*_args: Any, **_kwargs: Any) -> object:
            touched.append("redis")
            return object()

    monkeypatch.setattr(worker_main, "verify_schema_version", refuse)
    # The name in the worker's namespace, not `Redis.from_url` — patching the
    # attribute would reach through to the real `redis.Redis` class and leave
    # every other test in the session holding a stub.
    monkeypatch.setattr(worker_main, "Redis", _Redis)

    assert worker_main.main() == 1
    assert touched == []


def test_the_refusal_is_logged_where_someone_will_see_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Thirteen days of silence is the defect. One line at ERROR is the fix.

    Read from real stderr rather than `caplog`, because `main` calls
    `configure_logging`, which replaces the root handlers — including the one
    caplog installs. Asserting through the configuration the worker actually
    runs with is the stronger test anyway: it is the output a person sees.
    """

    def refuse(_engine: Any) -> None:
        raise SchemaVersionMismatch("Refusing to start: expects abc, database is at xyz")

    monkeypatch.setattr(worker_main, "verify_schema_version", refuse)

    worker_main.main()

    assert "Refusing to start" in capsys.readouterr().err


def test_a_matching_schema_goes_on_to_build_a_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary path still starts. A gate that refuses everything is not a
    gate, and this is the assertion that would catch it."""
    started: list[str] = []

    class _Worker:
        def work(self, **_kwargs: Any) -> None:
            started.append("worked")

    class _Redis:
        @staticmethod
        def from_url(*_args: Any, **_kwargs: Any) -> object:
            return object()

    monkeypatch.setattr(worker_main, "verify_schema_version", lambda _engine: None)
    monkeypatch.setattr(worker_main, "Redis", _Redis)
    monkeypatch.setattr(worker_main, "build_worker", lambda *a, **k: _Worker())

    assert worker_main.main() == 0
    assert started == ["worked"]
