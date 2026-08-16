"""The reviewed-candidate mechanism `requirement_skills.py` described as absent.

DEV-062, candidate 2. Every defect the DEV-011 calibration found had one shape:
lexical comparison over a hand-maintained vocabulary. Each fix added another
entry to another hand-written list, and those lists do not converge — there is
always another word, and the calibration was spending its budget discovering
which.

This does not make the vocabulary complete. It makes it **grow from the postings
that need it, through a person, instead of through a migration somebody
remembers to write.**

## The rule this does not break

`requirement_skills.py` refuses to let a job requirement create a canonical
skill, and the reasoning is sound: the name came from a model reading someone
else's prose, nobody reviews it, and there are as many requirements as there are
postings. That path would fill a shared table with "Rust (advantageous)",
"strong Rust" and "RUST".

Nothing here changes that. A posting still cannot write to `skills`. It can put
a name in a queue, and a person decides — which is the difference between a
catalogue that accumulates and one that grows.

## Refresh is idempotent, and rebuilds rather than appends

`refresh_candidates` recomputes the queue from the requirements each time. A
name already reviewed keeps its decision: a REJECTED candidate stays rejected
however many further postings use it, which is the point of storing rejections
at all. "General-purpose programming language" appears six times in the
development data and is not a skill; without a remembered rejection it would be
re-proposed forever.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from jip_api.application.errors import ApplicationError, ResourceNotFoundError
from jip_api.application.jobs.requirement_skills import clean_skill_name, resolve_known_skills
from jip_api.domain.career.skills import (
    CandidateStatus,
    Skill,
    SkillAlias,
    SkillCandidate,
    SkillCategory,
    normalize_skill_name,
)
from jip_api.domain.jobs.analysis import JobRequirement

logger = logging.getLogger(__name__)


class CandidateAlreadyReviewedError(ApplicationError):
    """The decision has already been made.

    A conflict rather than a not-found: the row exists and says something, and
    silently overwriting one reviewer's conclusion with another's is how a
    shared catalogue acquires changes nobody remembers making.
    """


@dataclass(frozen=True, slots=True)
class CandidateView:
    """A queue entry, with what a reviewer needs to decide."""

    id: uuid.UUID
    normalized_name: str
    display_name: str
    occurrences: int
    status: CandidateStatus
    resolved_skill_id: uuid.UUID | None
    note: str | None


def resolve_pending_requirements(session: Session) -> int:
    """Point stored requirements at skills the catalogue has since gained.

    The gap that made this necessary: `f2a91c47d8e3` added thirty canonical
    skills and never re-resolved the requirements already stored, because
    nothing in the codebase did that. `HTML` and `CSS` sat unresolved while the
    skills they name were in the catalogue.

    On the development data that was 21 of 44 distinct unresolved names — not a
    vocabulary gap, a resolution nobody re-ran. Called before every refresh so
    the queue only ever contains names that genuinely have no answer.

    Returns the number of requirement rows updated.
    """
    rows = list(
        session.execute(
            select(JobRequirement).where(
                JobRequirement.skill_id.is_(None), JobRequirement.skill_name.is_not(None)
            )
        ).scalars()
    )
    if not rows:
        return 0

    names = sorted({row.skill_name for row in rows if row.skill_name})
    resolved = resolve_known_skills(session, names)
    if not resolved:
        return 0

    updated = 0
    for row in rows:
        skill = resolved.get(row.skill_name or "")
        if skill is not None:
            row.skill_id = skill.id
            updated += 1

    session.flush()
    logger.info("Re-resolved requirements against the catalogue", extra={"updated": updated})
    return updated


def refresh_candidates(session: Session) -> list[CandidateView]:
    """Rebuild the queue from what the postings still cannot resolve.

    Resolves first, so a name the catalogue can already answer never reaches the
    queue at all. Then counts the survivors and upserts them, preserving any
    decision already recorded.
    """
    resolve_pending_requirements(session)

    counts: dict[str, tuple[str, int]] = {}
    rows = session.execute(
        select(JobRequirement.skill_name, func.count())
        .where(JobRequirement.skill_id.is_(None), JobRequirement.skill_name.is_not(None))
        .group_by(JobRequirement.skill_name)
    ).all()

    for raw_name, count in rows:
        display = clean_skill_name(raw_name or "")
        key = normalize_skill_name(display)
        if not key:
            continue
        # Two spellings of one technology collapse to a single queue entry. The
        # display name is whichever sorted first, so the queue does not reshuffle
        # between refreshes of identical data.
        seen = counts.get(key)
        if seen is None:
            counts[key] = (display, count)
        else:
            counts[key] = (min(seen[0], display), seen[1] + count)

    existing = {
        candidate.normalized_name: candidate
        for candidate in session.execute(select(SkillCandidate)).scalars()
    }

    for key, (display, count) in counts.items():
        candidate = existing.get(key)
        if candidate is None:
            session.add(
                SkillCandidate(
                    normalized_name=key,
                    display_name=display,
                    occurrences=count,
                    status=CandidateStatus.PENDING,
                )
            )
            continue
        # The count moves even for a reviewed candidate: how often a rejected
        # term keeps appearing is worth knowing when deciding whether the
        # rejection was right.
        candidate.occurrences = count

    session.flush()
    return list_candidates(session)


def list_candidates(
    session: Session, status: CandidateStatus | None = CandidateStatus.PENDING
) -> list[CandidateView]:
    """The queue, most-used first.

    Frequency order rather than alphabetical, and DEV-040 is why: a list sorted
    by name buries the entries that matter under the ones that begin with A.
    """
    statement = select(SkillCandidate)
    if status is not None:
        statement = statement.where(SkillCandidate.status == status)

    statement = statement.order_by(SkillCandidate.occurrences.desc(), SkillCandidate.display_name)

    return [
        CandidateView(
            id=candidate.id,
            normalized_name=candidate.normalized_name,
            display_name=candidate.display_name,
            occurrences=candidate.occurrences,
            status=CandidateStatus(candidate.status),
            resolved_skill_id=candidate.resolved_skill_id,
            note=candidate.note,
        )
        for candidate in session.execute(statement).scalars()
    ]


def _pending(session: Session, candidate_id: uuid.UUID) -> SkillCandidate:
    candidate = session.get(SkillCandidate, candidate_id)
    if candidate is None:
        raise ResourceNotFoundError("Skill candidate not found.")
    if candidate.status is not CandidateStatus.PENDING:
        raise CandidateAlreadyReviewedError(
            f"That candidate was already {str(candidate.status).lower()}."
        )
    return candidate


def accept_as_alias(
    session: Session, candidate_id: uuid.UUID, skill_id: uuid.UUID, note: str | None = None
) -> CandidateView:
    """This name means a skill the catalogue already holds.

    The commoner of the two decisions, and the one that keeps the catalogue
    small: "RESTful API" is not a new skill, it is how a posting writes an
    existing one.
    """
    candidate = _pending(session, candidate_id)

    skill = session.get(Skill, skill_id)
    if skill is None:
        raise ResourceNotFoundError("That skill is not in the catalogue.")

    if skill.normalized_name != candidate.normalized_name:
        # Guarded rather than assumed: an alias equal to some skill's canonical
        # name makes resolution depend on which lookup runs first, which is
        # exactly DEV-067. Accepting it as an alias of *itself* is a no-op that
        # would create that state.
        session.add(
            SkillAlias(
                skill_id=skill.id,
                alias=candidate.display_name,
                normalized_alias=candidate.normalized_name,
            )
        )

    candidate.status = CandidateStatus.ACCEPTED
    candidate.resolved_skill_id = skill.id
    candidate.note = note
    session.flush()

    _apply_to_requirements(session, candidate.normalized_name, skill.id)
    return _view(candidate)


def accept_as_new_skill(
    session: Session,
    candidate_id: uuid.UUID,
    category: SkillCategory,
    canonical_name: str | None = None,
    note: str | None = None,
) -> CandidateView:
    """The catalogue genuinely did not have this.

    `canonical_name` lets the reviewer correct the posting's spelling —
    "scikit-learn" for a posting that wrote "Scikit-Learn" — while the alias
    keeps the posting's wording resolvable.
    """
    candidate = _pending(session, candidate_id)

    name = (canonical_name or candidate.display_name).strip()
    if not name:
        raise ApplicationError("A canonical skill needs a name.")

    normalized = normalize_skill_name(name)
    existing = session.execute(
        select(Skill).where(Skill.normalized_name == normalized)
    ).scalar_one_or_none()
    if existing is not None:
        # Not an error worth refusing: the reviewer's intent is clear and the
        # outcome they want already exists. Treat it as the alias decision.
        return accept_as_alias(session, candidate_id, existing.id, note)

    skill = Skill(canonical_name=name, normalized_name=normalized, category=category)
    session.add(skill)
    session.flush()

    if normalized != candidate.normalized_name:
        session.add(
            SkillAlias(
                skill_id=skill.id,
                alias=candidate.display_name,
                normalized_alias=candidate.normalized_name,
            )
        )

    candidate.status = CandidateStatus.ACCEPTED
    candidate.resolved_skill_id = skill.id
    candidate.note = note
    session.flush()

    _apply_to_requirements(session, candidate.normalized_name, skill.id)
    return _view(candidate)


def reject(session: Session, candidate_id: uuid.UUID, note: str | None = None) -> CandidateView:
    """Not a skill, or not one worth a catalogue entry.

    "General-purpose programming language" is the case that proves the queue
    needs this: it appears six times in the development data, names no
    technology, and without a remembered rejection every refresh would propose
    it again.
    """
    candidate = _pending(session, candidate_id)
    candidate.status = CandidateStatus.REJECTED
    candidate.note = note
    session.flush()
    return _view(candidate)


def _apply_to_requirements(session: Session, normalized_name: str, skill_id: uuid.UUID) -> None:
    """Point every requirement using this name at the skill just decided.

    Without this the decision would only affect postings analysed afterwards,
    and the reviewer would have fixed the catalogue for the future while leaving
    every stored match reading the old answer.
    """
    # `session.execute` is typed as returning `Result`, which has no rowcount in
    # the stubs; a DML statement really returns a `CursorResult`, which does.
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(JobRequirement)
            .where(
                JobRequirement.skill_id.is_(None),
                JobRequirement.skill_name.is_not(None),
                func.trim(
                    func.regexp_replace(
                        func.lower(JobRequirement.skill_name), "[^a-z0-9+#]+", "-", "g"
                    ),
                    "-",
                )
                == normalized_name,
            )
            .values(skill_id=skill_id)
        ),
    )
    session.flush()
    logger.info(
        "Applied a skill decision to stored requirements",
        extra={"normalized_name": normalized_name, "updated": result.rowcount},
    )


def _view(candidate: SkillCandidate) -> CandidateView:
    return CandidateView(
        id=candidate.id,
        normalized_name=candidate.normalized_name,
        display_name=candidate.display_name,
        occurrences=candidate.occurrences,
        status=CandidateStatus(candidate.status),
        resolved_skill_id=candidate.resolved_skill_id,
        note=candidate.note,
    )
