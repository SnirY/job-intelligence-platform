"""API-side logging setup.

Reuses the shared JSON formatter and adds the current request id to every
record, so a failing request can be traced across all lines it produced.
"""

from __future__ import annotations

import logging

from jip_api.core.context import get_request_id
from jip_config import configure_logging as configure_shared_logging


class RequestIdFilter(logging.Filter):
    """Attach the active request id to records that have one."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        if request_id is not None:
            record.request_id = request_id
        return True


def configure_logging(level: str = "INFO") -> None:
    """Install JSON logging with request correlation."""
    configure_shared_logging(level, filters=[RequestIdFilter()])
