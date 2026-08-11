"""The import pipeline, as run by the worker.

```text
Store -> Extract -> Parse -> (wait for the user) -> Review -> Approve
```

Everything up to the pause happens here. The two properties that shape the code:

- **A failure never destroys work** (``GOAL.md``). The document row and its
  extracted text are committed as soon as each becomes available, so a parse
  failure still leaves a retry that skips extraction entirely.
- **AI output never becomes career data.** The parse lands in
  ``document_extractions`` and stops there.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jip_ai import AIError, AIFailureCode, AIRunTrace, LLMProvider, ModelRouter
from jip_api.application.processing import jobs as jobs_uc
from jip_api.application.resumes import looks_like_a_resume
from jip_api.application.resumes.parsing import ResumeParseOutcome, ResumeParsingService
from jip_api.application.resumes.validation import CandidateDraft
from jip_api.domain.ai.models import AIRun, AIRunStatus
from jip_api.domain.documents.models import (
    CandidateDecision,
    DocumentExtraction,
    DocumentExtractionItem,
    DocumentStatus,
    SourceDocument,
)
from jip_api.domain.processing.models import ProcessingJob, ProcessingStep
from jip_api.infrastructure.extraction import extract_text
from jip_api.infrastructure.storage.base import ObjectNotFoundError, ObjectStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """What one run produced."""

    document_id: uuid.UUID
    extraction_id: uuid.UUID | None
    candidate_count: int


def run_import(
    session: Session,
    storage: ObjectStorage,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: ProcessingJob,
    max_input_chars: int,
    max_attempts: int,
) -> PipelineResult:
    """Take a job from queued to parsed.

    Commits at each step rather than wrapping the whole run in one transaction.
    A single transaction would be tidier, but it would also throw away the
    extracted text when parsing failed — and re-extracting is exactly the work a
    retry should not have to repeat.
    """
    document = session.get(SourceDocument, job.entity_id)
    if document is None:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "The document for this job no longer exists.",
        )

    text = _ensure_text(session, storage, job=job, document=document)

    # DEV-020. Between having the text and paying for a call on it: a document
    # that is not a resume produces a review screen full of real quotations from
    # the wrong document, which is more convincing and less useful than an
    # error. Refused rather than warned about, because a screen the user is told
    # to ignore is a worse answer than a refusal.
    #
    # CONTENT_UNAVAILABLE because the input itself is the problem — the code is
    # already classified permanent, so no retry is offered for something no
    # number of retries can change (DEV-015, DEV-021).
    verdict = looks_like_a_resume.check(text)
    if not verdict.is_resume:
        logger.info(
            "Refused a document that does not look like a resume",
            extra={
                "document_id": str(document.id),
                "characters": len(text),
                "signals_found": len(verdict.found),
            },
        )
        # Recorded on the document, not only on the job, and committed before
        # the raise — the same shape `_ensure_text` uses for an extraction
        # failure. A document left EXTRACTED beside a failed job is the
        # mismatch `reaper._release_entity` exists to repair, and creating one
        # deliberately would be worse than the bug this closes.
        document.extraction_error = verdict.reason
        document.status = DocumentStatus.FAILED
        session.commit()
        raise AIError(AIFailureCode.CONTENT_UNAVAILABLE, verdict.reason)

    outcome = _parse(
        session,
        provider,
        router,
        job=job,
        document=document,
        text=text,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    extraction = _persist(session, document=document, outcome=outcome)

    document.status = DocumentStatus.PARSED
    jobs_uc.mark_completed(session, job)
    session.commit()

    return PipelineResult(
        document_id=document.id,
        extraction_id=extraction.id,
        candidate_count=len(outcome.validated.candidates),
    )


def _ensure_text(
    session: Session,
    storage: ObjectStorage,
    *,
    job: ProcessingJob,
    document: SourceDocument,
) -> str:
    """Return the document's text, extracting it if this is the first attempt.

    Reusing already-extracted text on a retry is not just an optimisation: it
    means a retry after an AI outage does not re-download the file or re-run a
    parser that already succeeded.
    """
    if document.extracted_text:
        return document.extracted_text

    jobs_uc.mark_running(session, job, ProcessingStep.EXTRACTING)
    document.status = DocumentStatus.EXTRACTING
    session.commit()

    try:
        data = storage.download(document.storage_key)
    except ObjectNotFoundError as exc:
        raise AIError(
            AIFailureCode.CONTENT_UNAVAILABLE,
            "The uploaded file could not be found in storage.",
            details=str(exc),
        ) from exc
    except Exception as exc:
        raise AIError(
            AIFailureCode.PROVIDER_ERROR,
            "The uploaded file could not be read right now.",
            details=str(exc),
        ) from exc

    try:
        extracted = extract_text(data, content_type=document.content_type)
    except AIError as error:
        # Recorded on the document as well as the job: the job may be trimmed
        # later, and the user still needs to know why this file never worked.
        document.extraction_error = str(error.args[0]) if error.args else str(error.code)
        document.status = DocumentStatus.FAILED
        session.commit()
        raise

    document.extracted_text = extracted.text
    document.extraction_error = None
    document.status = DocumentStatus.EXTRACTED
    session.commit()

    logger.info(
        "Extracted document text",
        extra={"document_id": str(document.id), "characters": len(extracted.text)},
    )
    return extracted.text


def _parse(
    session: Session,
    provider: LLMProvider,
    router: ModelRouter,
    *,
    job: ProcessingJob,
    document: SourceDocument,
    text: str,
    max_input_chars: int,
    max_attempts: int,
) -> ResumeParseOutcome:
    """Run the parser, recording every attempt as an ``AIRun``."""
    jobs_uc.mark_running(session, job, ProcessingStep.PARSING)
    document.status = DocumentStatus.PARSING
    session.commit()

    service = ResumeParsingService(
        provider,
        router,
        max_input_chars=max_input_chars,
        max_attempts=max_attempts,
    )

    # Owned here rather than inside the service so the attempts survive a
    # failure — DEV-016. Persisted before the commit below, because the worker's
    # handler opens with session.rollback() and would otherwise discard them.
    traces: list[AIRunTrace] = []
    try:
        outcome = service.parse(text, content_type=document.content_type, traces=traces)
    except AIError:
        _persist_traces(session, document, traces)
        document.status = DocumentStatus.FAILED
        session.commit()
        raise

    _persist_traces(session, document, outcome.traces)
    return outcome


def _persist_traces(session: Session, document: SourceDocument, traces: list[AIRunTrace]) -> None:
    """One ``ai_runs`` row per attempt, on the failure path as well.

    A wholly failed parse used to leave no trace at all, so the only record of
    what it cost was a generic message on ``processing_jobs`` — which is
    precisely the case the trace exists for.
    """
    for trace in traces:
        session.add(_ai_run(trace, user_id=document.user_id, document_id=document.id))
    session.flush()


def _ai_run(trace: AIRunTrace, *, user_id: uuid.UUID, document_id: uuid.UUID) -> AIRun:
    """Map a trace onto the ``ai_runs`` row."""
    return AIRun(
        user_id=user_id,
        operation=trace.operation,
        entity_type="source_document",
        entity_id=document_id,
        provider=trace.provider,
        model=trace.model,
        prompt_version=trace.prompt_version,
        input_hash=trace.input_hash,
        status=AIRunStatus.SUCCEEDED if trace.succeeded else AIRunStatus.FAILED,
        failure_code=str(trace.failure_code) if trace.failure_code else None,
        error_message=trace.error_message,
        latency_ms=trace.latency_ms,
        input_tokens=trace.usage.input_tokens,
        output_tokens=trace.usage.output_tokens,
        estimated_cost_usd=trace.estimated_cost_usd,
        attempt=trace.attempt,
    )


def _persist(
    session: Session,
    *,
    document: SourceDocument,
    outcome: ResumeParseOutcome,
) -> DocumentExtraction:
    """Store the extraction and its candidates as a new version."""
    next_version = (
        session.execute(
            select(func.coalesce(func.max(DocumentExtraction.version), 0)).where(
                DocumentExtraction.source_document_id == document.id
            )
        ).scalar_one()
        + 1
    )

    extraction = DocumentExtraction(
        user_id=document.user_id,
        source_document_id=document.id,
        version=next_version,
        provider=outcome.provider,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        input_hash=outcome.input_hash,
        payload=outcome.raw_payload,
        warnings=list(outcome.warnings),
    )
    session.add(extraction)
    session.flush()

    for draft in outcome.validated.candidates:
        _persist_draft(session, extraction=extraction, draft=draft, parent=None)
    session.flush()

    logger.info(
        "Stored extraction",
        extra={
            "document_id": str(document.id),
            "version": next_version,
            "candidates": len(outcome.validated.candidates),
        },
    )
    return extraction


def _persist_draft(
    session: Session,
    *,
    extraction: DocumentExtraction,
    draft: CandidateDraft,
    parent: DocumentExtractionItem | None,
) -> DocumentExtractionItem:
    """Store one candidate and its children.

    Flushes before recursing so the parent has an id for its children to point
    at — an achievement without a parent link cannot be applied at all.
    """
    item = DocumentExtractionItem(
        user_id=extraction.user_id,
        extraction_id=extraction.id,
        candidate_type=draft.candidate_type,
        parent_item_id=parent.id if parent else None,
        display_order=draft.display_order,
        payload=draft.payload,
        confidence=draft.confidence,
        source_text=draft.source_text,
        decision=CandidateDecision.PENDING,
    )
    session.add(item)
    session.flush()

    for child in draft.children:
        _persist_draft(session, extraction=extraction, draft=child, parent=item)

    return item
