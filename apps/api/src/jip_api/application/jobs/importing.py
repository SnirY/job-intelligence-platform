"""The URL import pipeline.

```text
Fetch raw content → Extract main content → Store
```

``docs/04-system-architecture.md`` keeps fetching and parsing separate, and
stops there for this phase: no cleaning beyond whitespace, and no semantic
parsing at all. Phase 5 picks up from the stored text.

Runs on the worker because a remote fetch takes seconds and can hang. The job
row exists before the fetch starts, so the user has something to look at — and
something that survives if the fetch never succeeds.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from jip_api.application.jobs.creation import (
    apply_fetched_content,
    mark_fetch_failed,
    record_import,
)
from jip_api.domain.jobs.models import Job, JobImportMethod
from jip_api.infrastructure.fetching import (
    FetchError,
    extract_content,
    fetch_url,
    has_useful_content,
)

logger = logging.getLogger(__name__)

FETCH_JOB_TASK = "jip_worker.tasks.jobs.run_job_url_import"
"""Dotted path the worker exposes. A string, so the API never imports the
worker package (ADR-0003)."""


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """What one import attempt produced."""

    job_id: uuid.UUID
    succeeded: bool
    characters: int = 0
    error_code: str | None = None


def run_url_import(
    session: Session,
    job: Job,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> ImportOutcome:
    """Fetch the job's URL and store what came back.

    Never raises for an expected failure. Every outcome is recorded on the job
    and in an import record, because the user is watching the job — an
    exception here would land somewhere they never look.
    """
    if not job.source_url:
        return _fail(session, job, message="This job has no link to import.", code="NO_URL")

    try:
        result = fetch_url(job.source_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    except FetchError as error:
        record_import(
            session,
            job,
            import_method=JobImportMethod.URL,
            source_url=job.source_url,
            error=str(error),
            error_code=error.code,
        )
        logger.info(
            "Job URL import failed",
            extra={"job_id": str(job.id), "code": error.code, "detail": error.details},
        )
        return _fail(session, job, message=str(error), code=error.code)

    extracted = extract_content(result.body)

    # The raw response is stored whether or not extraction found anything
    # useful. A better extractor in a later phase can re-read it, and by then
    # the posting itself is usually gone.
    record_import(
        session,
        job,
        import_method=JobImportMethod.URL,
        raw_content=result.body,
        extracted_text=extracted.text or None,
        source_url=job.source_url,
        final_url=result.final_url,
        redirect_chain=result.redirect_chain,
        content_type=result.content_type,
        http_status=result.status,
        content_bytes=result.byte_count,
    )

    if not has_useful_content(extracted.text):
        # Usually a JavaScript-rendered page. Saying so, and pointing at the
        # fallback, beats storing a navigation bar and calling it a success.
        return _fail(
            session,
            job,
            message=(
                "We reached that page but could not find a job description on it. "
                "Paste the description instead."
            ),
            code="NO_CONTENT",
        )

    apply_fetched_content(session, job, text=extracted.text, suggested_title=extracted.title)
    session.flush()

    logger.info(
        "Imported job from URL",
        extra={"job_id": str(job.id), "characters": len(extracted.text)},
    )
    return ImportOutcome(job_id=job.id, succeeded=True, characters=len(extracted.text))


def _fail(session: Session, job: Job, *, message: str, code: str) -> ImportOutcome:
    mark_fetch_failed(session, job, message=message)
    return ImportOutcome(job_id=job.id, succeeded=False, error_code=code)
