"""Engine and session management.

The engine is created lazily and cached per process. FastAPI route handlers that
touch the database are declared with ``def`` (not ``async def``) so Starlette
runs them in a worker thread — the SQLAlchemy engine here is synchronous.
See ``docs/adr/0002-synchronous-sqlalchemy-for-phase-0.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from jip_config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={
            # Bounded so an unreachable database surfaces as an error rather
            # than a request that hangs until some upstream proxy gives up.
            "connect_timeout": settings.connect_timeout_seconds,
            # Every connection reads and writes timestamps in UTC.
            #
            # `docs/10-api-contracts.md` requires ISO 8601 UTC in the API, and
            # without this a `timestamptz` comes back in the *server's* local
            # zone: the same instant is serialised as "…04:44:35Z" when it was
            # just set in Python and "…07:44:35+03:00" once reloaded. Both are
            # correct instants, which is what makes it easy to miss, and a
            # client comparing the two strings sees a change that never
            # happened.
            "options": "-c timezone=utc",
        },
    )


@lru_cache(maxsize=1)
def _get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def new_session() -> Session:
    """Return an unmanaged session for a caller that owns its own transactions.

    The worker needs this: a background task commits at several points so a
    later failure does not discard earlier work, which neither the request-scoped
    dependency nor ``session_scope`` allows.
    """
    return _get_session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for use outside the request cycle (worker, scripts).

    Commits on success and rolls back on failure so a partially applied unit of
    work is never left behind.
    """
    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Dispose the cached engine and drop the cached factories.

    Disposing first matters: abandoning a pool leaves open sockets for the
    garbage collector to finalise, and psycopg reports that as an unraisable
    exception at an unrelated moment. Used by tests that reconfigure the
    database URL, and on process shutdown.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    _get_session_factory.cache_clear()
