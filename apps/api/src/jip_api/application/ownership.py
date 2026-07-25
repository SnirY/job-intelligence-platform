"""Scoping helpers for user-owned data.

``docs/10-api-contracts.md`` requires every user-owned query to enforce
ownership. These helpers make the user id a required argument, so an unscoped
query has to be written deliberately rather than produced by forgetting a
``where`` clause.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from jip_api.infrastructure.db.base import Base


def owned[ModelT: Base](model: type[ModelT], user_id: uuid.UUID) -> Select[tuple[ModelT]]:
    """Start a SELECT already scoped to ``user_id``.

    Prefer this over ``select(Model)`` in every repository. Filtering by a
    primary key alone is not enough: an id that belongs to another user would
    still match, which turns a guessable identifier into a data leak.

    Raises ``TypeError`` for a model that has no ``user_id``. Some tables are
    deliberately global — the canonical ``skills`` catalogue is shared by every
    user — and scoping one of those by user would quietly return nothing rather
    than failing, so it is caught here instead.
    """
    user_column = getattr(model, "user_id", None)
    if user_column is None:
        raise TypeError(
            f"{model.__name__} has no user_id column, so it cannot be scoped to a user. "
            "Global tables must be queried with select() directly."
        )
    return select(model).where(user_column == user_id)
