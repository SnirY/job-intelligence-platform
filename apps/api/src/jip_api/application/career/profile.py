"""Career profile use cases."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jip_api.application.ownership import owned
from jip_api.domain.career.models import CareerProfile

logger = logging.getLogger(__name__)

_UNSET = object()


@dataclass(slots=True)
class ProfileUpdate:
    """A partial update to the profile.

    Every field defaults to a sentinel rather than ``None``, because the API is
    a PATCH: "not mentioned" and "explicitly cleared" are different intents, and
    collapsing them would make it impossible to erase a headline once set.
    """

    headline: Any = field(default=_UNSET)
    professional_summary: Any = field(default=_UNSET)
    years_of_experience: Any = field(default=_UNSET)
    current_location: Any = field(default=_UNSET)
    links: Any = field(default=_UNSET)

    def changes(self) -> dict[str, Any]:
        """Return only the fields the caller actually supplied."""
        return {
            name: value
            for name, value in (
                ("headline", self.headline),
                ("professional_summary", self.professional_summary),
                ("years_of_experience", self.years_of_experience),
                ("current_location", self.current_location),
                ("links", self.links),
            )
            if value is not _UNSET
        }


def get_or_create_profile(session: Session, user_id: uuid.UUID) -> CareerProfile:
    """Return the user's profile, creating an empty one on first read.

    Creating on demand keeps a null profile out of every downstream consumer.
    The insert tolerates a concurrent create for the same reason user
    provisioning does — two parallel first requests must not produce two rows,
    and the unique constraint on ``user_id`` is what enforces it.
    """
    profile = session.execute(owned(CareerProfile, user_id)).scalar_one_or_none()
    if profile is not None:
        return profile

    statement = (
        pg_insert(CareerProfile)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=[CareerProfile.user_id])
        .returning(CareerProfile)
    )
    created = session.execute(statement).scalar_one_or_none()
    if created is not None:
        logger.info("Created empty career profile")
        return created

    existing = session.execute(owned(CareerProfile, user_id)).scalar_one_or_none()
    if existing is None:  # pragma: no cover - would mean the unique constraint vanished
        raise RuntimeError(
            "career profile could neither be inserted nor found; the unique "
            "constraint on career_profiles.user_id may be missing"
        )
    return existing


def update_profile(session: Session, user_id: uuid.UUID, update: ProfileUpdate) -> CareerProfile:
    """Apply a partial update and return the profile.

    Scoped by ``user_id``, so a caller cannot reach another user's profile even
    if they learn its id — the id is never accepted as an input.
    """
    profile = get_or_create_profile(session, user_id)

    for name, value in update.changes().items():
        setattr(profile, name, value)

    session.flush()
    return profile
