"""Scanning a user's watched boards.

Background work for the plainest reason: it is several HTTP requests to servers
this system does not control, and one slow board would otherwise hold an HTTP
request open until something upstream gave up.

Keyed on the *user* rather than on a processing job, like the URL import and
unlike the analysis. `run_job_analysis`'s docstring gives the distinction and it
holds here: an analysis is an attempt that can fail, be retried and be counted,
while a scan writes its outcome across the rows it touched — each board's
`last_scanned_at` and `last_error`, and the postings themselves.
"""

from __future__ import annotations

import logging
import uuid

from jip_api.application.discovery.scanning import run_scan
from jip_api.infrastructure.db.session import new_session
from jip_config import get_settings

logger = logging.getLogger(__name__)


def run_board_scan(user_id: str) -> dict[str, object]:
    """Scan every board this user watches and is not pausing.

    Never raises for an expected failure. A board that is unreachable or
    misconfigured is recorded against that board inside `run_scan` and the rest
    of the scan continues — ten watched companies must not become zero postings
    because one is having an outage.
    """
    settings = get_settings()
    session = new_session()

    try:
        try:
            outcome = run_scan(
                session,
                uuid.UUID(user_id),
                timeout_seconds=settings.job_fetch_timeout_seconds,
            )
        except Exception:
            # A defect here rather than a board failing. Roll back rather than
            # commit a partial scan: half a board's postings written with the
            # board's `last_scanned_at` updated would read as a completed run
            # that found less than it did.
            session.rollback()
            logger.exception("Board scan raised unexpectedly", extra={"user_id": user_id})
            return {"user_id": user_id, "status": "FAILED", "error_code": "INTERNAL_ERROR"}

        session.commit()
        return {
            "user_id": user_id,
            "status": "COMPLETED",
            "boards_read": outcome.boards_read,
            "boards_failed": outcome.boards_failed,
            "postings_found": outcome.postings_found,
            "postings_new": outcome.postings_new,
        }
    finally:
        session.close()
