"""A named set of list filters.

The list already carries search, company, work mode, employment type,
seniority, processing status, archived state, an alignment band and a sort.
Reaching a subset is cheap; *returning* to one costs re-deriving the whole
combination from memory, and the combinations people care about are the ones
they invented — "remote, no blockers", "companies to watch", "career change".

Not a filter, then, but a place. The distinction matters for what gets stored:
a view keeps everything about the question and nothing about where the reader
had got to in the answer, so `page` is deliberately absent.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import TimestampMixin, UserOwnedMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base


class SavedJobView(TimestampMixin, UserOwnedMixin, Base):
    """One saved set of filters, named by the person who saved it."""

    __tablename__ = "saved_job_views"

    id: Mapped[uuid.UUID] = new_uuid_column()

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    """What the user calls it. Theirs, not derived from the filters.

    A generated name — "Remote · Senior · 70+" — would go stale the moment the
    filters were edited, and it would not say the thing the name is for. "Worth
    a second look" is not reconstructible from a query string.
    """

    filters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    """The query, as validated at save time.

    JSON rather than a column each, which is the opposite of the choice
    ``JobMatchItem`` makes two modules away — and for the reason that one gives.
    Its fields are columns because Phase 10's insights query *across* them:
    "which requirements are most often a gap" is a question about rows. Nothing
    asks a question across saved views. A view is only ever read whole, by the
    one person who owns it, and a column per filter would mean a migration
    every time the list grows one.

    ``page`` is never stored. A view is a question, and where somebody had got
    to in the answer is not part of it.
    """

    __table_args__ = (
        # One name per user. Two views called "Remote" is a list nobody can
        # navigate, and the second one silently wins.
        UniqueConstraint("user_id", "name", name="uq_saved_job_views_user_name"),
        CheckConstraint("length(trim(name)) > 0", name="saved_view_name_not_blank"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SavedJobView {self.name!r}>"
