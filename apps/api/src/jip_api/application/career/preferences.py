"""Career preference use cases.

Mirrors ``career.profile``: one row per user, created empty on first read, and
patched with sentinels so "not mentioned" stays distinct from "cleared".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jip_api.application.ownership import owned
from jip_api.domain.career.models import CareerPreferences

logger = logging.getLogger(__name__)

_UNSET = object()


@dataclass(slots=True)
class PreferencesUpdate:
    """A partial update.

    Same sentinel scheme as ``ProfileUpdate``, and it matters more here: with a
    plain ``None`` default there would be no way to express "I no longer care
    where the job is" as distinct from "leave my locations alone".
    """

    work_modes: Any = field(default=_UNSET)
    employment_types: Any = field(default=_UNSET)
    locations: Any = field(default=_UNSET)
    open_to_relocation: Any = field(default=_UNSET)
    salary_min: Any = field(default=_UNSET)
    salary_currency: Any = field(default=_UNSET)
    excluded_role_families: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        """Only the fields the caller actually supplied."""
        return {
            name: value
            for name, value in (
                ("work_modes", self.work_modes),
                ("employment_types", self.employment_types),
                ("locations", self.locations),
                ("open_to_relocation", self.open_to_relocation),
                ("salary_min", self.salary_min),
                ("salary_currency", self.salary_currency),
                ("excluded_role_families", self.excluded_role_families),
            )
            if value is not _UNSET
        }


def get_or_create_preferences(session: Session, user_id: uuid.UUID) -> CareerPreferences:
    """Return the user's preferences, creating an empty row on first read.

    Returning an all-empty record rather than 404 is the contract in
    ``docs/10-api-contracts.md``, and it is not a convenience: *no constraints*
    and *no preferences exist* are different answers, and only the first is true
    of someone who has not opened the screen.

    The insert tolerates a concurrent create for the reason
    ``get_or_create_profile`` gives — two parallel first requests must not
    produce two rows, and the unique constraint on ``user_id`` enforces it.
    """
    preferences = session.execute(owned(CareerPreferences, user_id)).scalar_one_or_none()
    if preferences is not None:
        return preferences

    statement = (
        pg_insert(CareerPreferences)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=[CareerPreferences.user_id])
        .returning(CareerPreferences)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        logger.info("Created empty career preferences")
        return created

    existing = session.execute(owned(CareerPreferences, user_id)).scalar_one_or_none()
    if existing is None:  # pragma: no cover - would mean the unique constraint vanished
        raise RuntimeError(
            "career preferences could neither be inserted nor found; the unique "
            "constraint on career_preferences.user_id may be missing"
        )
    return existing


def update_preferences(
    session: Session, user_id: uuid.UUID, update: PreferencesUpdate
) -> CareerPreferences:
    """Apply a partial update and return the row."""
    preferences = get_or_create_preferences(session, user_id)

    for name, value in update.changes().items():
        setattr(preferences, name, value)

    session.flush()
    # Field *names* only. What a person will accept for pay, and where they will
    # not move, is exactly the kind of detail `docs/11-engineering-standards.md`
    # keeps out of logs.
    logger.info("Updated career preferences", extra={"fields": sorted(update.changes())})
    return preferences
