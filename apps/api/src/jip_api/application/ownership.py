"""Scoping helpers for user-owned data.

``docs/10-api-contracts.md`` requires every user-owned query to enforce
ownership. These helpers make the user id a required argument, so an unscoped
query has to be written deliberately rather than produced by forgetting a
``where`` clause.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import Select, select


class UserOwned(Protocol):
    """A model with a ``user_id`` column."""

    user_id: uuid.UUID


def owned[ModelT: UserOwned](model: type[ModelT], user_id: uuid.UUID) -> Select[tuple[ModelT]]:
    """Start a SELECT already scoped to ``user_id``.

    Prefer this over ``select(Model)`` in every repository. Filtering by a
    primary key alone is not enough: an id that belongs to another user would
    still match, which turns a guessable identifier into a data leak.
    """
    return select(model).where(model.user_id == user_id)  # type: ignore[arg-type]
