"""Greenhouse job boards.

``GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true``

Public, unauthenticated, and documented. `content=true` is not optional for our
purposes: without it the response carries titles and links but no posting text,
and a posting with no text cannot be analysed — it would arrive as a row the
user has to go and fetch by hand, which is the problem discovery exists to
remove.

Greenhouse returns the posting as **HTML-escaped HTML**: the body is markup, and
that markup arrives entity-encoded. One `html.unescape` puts it back to markup,
which is what `description_html` means. Turning it into text is the caller's
job, through the same extractor a pasted page goes through.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from collections.abc import Sequence
from typing import Any

from jip_sources.http import DEFAULT_TIMEOUT_SECONDS, get_json
from jip_sources.models import BoardRef, RawPosting
from jip_sources.parsing import as_text, iso_datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
"""Fixed here and never configurable. The only variable in the URL is the board
token, which `BoardRef` validates before it can exist."""


class GreenhouseSource:
    name = "greenhouse"

    def fetch(
        self, board: BoardRef, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Sequence[RawPosting]:
        payload = get_json(
            f"{BASE_URL}/{board.token}/jobs?content=true", timeout_seconds=timeout_seconds
        )
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            logger.warning("Greenhouse board returned no job list", extra={"board": board.token})
            return []

        postings: list[RawPosting] = []
        for row in rows:
            posting = _read(row, board)
            if posting is not None:
                postings.append(posting)
        return postings


def _read(row: Any, board: BoardRef) -> RawPosting | None:
    """One row, or ``None`` if it is not usable.

    Skipped rather than raised: one malformed posting should cost that posting,
    not the other ninety-nine on the board.
    """
    if not isinstance(row, dict):
        return None

    identifier = row.get("id")
    title = as_text(row.get("title"))
    url = as_text(row.get("absolute_url"))
    if identifier is None or not title or not url:
        return None

    # `location` is an object with a `name`, and that name is frequently a list
    # of offices joined by semicolons and pipes. Kept exactly as written: it is
    # what the posting says, and splitting it into somewhere specific would be
    # this system deciding where the job is.
    location = row.get("location")
    location_name = as_text(location.get("name")) if isinstance(location, dict) else None

    content = row.get("content")
    markup = html.unescape(content) if isinstance(content, str) and content else None

    return RawPosting(
        provider="greenhouse",
        board=board.token,
        external_id=str(identifier),
        title=title,
        url=url,
        company=as_text(row.get("company_name")) or board.label,
        location=location_name,
        # `first_published` is when the posting went up; `updated_at` moves
        # whenever anyone edits it. The first is the one a reader means by "how
        # old is this", so it leads and the other is only a fallback.
        posted_at=_posted(row),
        description_html=markup,
    )


def _posted(row: dict[str, Any]) -> dt.datetime | None:
    return iso_datetime(row.get("first_published")) or iso_datetime(row.get("updated_at"))
