"""Traceability for every model call.

``docs/09-mvp-roadmap.md`` gates AI features on an ``AIRun`` trace, and
``docs/03-domain-model.md`` fixes its fields. The row is written whether the
call succeeded or failed — a trace that only records successes cannot answer
the two questions it exists for: what did this cost, and why did that document
never parse.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.domain.common import StrEnumType, TimestampMixin, new_uuid_column
from jip_api.infrastructure.db.base import Base


class AIRunStatus(enum.StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AIRun(TimestampMixin, Base):
    """One attempt at one AI operation."""

    __tablename__ = "ai_runs"

    id: Mapped[uuid.UUID] = new_uuid_column()

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Who the call was made for.

    ``SET NULL`` rather than ``CASCADE``: deleting a user must remove their
    career data, but the cost and reliability record of calls already paid for
    is operational history, not personal profile data.
    """

    operation: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    """Routed operation, e.g. ``RESUME_PARSE``. Matches ``jip_ai.AIOperation``."""

    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)

    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    """SHA-256 over prompt version, model, and rendered input.

    ``docs/10-api-contracts.md`` asks for input hashes on expensive repeatable
    operations. Re-uploading the same resume then reuses the stored result
    instead of paying for an identical call.
    """

    status: Mapped[AIRunStatus] = mapped_column(StrEnumType(AIRunStatus, 20), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    """Numeric, not float: costs are summed for reporting, and binary floating
    point makes those sums disagree with themselves."""

    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __table_args__ = (
        CheckConstraint("length(input_hash) = 64", name="input_hash_length"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AIRun id={self.id} operation={self.operation} status={self.status}>"
