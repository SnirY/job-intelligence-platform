"""PostgreSQL access: declarative base, engine, and session lifecycle."""

from jip_api.infrastructure.db.base import Base
from jip_api.infrastructure.db.session import get_engine, get_session, session_scope

__all__ = ["Base", "get_engine", "get_session", "session_scope"]
