"""Boards the user watches, and what those boards returned.

Two tables, and the second is deliberately not `jobs`.

A `DiscoveredPosting` is a **candidate**. Nobody chose it; a board returned it
because it exists. Putting those rows straight into the job library would mix
what the user decided to consider with what a scan happened to find, and the
library is the one list whose contents are supposed to mean "I am interested in
this". Once that stops being true, every count on the dashboard changes meaning
and nothing on screen says so.

So a scan writes here, a person promotes, and promotion is what creates a
`Job` — the same boundary the career profile already draws between an AI
proposal and a confirmed fact, for the same reason.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import TimestampMixin, UserOwnedMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base


class WatchedBoard(TimestampMixin, UserOwnedMixin, Base):
    """One company's board on one provider, that this user wants scanned.

    These endpoints are per-company: there is no global search across
    Greenhouse, only one board at a time. So discovery here means "watch these
    companies", which is a narrower promise than "search the market" and the
    only one the public APIs can actually keep.
    """

    __tablename__ = "watched_boards"

    id: Mapped[uuid.UUID] = new_uuid_column()

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    """`greenhouse`, `ashby`, `lever`. Not an enum column: the set grows
    whenever a provider module is added, and `jip_sources.PROVIDERS` is the
    authority on which names are real."""

    token: Mapped[str] = mapped_column(String(100), nullable=False)
    """The company's identifier on that provider. Validated against
    `BoardRef` before any scan uses it, because it is interpolated into a URL
    path."""

    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """What to call the company. Lever and Ashby never say, so without this a
    posting is attributed to a slug."""

    paused_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Paused rather than deleted, so a board can be taken out of a scan without
    losing the postings already discovered through it."""

    last_scanned_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Why the last scan of this board failed, in words safe to show. Cleared on
    success.

    Per board rather than per run on purpose. "We read four of your five" is
    only actionable if the screen can name the fifth, and an aggregate would let
    a company quietly stop being watched.
    """

    __table_args__ = (
        # One row per board per user. A second copy would double every posting
        # it returns and there is no reading under which that is wanted.
        UniqueConstraint("user_id", "provider", "token", name="uq_watched_board"),
    )

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None


class DiscoveredPosting(TimestampMixin, UserOwnedMixin, Base):
    """A posting a scan found, before anyone decided anything about it.

    Everything here is what the board said. There is deliberately no score, no
    requirement, no seniority and no role family: those are readings, they come
    from the analysis pipeline, and a posting only reaches that pipeline after a
    person promotes it into a `Job`.
    """

    __tablename__ = "discovered_postings"

    id: Mapped[uuid.UUID] = new_uuid_column()

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    board: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    """The board's own id, which is what makes a second scan recognise a posting
    it has already seen rather than offering it again."""

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Both, because the boards differ: Lever and Ashby send text, Greenhouse
    sends markup. Stored as they arrived. Extraction happens at promotion,
    through the same extractor a pasted page goes through."""

    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """`first_seen_at` never moves. It is the only thing that can later answer
    "has this company been reposting the same role for four months", which is
    Slice 3's strongest legitimacy signal and costs nothing to keep now."""

    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """The user said no. Kept rather than deleted so a later scan does not offer
    it back — a review list that resurrects what you have already rejected is
    one you stop reading."""

    promoted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The job this became, if a person promoted it.

    ``SET NULL`` rather than ``CASCADE``: deleting the job should not erase the
    record that this posting was found and acted on. The row then reads as
    reviewed with the job gone, which is what happened.
    """

    __table_args__ = (
        # What makes a re-scan idempotent. Without it every run offers the same
        # postings again and the review list is unusable by the second week.
        UniqueConstraint(
            "user_id", "provider", "board", "external_id", name="uq_discovered_posting"
        ),
        # The review list: this user's undismissed, unpromoted rows, newest
        # first. Scoped by user because an index on the dates alone would scan
        # every user's rows.
        Index("ix_discovered_user_first_seen", "user_id", "first_seen_at"),
    )

    @property
    def is_reviewed(self) -> bool:
        """Whether a person has decided about this row, either way."""
        return self.dismissed_at is not None or self.promoted_job_id is not None
