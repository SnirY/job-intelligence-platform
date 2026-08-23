"""Lever job boards.

``GET https://api.lever.co/v0/postings/{site}?mode=json``

Public and unauthenticated. The response is a bare JSON array rather than an
object with a `jobs` key, which is worth knowing before reading the parsing
below.

Lever gives the posting as both markup and plain text, so both travel. It does
not say which company the board belongs to — every other field is about the
role — so the company name comes from configuration or from the site token.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from jip_sources.http import DEFAULT_TIMEOUT_SECONDS, get_json
from jip_sources.models import BoardRef, RawPosting
from jip_sources.parsing import as_text, epoch_datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings"


class LeverSource:
    name = "lever"

    def fetch(
        self, board: BoardRef, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Sequence[RawPosting]:
        payload = get_json(f"{BASE_URL}/{board.token}?mode=json", timeout_seconds=timeout_seconds)
        if not isinstance(payload, list):
            logger.warning("Lever board returned no posting list", extra={"board": board.token})
            return []

        postings: list[RawPosting] = []
        for row in payload:
            posting = _read(row, board)
            if posting is not None:
                postings.append(posting)
        return postings


def _read(row: Any, board: BoardRef) -> RawPosting | None:
    if not isinstance(row, dict):
        return None

    identifier = as_text(row.get("id"))
    # `text` is Lever's name for the title. Not renamed on the way in beyond
    # this, because the mapping belongs here rather than in a shared shape.
    title = as_text(row.get("text"))
    # `hostedUrl` is the posting; `applyUrl` is the form. The posting is what a
    # person wants to read, and the form is reachable from it.
    url = as_text(row.get("hostedUrl")) or as_text(row.get("applyUrl"))
    if not identifier or not title or not url:
        return None

    categories = row.get("categories")
    location = as_text(categories.get("location")) if isinstance(categories, dict) else None

    return RawPosting(
        provider="lever",
        board=board.token,
        external_id=identifier,
        title=title,
        url=url,
        # Lever's payload never names the company, so this is configuration or
        # the token — and the token is the company's own slug, which is a
        # reasonable last resort rather than a guess.
        company=board.label or board.token,
        location=location,
        posted_at=epoch_datetime(row.get("createdAt")),
        description_text=as_text(row.get("descriptionPlain")),
        description_html=as_text(row.get("description")),
    )
