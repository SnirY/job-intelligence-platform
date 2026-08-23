"""Ashby job boards.

``GET https://api.ashbyhq.com/posting-api/job-board/{name}``

Public and unauthenticated. Like Lever, the payload does not name the company,
so that comes from configuration or the board name.

The field that matters and has no equivalent elsewhere is `isListed`. Ashby
returns roles that are not on the public board — drafts, internal postings, and
roles taken down but not deleted. **An unlisted posting is skipped.** Importing
one would put a job in front of the user that they cannot apply to and, worse,
that nobody published.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from jip_sources.http import DEFAULT_TIMEOUT_SECONDS, get_json
from jip_sources.models import BoardRef, RawPosting
from jip_sources.parsing import as_text, iso_datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class AshbySource:
    name = "ashby"

    def fetch(
        self, board: BoardRef, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Sequence[RawPosting]:
        payload = get_json(f"{BASE_URL}/{board.token}", timeout_seconds=timeout_seconds)
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            logger.warning("Ashby board returned no job list", extra={"board": board.token})
            return []

        postings: list[RawPosting] = []
        for row in rows:
            posting = _read(row, board)
            if posting is not None:
                postings.append(posting)
        return postings


def _read(row: Any, board: BoardRef) -> RawPosting | None:
    if not isinstance(row, dict):
        return None

    # Absent rather than false is treated as listed: the field has been present
    # on every response observed, and a board that stopped sending it should not
    # silently produce zero postings. A row that says `false` is honoured.
    if row.get("isListed") is False:
        return None

    identifier = as_text(row.get("id"))
    title = as_text(row.get("title"))
    url = as_text(row.get("jobUrl")) or as_text(row.get("applyUrl"))
    if not identifier or not title or not url:
        return None

    return RawPosting(
        provider="ashby",
        board=board.token,
        external_id=identifier,
        title=title,
        url=url,
        company=board.label or board.token,
        # A plain string here, unlike Greenhouse's object. `secondaryLocations`
        # is deliberately not merged in: the posting names a primary location,
        # and concatenating the others would invent a place the posting does
        # not claim the role is.
        location=as_text(row.get("location")),
        posted_at=iso_datetime(row.get("publishedAt")),
        description_text=as_text(row.get("descriptionPlain")),
        description_html=as_text(row.get("descriptionHtml")),
    )
