"""Map a verified external identity onto the internal user record.

Takes a provider-neutral :class:`VerifiedIdentity`, so this layer does not know
or care which issuer authenticated the request.

Provisioning is just-in-time: the first authenticated request for an unknown
subject creates the row. It must be idempotent — a user signing in repeatedly,
or issuing two requests at once, must end up with exactly one account.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jip_api.domain.users.models import User
from jip_api.infrastructure.auth.oidc import VerifiedIdentity

logger = logging.getLogger(__name__)


def provision_user(session: Session, identity: VerifiedIdentity, *, provider: str) -> User:
    """Return the internal user for ``identity``, creating it if needed.

    ``identity`` must come from a verified token. Passing unverified claims here
    would make account selection attacker-controlled.
    """
    user = _find_by_identity(session, identity.subject, provider)
    if user is None:
        user = _insert_idempotently(session, identity, provider)

    if _sync_profile(user, identity):
        session.flush()

    return user


def _find_by_identity(session: Session, subject: str, provider: str) -> User | None:
    return session.execute(
        select(User).where(User.auth_provider == provider, User.external_user_id == subject)
    ).scalar_one_or_none()


def _insert_idempotently(session: Session, identity: VerifiedIdentity, provider: str) -> User:
    """Insert the user, tolerating a concurrent insert of the same identity.

    ``ON CONFLICT DO NOTHING`` makes this atomic in one statement: if a
    simultaneous request already created the row, this insert affects nothing
    and returns no row, and we read the winner's row instead. A read-then-insert
    without the constraint would let both requests create an account and split
    one person's data across two of them.
    """
    statement = (
        pg_insert(User)
        .values(
            auth_provider=provider,
            external_user_id=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )
        .on_conflict_do_nothing(
            index_elements=[User.auth_provider, User.external_user_id],
        )
        .returning(User)
    )

    inserted = session.execute(statement).scalar_one_or_none()
    if inserted is not None:
        logger.info("Provisioned user", extra={"auth_provider": provider})
        return inserted

    existing = _find_by_identity(session, identity.subject, provider)
    if existing is None:  # pragma: no cover - would mean the unique constraint vanished
        raise RuntimeError(
            "user could neither be inserted nor found; the unique constraint on "
            "(auth_provider, external_user_id) may be missing"
        )
    return existing


def _sync_profile(user: User, identity: VerifiedIdentity) -> bool:
    """Refresh cached profile fields from the token. Returns True if changed.

    An absent claim never clears a stored value. Many issuers — Clerk's default
    session token among them — carry no email or name, so treating "absent" as
    "empty" would wipe the cache on every request.
    """
    changed = False

    if identity.email is not None and identity.email != user.email:
        user.email = identity.email
        changed = True

    if identity.display_name is not None and identity.display_name != user.display_name:
        user.display_name = identity.display_name
        changed = True

    return changed
