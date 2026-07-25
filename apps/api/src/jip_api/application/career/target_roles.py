"""Target role use cases.

Every function takes a ``user_id`` and scopes on it. A caller that knows another
user's row id still gets ``ResourceNotFoundError`` — the same answer as an id
that does not exist, so the API cannot be used to probe for what other users
own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jip_api.application.errors import DuplicateResourceError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.domain.career.models import Seniority, TargetRole

_UNSET = object()


@dataclass(slots=True)
class TargetRoleInput:
    """Fields for creating a target role."""

    title: str
    role_family: str | None = None
    desired_seniority: Seniority | None = None
    priority: int = 1
    is_active: bool = True
    notes: str | None = None


@dataclass(slots=True)
class TargetRoleUpdate:
    """Partial update. Unset fields are left alone; ``None`` clears them."""

    title: Any = field(default=_UNSET)
    role_family: Any = field(default=_UNSET)
    desired_seniority: Any = field(default=_UNSET)
    priority: Any = field(default=_UNSET)
    is_active: Any = field(default=_UNSET)
    notes: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("title", self.title),
                ("role_family", self.role_family),
                ("desired_seniority", self.desired_seniority),
                ("priority", self.priority),
                ("is_active", self.is_active),
                ("notes", self.notes),
            )
            if value is not _UNSET
        }


def list_target_roles(session: Session, user_id: uuid.UUID) -> list[TargetRole]:
    """Return the user's target roles, most important first.

    Ordered in the database rather than the client so every consumer — API, and
    later the matching engine — sees the same sequence.
    """
    statement = owned(TargetRole, user_id).order_by(
        asc(TargetRole.priority), asc(TargetRole.created_at)
    )
    return list(session.execute(statement).scalars())


def get_target_role(session: Session, user_id: uuid.UUID, role_id: uuid.UUID) -> TargetRole:
    """Return one target role, or raise if it is not this user's."""
    role = session.execute(
        owned(TargetRole, user_id).where(TargetRole.id == role_id)
    ).scalar_one_or_none()

    if role is None:
        raise ResourceNotFoundError("Target role not found.")
    return role


def create_target_role(session: Session, user_id: uuid.UUID, data: TargetRoleInput) -> TargetRole:
    """Create a target role, refusing a duplicate title for this user."""
    role = TargetRole(
        user_id=user_id,
        title=data.title,
        role_family=data.role_family,
        desired_seniority=data.desired_seniority,
        priority=data.priority,
        is_active=data.is_active,
        notes=data.notes,
    )
    session.add(role)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateResourceError(
            f"A target role titled {data.title!r} already exists."
        ) from exc

    return role


def update_target_role(
    session: Session, user_id: uuid.UUID, role_id: uuid.UUID, update: TargetRoleUpdate
) -> TargetRole:
    """Apply a partial update to one of the user's target roles."""
    role = get_target_role(session, user_id, role_id)

    for name, value in update.changes().items():
        setattr(role, name, value)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateResourceError("A target role with that title already exists.") from exc

    return role


def delete_target_role(session: Session, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
    """Delete one of the user's target roles."""
    role = get_target_role(session, user_id, role_id)
    session.delete(role)
    session.flush()
