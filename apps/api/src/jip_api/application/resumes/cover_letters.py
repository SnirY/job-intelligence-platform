"""Drafting a cover letter, and checking it says only what the profile supports.

```text
match -> selection -> draft -> truth validation -> a person reads it
```

The same gate the resume pipeline uses, and the same order. What differs is one
thing, and it is why this is not a mode of `RESUME_REWRITE`:

**A rewrite is anchored and a letter is not.** A rewrite has an original line,
so validation can ask whether the new wording says more than the old one did. A
letter has no original, so validation runs with `original=""` — the strictest
setting `truth.py` has, under which every number in the text must appear in the
career facts or the claim is BLOCKED. That is the correct setting here. A
figure in a cover letter that the profile cannot support is a figure the
candidate will be asked about in an interview.

Requires a match, like `create_strategy` and for the same reason: a letter
argues from evidence, and the evidence is what matching produced. Refused with a
reason otherwise rather than drafting something generic.

The draft is stored whatever validation concludes. A letter with a blocked claim
is shown to the user with the problem attached — they may know the number is
real, in which case the fix is to add it to their profile, which is exactly what
`docs/06` means by the system asking for a missing metric rather than inventing
one.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_ai import (
    AIError,
    AIFailureCode,
    AIOperation,
    AIRunTrace,
    LLMProvider,
    ModelRouter,
    StructuredRequest,
    compute_input_hash,
    run_with_retry,
    schema_failure_summary,
    timed,
)
from jip_api.application.errors import ApplicationError
from jip_api.application.matching import queries as match_queries
from jip_api.application.resumes.cover_letter_schema import (
    CoverLetterResult,
    cover_letter_json_schema,
)
from jip_api.application.resumes.selection import SelectionResult, select_for_match
from jip_api.application.resumes.truth import TruthReport, validate_rewrite
from jip_api.domain.jobs.models import Job
from jip_api.domain.matching.models import JobMatch
from jip_api.domain.resumes.cover_letters import (
    CoverLetter,
    CoverLetterClaim,
    CoverLetterStatus,
)
from jip_prompts import COVER_LETTER_LATEST, get_prompt

logger = logging.getLogger(__name__)

DRAFT_TASK = "jip_worker.tasks.resumes.run_cover_letter_draft"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""

DEFAULT_ANGLE = (
    "Why this candidate is a credible fit for this role, argued from the "
    "strongest evidence in their profile."
)
"""Used when the user does not supply one.

Deliberately dull. An angle is the user's to choose, and a default that took a
position — "emphasise leadership", "lead with the career change" — would be the
system deciding what their letter is about.
"""

MAX_FACTS = 40
MAX_JOB_CHARS = 6000


class CoverLetterNotPossibleError(ApplicationError):
    """There is not enough here to write a letter from."""


@dataclass(slots=True)
class CoverLetterOutcome:
    """One drafting attempt."""

    letter: CoverLetter
    report: TruthReport | None = None
    traces: list[AIRunTrace] = field(default_factory=list)


def latest_for_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> CoverLetter | None:
    """The newest letter for one job, or ``None``."""
    return session.scalars(
        select(CoverLetter)
        .where(CoverLetter.user_id == user_id, CoverLetter.job_id == job_id)
        .order_by(CoverLetter.created_at.desc())
        .limit(1)
    ).one_or_none()


def claims_for(session: Session, letter_id: uuid.UUID) -> list[CoverLetterClaim]:
    return list(
        session.scalars(
            select(CoverLetterClaim)
            .where(CoverLetterClaim.cover_letter_id == letter_id)
            .order_by(CoverLetterClaim.created_at.asc())
        )
    )


def start_draft(
    session: Session,
    user_id: uuid.UUID,
    job: Job,
    *,
    angle: str | None = None,
) -> CoverLetter:
    """Create the row a draft will fill in, before any model is called.

    Exists before the work starts for the reason the job row does in
    `importing.py`: the user is watching, and something that survives a failure
    is better than a request that vanishes.
    """
    if match_queries.latest_match(session, user_id, job.id) is None:
        raise CoverLetterNotPossibleError(
            "This job has not been matched against your profile yet, so there is "
            "nothing to write a letter from."
        )

    letter = CoverLetter(
        user_id=user_id,
        job_id=job.id,
        status=CoverLetterStatus.DRAFTING,
        angle=(angle or DEFAULT_ANGLE).strip()[:500],
    )
    session.add(letter)
    session.flush()
    return letter


def run_draft(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    letter: CoverLetter,
    job: Job,
    max_attempts: int = 2,
) -> CoverLetterOutcome:
    """Draft the letter, validate it, and record both.

    Never raises for an expected failure. The outcome belongs on the row the
    user is looking at.
    """
    traces: list[AIRunTrace] = []

    match = match_queries.latest_match(session, letter.user_id, job.id)
    if match is None:
        return _fail(session, letter, "The match this letter was based on is no longer there.")

    selection = select_for_match(session, letter.user_id, match)
    facts = _facts(selection)
    if not facts:
        return _fail(
            session,
            letter,
            "Your profile has nothing confirmed that this role asks for, so there "
            "is nothing a letter could honestly claim.",
        )

    try:
        result, prompt_name = _ask(
            provider,
            router,
            job=job,
            angle=letter.angle or DEFAULT_ANGLE,
            match_summary=_match_summary(match),
            facts=facts,
            max_attempts=max_attempts,
            traces=traces,
        )
    except AIError as error:
        logger.info(
            "Cover letter draft failed",
            extra={"letter_id": str(letter.id), "code": str(error.code)},
        )
        return _fail(session, letter, str(error), traces=traces)

    # `original=""` on purpose: there is no earlier wording to be measured
    # against, so every figure has to come from the facts. See the module
    # docstring.
    report = validate_rewrite(original="", suggested=result.body, source_facts=facts)

    letter.body = result.body
    letter.angle_warning = result.angle_warning
    letter.prompt_version = prompt_name
    letter.error = None
    letter.status = CoverLetterStatus.DRAFTED

    for claim in report.claims:
        session.add(
            CoverLetterClaim(
                user_id=letter.user_id,
                cover_letter_id=letter.id,
                text=claim.text,
                status=claim.status,
                explanation=claim.explanation,
                confidence=claim.confidence,
            )
        )

    session.flush()
    return CoverLetterOutcome(letter=letter, report=report, traces=traces)


def edit(
    session: Session,
    letter: CoverLetter,
    *,
    body: str,
    now: dt.datetime | None = None,
) -> CoverLetter:
    """Replace the text with what a person wrote.

    **Not re-validated, and that is deliberate.** The claims attached to this
    letter were computed against the model's words. What a person writes about
    themselves is theirs, and running a fabrication check over it would be the
    system second-guessing the one source it treats as authoritative.

    The status moves to EDITED so nothing later reads the claims as though they
    described the current text.
    """
    letter.body = body.strip()
    letter.status = CoverLetterStatus.EDITED
    letter.edited_at = now or dt.datetime.now(tz=dt.UTC)
    letter.approved_at = None
    session.flush()
    return letter


def approve(
    session: Session, letter: CoverLetter, *, now: dt.datetime | None = None
) -> CoverLetter:
    """A person read it and said yes."""
    if not letter.body:
        raise CoverLetterNotPossibleError("There is no letter here to approve.")
    letter.status = CoverLetterStatus.APPROVED
    letter.approved_at = now or dt.datetime.now(tz=dt.UTC)
    session.flush()
    return letter


def _fail(
    session: Session,
    letter: CoverLetter,
    message: str,
    *,
    traces: list[AIRunTrace] | None = None,
) -> CoverLetterOutcome:
    letter.status = CoverLetterStatus.FAILED
    letter.error = message
    session.flush()
    return CoverLetterOutcome(letter=letter, traces=traces or [])


def _facts(selection: SelectionResult) -> list[str]:
    """The career text a letter may draw on.

    Only what selection confirmed. `excluded_unverified` is deliberately absent:
    those are things the user has not confirmed, and a letter is a claim made in
    their name.
    """
    return [candidate.text for candidate in selection.all_selected[:MAX_FACTS]]


def _match_summary(match: JobMatch) -> str:
    """What matching concluded, as prose the prompt can use.

    The same shape the strategy prompt is given. The letter may know the verdict
    and the reasoning behind it; what it must never do is quote the figure back
    at the employer, and `docs/05` is why — the score is a reading of fit for
    the candidate, not a credential to put in front of a recruiter.
    """
    parts = [
        f"Alignment: {match.overall_score if match.overall_score is not None else 'not scored'}"
        f" ({match.alignment_label})",
        f"Recommendation: {match.recommendation}",
    ]
    parts.extend(f"- {reason}" for reason in match.recommendation_reasons)
    return "\n".join(parts)


def _ask(
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: Job,
    angle: str,
    match_summary: str,
    facts: list[str],
    max_attempts: int,
    traces: list[AIRunTrace],
) -> tuple[CoverLetterResult, str]:
    prompt = get_prompt(COVER_LETTER_LATEST)
    route = router.route(AIOperation.COVER_LETTER)

    rendered = prompt.render(
        job=f"{job.title}\n{(job.description or '')[:MAX_JOB_CHARS]}",
        match=match_summary,
        angle=angle,
        facts="\n".join(f"- {fact}" for fact in facts),
    )
    input_hash = compute_input_hash(prompt.name, route.model, prompt.system, rendered)

    request = StructuredRequest(
        system=prompt.system,
        user=rendered,
        json_schema=cover_letter_json_schema(),
        max_output_tokens=route.max_output_tokens,
        effort=route.effort,
    )

    def attempt(number: int) -> CoverLetterResult:
        trace = AIRunTrace(
            operation=str(AIOperation.COVER_LETTER),
            provider=provider.name,
            model=route.model,
            prompt_version=prompt.name,
            input_hash=input_hash,
            attempt=number,
        )
        traces.append(trace)

        with timed(trace):
            try:
                response = provider.generate_structured(request, model=route.model)
            except AIError as error:
                trace.mark_failure(error.code, str(error))
                raise

            cost = route.pricing.estimate(response.usage) if route.pricing else None
            trace.mark_success(response.usage, cost=cost)

            try:
                return CoverLetterResult.model_validate(response.payload)
            except ValidationError as exc:
                trace.mark_failure(
                    AIFailureCode.INVALID_OUTPUT,
                    f"Output failed schema check: {schema_failure_summary(exc)}",
                )
                raise AIError(
                    AIFailureCode.INVALID_OUTPUT,
                    "The draft came back in an unexpected shape.",
                    details=str(exc)[:500],
                ) from exc

    return run_with_retry(attempt, max_attempts=max_attempts), prompt.name
