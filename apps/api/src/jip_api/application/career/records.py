"""CRUD for the user-owned career history records.

Experience, projects, and education differ in their fields but not in their
lifecycle: list mine, fetch one of mine, create, patch, delete. Writing that
three times would mean three chances to forget the ownership filter, which is
the one mistake here that is a data leak rather than a bug.

Field-level rules stay in each entity's own module; only the shape is shared.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import UnaryExpression
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jip_api.application.errors import DuplicateResourceError, ResourceNotFoundError
from jip_api.application.ownership import owned
from jip_api.infrastructure.db.base import Base


def list_owned[ModelT: Base](
    session: Session,
    model: type[ModelT],
    user_id: uuid.UUID,
    *order_by: UnaryExpression[Any],
) -> list[ModelT]:
    """Return every row of ``model`` belonging to ``user_id``."""
    statement = owned(model, user_id)
    if order_by:
        statement = statement.order_by(*order_by)
    return list(session.execute(statement).scalars())


def get_owned[ModelT: Base](
    session: Session,
    model: type[ModelT],
    user_id: uuid.UUID,
    record_id: uuid.UUID,
    *,
    missing_message: str,
) -> ModelT:
    """Return one row belonging to ``user_id``, or raise.

    Scoped by user *and* id. Filtering on the id alone would match another
    user's row, turning a guessable identifier into a data leak — and the error
    is identical whether the row is missing or simply not theirs, so the API
    cannot be used to enumerate what others own.
    """
    record = session.execute(
        owned(model, user_id).where(model.id == record_id)  # type: ignore[attr-defined]
    ).scalar_one_or_none()
    if record is None:
        raise ResourceNotFoundError(missing_message)
    return record


def create_owned[ModelT: Base](
    session: Session,
    record: ModelT,
    *,
    conflict_message: str,
) -> ModelT:
    """Persist a new row, translating a constraint clash into a 409."""
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateResourceError(conflict_message) from exc
    return record


def apply_changes(session: Session, record: object, changes: dict[str, Any]) -> None:
    """Apply a partial update and flush."""
    for name, value in changes.items():
        setattr(record, name, value)
    session.flush()


def delete_owned(session: Session, record: object) -> None:
    session.delete(record)
    session.flush()
