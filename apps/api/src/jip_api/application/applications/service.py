"""Creating applications and moving them through the pipeline.

``docs/11-engineering-standards.md`` states the one rule this module exists to
enforce:

> Every status update must also create history, ideally in one transaction.

So no status is written anywhere but :func:`transition`, and :func:`transition`
always appends its event. The two cannot come apart, which is the only way "the
history is complete" stays true — a second code path that set ``status``
directly would be indistinguishable from correct until someone read a timeline
with a hole in it.

Events are appended and never updated or deleted. There is deliberately no
function here that does either.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_api.application.errors import (
    ApplicationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from jip_api.application.ownership import owned
from jip_api.domain.applications.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationSource,
    ApplicationStatus,
)
from jip_api.domain.applications.transitions import can_transition, refusal_reason
from jip_api.domain.jobs.models import Job
from jip_api.domain.resumes.models import ResumeVersion, ResumeVersionStatus

logger = logging.getLogger(__name__)


class TransitionNotAllowedError(ApplicationError):
    """The lifecycle does not permit this move."""


def create_application(
    session: Session,
    user_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    status: ApplicationStatus = ApplicationStatus.SAVED,
    notes: str | None = None,
    occurred_at: dt.datetime | None = None,
) -> Application:
    """Start tracking a job.

    Explicit rather than automatic. A job the user glanced at and moved on from
    is not a relationship with an opportunity, and creating an application for
    every saved job would make the two words synonyms — and the funnel's first
    conversion rate permanently 100%.

    ``occurred_at`` backdates the CREATED event. DEV-034: every other event type
    already accepted one, and `events_for` orders by when things *happened*, so
    a user entering three weeks of history in one sitting used to get a timeline
    ending with "Created" — the first thing that happened, sorted last.
    """
    job = session.execute(owned(Job, user_id).where(Job.id == job_id)).scalar_one_or_none()
    if job is None:
        raise ResourceNotFoundError("Job not found.")

    existing = session.execute(
        owned(Application, user_id).where(Application.job_id == job_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateResourceError("You are already tracking an application for this job.")

    application = Application(
        user_id=user_id,
        job_id=job_id,
        status=status,
        notes=(notes or "").strip() or None,
    )
    session.add(application)
    session.flush()

    _record(
        session,
        application,
        event_type=ApplicationEventType.CREATED,
        to_status=status,
        occurred_at=occurred_at,
        summary=f"Started tracking {job.title}",
    )
    session.flush()
    return application


def transition(
    session: Session,
    application: Application,
    target: ApplicationStatus,
    *,
    occurred_at: dt.datetime | None = None,
    detail: str | None = None,
) -> Application:
    """Move to ``target``, recording the move.

    The only place ``Application.status`` is assigned. Refuses anything the
    transition table forbids, with a reason written to be shown to the person
    who tried it.
    """
    current = application.status
    if not can_transition(current, target):
        raise TransitionNotAllowedError(refusal_reason(current, target))

    application.status = target
    _record(
        session,
        application,
        event_type=ApplicationEventType.STATUS_CHANGED,
        from_status=current,
        to_status=target,
        occurred_at=occurred_at,
        summary=f"Moved from {_label(current)} to {_label(target)}",
        detail=detail,
    )
    session.flush()

    logger.info(
        "Application status changed",
        extra={
            "application_id": str(application.id),
            "from": str(current),
            "to": str(target),
        },
    )
    return application


def mark_applied(
    session: Session,
    application: Application,
    *,
    resume_version_id: uuid.UUID | None,
    source: ApplicationSource | None,
    applied_at: dt.datetime | None = None,
    detail: str | None = None,
) -> Application:
    """Record that the application was actually sent.

    ``docs/07`` requires four things preserved at this moment: the date, the
    exact resume version, the source, and any notes. The version is pinned *and*
    frozen — a resume that has been sent is a historical fact, and
    ``ResumeVersion.content_is_frozen`` is what stops it being edited afterwards.

    ``applied_at`` is supplied rather than assumed, because someone entering
    last month's applications needs the timeline to read correctly.
    """
    moment = applied_at or dt.datetime.now(tz=dt.UTC)

    if resume_version_id is not None:
        version = session.execute(
            owned(ResumeVersion, application.user_id).where(ResumeVersion.id == resume_version_id)
        ).scalar_one_or_none()
        if version is None:
            raise ResourceNotFoundError("Resume version not found.")

        application.resume_version_id = version.id
        _record(
            session,
            application,
            event_type=ApplicationEventType.RESUME_ATTACHED,
            occurred_at=moment,
            summary=f"Attached version {version.version}"
            + (f" — {version.label}" if version.label else ""),
        )

        # Freezing is the point, not bookkeeping: from here the document is what
        # an employer read, and editing it would rewrite what was sent.
        if version.status is not ResumeVersionStatus.USED:
            version.status = ResumeVersionStatus.USED
            version.used_at = moment

    application.applied_at = moment
    application.source = source

    if application.status is not ApplicationStatus.APPLIED:
        transition(session, application, ApplicationStatus.APPLIED, occurred_at=moment)

    _record(
        session,
        application,
        event_type=ApplicationEventType.SUBMITTED,
        occurred_at=moment,
        summary="Application submitted",
        detail=detail,
    )
    session.flush()
    return application


def add_note(
    session: Session,
    application: Application,
    text: str,
    *,
    occurred_at: dt.datetime | None = None,
) -> ApplicationEvent:
    """Append a note to the timeline.

    An event rather than an edit to ``Application.notes``: a note is something
    that happened at a time, and overwriting the previous one would lose it.
    ``notes`` remains the user's freely-editable scratch space; this is the
    record.
    """
    cleaned = text.strip()
    if not cleaned:
        raise TransitionNotAllowedError("A note needs some text.")

    event = _record(
        session,
        application,
        event_type=ApplicationEventType.NOTE_ADDED,
        occurred_at=occurred_at,
        summary=cleaned[:300],
        detail=cleaned if len(cleaned) > 300 else None,
    )
    session.flush()
    return event


def record_feedback(
    session: Session,
    application: Application,
    feedback: str,
    *,
    occurred_at: dt.datetime | None = None,
) -> Application:
    """Store what the employer actually said.

    Kept in its own column, and only ever written from the user's own words.
    ``docs/07`` is explicit that known feedback stays separate from system
    inference and that a guessed reason must never be presented as fact —
    nothing in this phase infers anything here.

    ``occurred_at`` for the same reason as `create_application`: a reply
    recorded weeks after it arrived belongs where it arrived (DEV-034).
    """
    application.rejection_feedback = feedback.strip() or None
    _record(
        session,
        application,
        event_type=ApplicationEventType.FEEDBACK_RECORDED,
        occurred_at=occurred_at,
        summary="Recorded feedback from the employer",
        detail=application.rejection_feedback,
    )
    session.flush()
    return application


def list_applications(
    session: Session, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[Application]:
    """Everything the board draws.

    Ordered by status then by age, so a column reads oldest-first — the card
    that has been sitting longest is the one that needs attention, and burying
    it under this morning's is the opposite of a tracker.
    """
    query = owned(Application, user_id)
    if not include_archived:
        query = query.where(Application.status != ApplicationStatus.ARCHIVED)

    return list(
        session.execute(query.order_by(Application.status, Application.created_at)).scalars()
    )


def days_in_stage(session: Session, application_id: uuid.UUID) -> int | None:
    """How long the application has sat where it is.

    Derived from the last status change rather than a stored column. The events
    already record every move exactly, and a denormalised ``entered_stage_at``
    would be a second source of truth for the same fact — one that drifts the
    first time a status is set by a path that forgets to update it.

    ``None`` before any move: an application created five minutes ago has not
    been "in a stage" in any sense worth reporting.
    """
    return days_in_stage_for(session, [application_id]).get(application_id)


def days_in_stage_for(session: Session, application_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """The same, for a whole board, in one query rather than one per card."""
    if not application_ids:
        return {}

    latest = (
        select(
            ApplicationEvent.application_id,
            func.max(ApplicationEvent.occurred_at).label("moved_at"),
        )
        .where(
            ApplicationEvent.application_id.in_(application_ids),
            ApplicationEvent.event_type == ApplicationEventType.STATUS_CHANGED,
        )
        .group_by(ApplicationEvent.application_id)
    )

    now = dt.datetime.now(tz=dt.UTC)
    result: dict[uuid.UUID, int] = {}
    for application_id, moved_at in session.execute(latest):
        moment = moved_at if moved_at.tzinfo is not None else moved_at.replace(tzinfo=dt.UTC)
        result[application_id] = max((now - moment).days, 0)
    return result


def get_application(session: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> Application:
    application = session.execute(
        owned(Application, user_id).where(Application.id == application_id)
    ).scalar_one_or_none()
    if application is None:
        raise ResourceNotFoundError("Application not found.")
    return application


def events_for(session: Session, application_id: uuid.UUID) -> list[ApplicationEvent]:
    """The timeline, oldest first.

    Ordered by when things *happened*, not when they were recorded, so a user
    entering three weeks of history in one sitting still reads correctly. The id
    breaks ties so two events at the same instant keep a stable order.
    """
    return list(
        session.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
        ).scalars()
    )


def _record(
    session: Session,
    application: Application,
    *,
    event_type: ApplicationEventType,
    summary: str,
    from_status: ApplicationStatus | None = None,
    to_status: ApplicationStatus | None = None,
    occurred_at: dt.datetime | None = None,
    detail: str | None = None,
) -> ApplicationEvent:
    event = ApplicationEvent(
        user_id=application.user_id,
        application_id=application.id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        occurred_at=occurred_at or dt.datetime.now(tz=dt.UTC),
        summary=summary,
        detail=detail,
    )
    session.add(event)
    return event


def _label(status: ApplicationStatus) -> str:
    return str(status).replace("_", " ").lower()
