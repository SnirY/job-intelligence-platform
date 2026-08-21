"""Saving a set of list filters, and reading it back honestly.

The interesting part is not the storage. It is what happens when a view is read
back by a version of the app that no longer understands one of the filters it
was saved with.

A stored view is a promise about which jobs the user will see. If a key that no
longer parses were quietly dropped, the promise would be broken silently: the
list would come back *wider* than the name says, and nothing on screen would
admit it. The same failure as showing a job with no score at the bottom of a
ranking — a narrower claim turned into a broader one by omission.

So a view that cannot be read is returned as unreadable, with the keys that
caused it, and the screen says so rather than running it.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jip_api.application.errors import ResourceNotFoundError
from jip_api.application.jobs.queries import MAX_PAGE_SIZE, ArchivedFilter, JobSort
from jip_api.application.ownership import owned
from jip_api.core.errors import ConflictError
from jip_api.domain.career.history import EmploymentType
from jip_api.domain.career.models import Seniority
from jip_api.domain.jobs.models import JobProcessingStatus, WorkMode
from jip_api.domain.jobs.saved_views import SavedJobView

MAX_VIEWS = 40
"""Enough for anybody, and low enough that the row of chips stays a row.

Not a storage limit — forty JSON blobs is nothing. It is a limit on how many
things can be offered at once before offering them stops helping.
"""

# Everything a view is allowed to remember. `page` is absent on purpose: a view
# is a question, and where the reader had got to in the answer is not part of it.
STORABLE = frozenset(
    {
        "search",
        "company",
        "work_mode",
        "employment_type",
        "seniority",
        "status",
        "archived",
        "sort",
        "min_score",
        "max_score",
        "page_size",
    }
)


@dataclass(frozen=True, slots=True)
class ReadView:
    """A stored view, and whether this version of the app can still run it."""

    view: SavedJobView
    unreadable: list[str]

    @property
    def is_readable(self) -> bool:
        return not self.unreadable


def list_views(session: Session, user_id: uuid.UUID) -> list[ReadView]:
    """Every view the user has, oldest first, each checked against the filters
    this version actually supports."""
    rows = session.execute(
        owned(SavedJobView, user_id).order_by(SavedJobView.created_at, SavedJobView.id)
    ).scalars()
    return [ReadView(view=row, unreadable=unreadable_keys(row.filters)) for row in rows]


# The enums a stored value has to still be a member of. Checked against the
# same types the route coerces its query parameters into, because that is what
# decides whether a filter runs — `JobFilters` is a plain dataclass and would
# happily hold a seniority nobody has heard of.
_ENUMS: dict[str, type[enum.StrEnum]] = {
    "work_mode": WorkMode,
    "employment_type": EmploymentType,
    "seniority": Seniority,
    "status": JobProcessingStatus,
    "archived": ArchivedFilter,
    "sort": JobSort,
}

_BOUNDED = {
    "min_score": (0, 100),
    "max_score": (0, 100),
    "page_size": (1, MAX_PAGE_SIZE),
}


def unreadable_keys(filters: dict[str, object]) -> list[str]:
    """Which stored keys this version can no longer honour.

    Three ways a key fails, and they are one failure: the filter would not run
    as saved. A key the app no longer has, an enum member that has since been
    removed, and a number outside the range the route accepts.

    A view naming a seniority that no longer exists is exactly as broken as one
    naming a filter that no longer exists, because running either returns a
    different set of jobs from the one the name promises.
    """
    broken: set[str] = {key for key in filters if key not in STORABLE}

    for key, value in filters.items():
        if key in broken or value is None:
            continue

        member = _ENUMS.get(key)
        if member is not None and value not in {option.value for option in member}:
            broken.add(key)
            continue

        bounds = _BOUNDED.get(key)
        if bounds is not None:
            low, high = bounds
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                broken.add(key)

    return sorted(broken)


def create_view(
    session: Session, user_id: uuid.UUID, *, name: str, filters: dict[str, object]
) -> SavedJobView:
    """Save a view, refusing a name that is already taken.

    Refused rather than overwritten. Two things a user might mean by saving
    over a name — "update this" and "I forgot I had one" — and picking the
    destructive reading for them is not a guess worth making silently.
    """
    cleaned = clean(filters)
    trimmed = name.strip()

    existing = session.execute(
        owned(SavedJobView, user_id).where(SavedJobView.name == trimmed)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"You already have a view called {trimmed!r}.")

    count = len(list(session.execute(owned(SavedJobView, user_id)).scalars()))
    if count >= MAX_VIEWS:
        raise ConflictError(
            f"That would be view {count + 1}. Delete one first — "
            f"{MAX_VIEWS} is as many as the screen can offer usefully."
        )

    view = SavedJobView(user_id=user_id, name=trimmed, filters=cleaned)
    session.add(view)
    session.flush()
    return view


def clean(filters: dict[str, object]) -> dict[str, object]:
    """What actually gets stored.

    Unknown keys are dropped and `None` values with them, so a view saved from a
    screen with nothing set stores `{}` rather than eleven nulls. An empty view
    is a real thing — "everything, newest first" — and it should read that way
    in the database too.
    """
    return {key: value for key, value in filters.items() if key in STORABLE and value is not None}


def rename_view(
    session: Session, user_id: uuid.UUID, view_id: uuid.UUID, name: str
) -> SavedJobView:
    view = get_view(session, user_id, view_id)
    trimmed = name.strip()

    clash = session.execute(
        owned(SavedJobView, user_id)
        .where(SavedJobView.name == trimmed)
        .where(SavedJobView.id != view_id)
    ).scalar_one_or_none()
    if clash is not None:
        raise ConflictError(f"You already have a view called {trimmed!r}.")

    view.name = trimmed
    session.flush()
    return view


def get_view(session: Session, user_id: uuid.UUID, view_id: uuid.UUID) -> SavedJobView:
    view = session.execute(
        owned(SavedJobView, user_id).where(SavedJobView.id == view_id)
    ).scalar_one_or_none()
    if view is None:
        raise ResourceNotFoundError("Saved view not found.")
    return view


def delete_view(session: Session, user_id: uuid.UUID, view_id: uuid.UUID) -> None:
    """Gone, and nothing goes with it.

    Worth stating because the product now asks before deleting a job and three
    kinds of career record: a view holds no data of its own. Deleting one loses
    a name and a filter combination, both of which the user can rebuild from
    the screen they were looking at. No confirmation.
    """
    session.delete(get_view(session, user_id, view_id))
