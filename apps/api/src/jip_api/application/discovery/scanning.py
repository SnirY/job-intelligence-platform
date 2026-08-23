"""Running a scan, and writing down what came back.

```text
Watched boards -> jip_sources.scan -> upsert postings -> record per board
```

Two rules govern everything here, and both are about not undoing a person's
decision.

**A re-scan never resurrects a dismissed posting.** Boards return the same open
role every time they are read. If seeing it again cleared `dismissed_at`, the
review list would hand back everything the user has already rejected, and a
review list that does that is one you stop opening after a week.

**`first_seen_at` never moves.** It is the only field that can later answer "has
this company been reposting the same role for four months" — Slice 3's strongest
legitimacy signal — and a scan that refreshed it would erase that permanently
and silently.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.domain.discovery.models import DiscoveredPosting, WatchedBoard
from jip_sources import BoardRef, InvalidBoard, RawPosting, scan

logger = logging.getLogger(__name__)

SCAN_TASK = "jip_worker.tasks.discovery.run_board_scan"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """What one run produced, for the caller to report."""

    boards_read: int
    boards_failed: int
    postings_found: int
    """Every posting the boards returned, including ones already known."""

    postings_new: int
    """The number the user has not been offered before. This is the figure worth
    showing: "142 postings" after the third scan of the same boards would be a
    number that says nothing."""


def run_scan(
    session: Session,
    user_id: uuid.UUID,
    *,
    timeout_seconds: float = 15.0,
    now: dt.datetime | None = None,
) -> ScanOutcome:
    """Scan every board this user watches and is not pausing."""
    moment = now or dt.datetime.now(tz=dt.UTC)
    boards = list(
        session.scalars(
            select(WatchedBoard).where(
                WatchedBoard.user_id == user_id, WatchedBoard.paused_at.is_(None)
            )
        )
    )
    if not boards:
        return ScanOutcome(boards_read=0, boards_failed=0, postings_found=0, postings_new=0)

    by_key: dict[tuple[str, str], WatchedBoard] = {}
    refs: list[BoardRef] = []

    for board in boards:
        try:
            refs.append(BoardRef(board.provider, board.token, label=board.label))
        except InvalidBoard as error:
            # A token that cannot be put in a URL. Recorded on the board so the
            # user can fix it, rather than dropped — a board that silently stops
            # being scanned is the failure mode this whole module avoids.
            board.last_error = str(error)
            board.last_scanned_at = moment
            continue
        by_key[(board.provider, board.token)] = board

    result = scan(refs, timeout_seconds=timeout_seconds)

    new_count = 0
    for outcome in result.outcomes:
        board = by_key[(outcome.board.provider, outcome.board.token)]
        board.last_scanned_at = moment
        board.last_error = outcome.error

        for posting in outcome.postings:
            if _upsert(session, user_id, posting, now=moment):
                new_count += 1

    session.flush()

    logger.info(
        "Board scan finished",
        extra={
            "user_id": str(user_id),
            "boards": len(result.outcomes),
            "failed": len(result.failures),
            "new": new_count,
        },
    )
    return ScanOutcome(
        boards_read=len(result.outcomes) - len(result.failures),
        boards_failed=len(result.failures) + (len(boards) - len(refs)),
        postings_found=len(result.postings),
        postings_new=new_count,
    )


def _upsert(session: Session, user_id: uuid.UUID, posting: RawPosting, *, now: dt.datetime) -> bool:
    """Store one posting. Returns whether it had never been seen before.

    An existing row has its description and title refreshed, because a company
    does edit a posting after publishing it and the newer text is the one worth
    reading. What is never touched is anything recording a decision or a
    history: `first_seen_at`, `dismissed_at`, `promoted_job_id`.
    """
    existing = session.scalars(
        select(DiscoveredPosting).where(
            DiscoveredPosting.user_id == user_id,
            DiscoveredPosting.provider == posting.provider,
            DiscoveredPosting.board == posting.board,
            DiscoveredPosting.external_id == posting.external_id,
        )
    ).one_or_none()

    if existing is not None:
        existing.last_seen_at = now
        existing.title = posting.title
        existing.url = posting.url
        existing.location = posting.location
        existing.description_text = posting.description_text
        existing.description_html = posting.description_html
        return False

    session.add(
        DiscoveredPosting(
            user_id=user_id,
            provider=posting.provider,
            board=posting.board,
            external_id=posting.external_id,
            title=posting.title,
            url=posting.url,
            company=posting.company,
            location=posting.location,
            posted_at=posting.posted_at,
            description_text=posting.description_text,
            description_html=posting.description_html,
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    return True
