"""The review list, and the two things a person can do with a row.

Promotion is the boundary this whole feature is built around. A scan produces
candidates; only a person turns one into a job. That is the same rule the career
profile already keeps between an AI proposal and a confirmed fact, and it is
kept here for the same reason — the job library is the one list whose contents
mean "I am interested in this", and a scan writing to it directly would change
what every count on the dashboard means with nothing on screen saying so.

Promotion goes through `creation.create_job`, deliberately and not around it.
That is where duplicate detection lives, and a posting discovered on a board the
user had already pasted by hand is exactly the case worth catching.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from jip_api.application.jobs import creation as creation_uc
from jip_api.core.errors import NotFoundError
from jip_api.domain.discovery.models import DiscoveredPosting
from jip_api.domain.jobs.models import Job, JobImportMethod
from jip_api.infrastructure.fetching import extract_content


def pending(user_id: uuid.UUID) -> Select[tuple[DiscoveredPosting]]:
    """Rows nobody has decided about yet, newest first.

    Returned as a statement rather than a list so the caller can page it. The
    two exclusions are the point: a dismissed row and a promoted row have both
    been reviewed, and neither belongs in a list whose whole purpose is things
    still awaiting a decision.
    """
    return (
        select(DiscoveredPosting)
        .where(
            DiscoveredPosting.user_id == user_id,
            DiscoveredPosting.dismissed_at.is_(None),
            DiscoveredPosting.promoted_job_id.is_(None),
        )
        .order_by(DiscoveredPosting.first_seen_at.desc(), DiscoveredPosting.id.desc())
    )


def get_posting(session: Session, user_id: uuid.UUID, posting_id: uuid.UUID) -> DiscoveredPosting:
    """One row, scoped to its owner.

    The same answer whether the row is missing or simply not theirs, per
    `docs/10-api-contracts.md`.
    """
    posting = session.scalars(
        select(DiscoveredPosting).where(
            DiscoveredPosting.id == posting_id, DiscoveredPosting.user_id == user_id
        )
    ).one_or_none()
    if posting is None:
        raise NotFoundError("That posting does not exist.")
    return posting


def dismiss(
    session: Session,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
) -> DiscoveredPosting:
    """Say no to a posting.

    Recorded rather than deleted, so the next scan of the same board does not
    offer it back. Re-dismissing is a no-op rather than an error: the date that
    matters is when the user first decided.
    """
    posting = get_posting(session, user_id, posting_id)
    if posting.dismissed_at is None:
        posting.dismissed_at = now or dt.datetime.now(tz=dt.UTC)
        session.flush()
    return posting


def promote(
    session: Session,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    *,
    allow_duplicate: bool = False,
) -> Job:
    """Turn a candidate into a job.

    Raises `creation_uc.DuplicateJobError` when the user already has this job —
    which is a normal outcome here, not an edge case, since a board may well
    list something they pasted last week. The caller offers the create-anyway
    path exactly as `POST /jobs` does.
    """
    posting = get_posting(session, user_id, posting_id)

    if posting.promoted_job_id is not None:
        existing = session.get(Job, posting.promoted_job_id)
        if existing is not None:
            # Already promoted. Returning the job rather than raising, because a
            # double click on a slow connection should not read as an error.
            return existing

    job = creation_uc.create_job(
        session,
        user_id,
        creation_uc.JobInput(
            title=posting.title,
            import_method=JobImportMethod.DISCOVERED,
            company=posting.company,
            location=posting.location,
            description=_description(posting),
            source_url=posting.url,
        ),
        allow_duplicate=allow_duplicate,
    )

    posting.promoted_job_id = job.id
    session.flush()
    return job


def _description(posting: DiscoveredPosting) -> str | None:
    """The posting text, whichever way the board sent it.

    Text is preferred where the board gave it. Greenhouse sends only markup, and
    that goes through the same extractor a pasted page does — writing a second
    HTML-to-text path here would mean two answers to one question, and the other
    one is already tested against real pages.
    """
    if posting.description_text:
        return posting.description_text
    if posting.description_html:
        return extract_content(posting.description_html).text or None
    return None
