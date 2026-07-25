"""Career profile entities."""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import TimestampMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base


class VerificationStatus(enum.StrEnum):
    """How much the platform trusts a piece of career data.

    From ``docs/03-domain-model.md``. Only ``USER_CONFIRMED`` and
    ``EVIDENCE_BACKED`` facts may be used automatically in resume claims
    (``docs/06-resume-engine.md``), so the distinction has to survive in the
    database rather than being inferred later.
    """

    UNVERIFIED = "UNVERIFIED"
    AI_INFERRED = "AI_INFERRED"
    USER_CONFIRMED = "USER_CONFIRMED"
    EVIDENCE_BACKED = "EVIDENCE_BACKED"


class CareerProfile(TimestampMixin, Base):
    """The user's professional summary. Exactly one per user.

    ``user_id`` is unique rather than merely indexed, which is what makes the
    one-to-one relationship a database guarantee instead of an application
    convention.

    Every field is optional: a profile is created empty on first read and filled
    in over time, so the shape must tolerate a user who has typed nothing yet.
    """

    __tablename__ = "career_profiles"

    id: Mapped[uuid.UUID] = new_uuid_column()

    # Declared here rather than via UserOwnedMixin because this table needs a
    # unique constraint on user_id, not the mixin's plain index.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    headline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    professional_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)

    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    """Profile links as ``[{"label": ..., "url": ...}]``.

    JSONB because nothing filters, sorts, or joins on these
    (``docs/03-domain-model.md``, JSONB principle). A dedicated table would add
    a join and a migration for every new link type, and buy nothing.
    """

    __table_args__ = (
        # A negative or absurd value is a data-entry error, and the database is
        # the only place that can refuse it regardless of which caller wrote it.
        # Named without the ck_/table prefix: the metadata naming convention in
        # infrastructure/db/base.py adds it, and spelling it here again produces
        # ck_career_profiles_ck_career_profiles_...
        CheckConstraint(
            "years_of_experience IS NULL OR (years_of_experience >= 0 "
            "AND years_of_experience <= 80)",
            name="years_of_experience_range",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CareerProfile id={self.id} user_id={self.user_id}>"
