"""The internal user record.

The authentication provider owns *identity* — credentials, email verification,
MFA, recovery. This table owns the *domain user*: the thing every user-owned row
in the database points at.

The two are joined by ``(auth_provider, external_user_id)``, and nothing else in
the schema may reference those columns. See
``docs/adr/0004-clerk-as-authentication-provider.md`` and
``docs/adr/0005-provider-neutral-identity-boundary.md``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from jip_api.infrastructure.db.base import Base


class User(Base):
    """A user of the platform.

    ``email`` and ``display_name`` are a *cache* of what Clerk knows, refreshed
    from verified token claims when those claims are present. They are nullable
    because Clerk's default session token carries neither; surfacing them
    requires a custom session-token claim, and inventing values would be worse
    than leaving them empty. Identity never depends on them —
    ``docs/03-domain-model.md`` lists them on User, but an email address is a
    mutable attribute, not a stable identifier.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Scoping uniqueness to the provider is what makes a future migration
        # tractable: users from a new issuer can be inserted alongside the old
        # ones, rather than colliding on a bare subject string.
        UniqueConstraint("auth_provider", "external_user_id", name="uq_users_external_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    """Internal identifier. Every user-owned foreign key points here.

    Deliberately not the provider's id: keeping the domain key independent means
    changing providers rewrites one column instead of every foreign key in the
    database.
    """

    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    """Which issuer vouched for this person, e.g. ``clerk``.

    Recorded per row rather than assumed globally, so a migration can run with
    both providers live instead of requiring a flag day.
    """

    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    """The provider's identifier for this person — the verified ``sub`` claim.

    The unique constraint above is what makes provisioning idempotent under
    concurrency: two simultaneous first requests race, one inserts, the other is
    rejected and re-reads. Without it, the loser would create a duplicate user
    and silently split that person's data across two accounts.
    """

    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} provider={self.auth_provider!r}>"
