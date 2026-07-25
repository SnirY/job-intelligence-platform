"""Structured logging shared by the API and the worker.

Logs are emitted as single-line JSON so they stay greppable locally and remain
machine-parseable once shipped to a log aggregator. Any extra attributes
attached to a record — by ``logger.info(..., extra={...})`` or by a filter — are
merged into the JSON object, which is how per-process correlation fields such as
a request id get in without this module knowing about them.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Iterable
from typing import Any

_RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS:
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO",
    *,
    filters: Iterable[logging.Filter] = (),
) -> None:
    """Install the JSON formatter on the root logger.

    Existing handlers are replaced so third-party frameworks (uvicorn, RQ) do not
    emit a second, differently shaped copy of every line.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    for log_filter in filters:
        handler.addFilter(log_filter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "rq.worker"):
        third_party = logging.getLogger(name)
        third_party.handlers = []
        third_party.propagate = True
