"""Per-request correlation context.

The request id is stored in a :class:`~contextvars.ContextVar` so error
handlers and log records can reference it without threading it through every
function signature.
"""

from __future__ import annotations

from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("jip_request_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()
