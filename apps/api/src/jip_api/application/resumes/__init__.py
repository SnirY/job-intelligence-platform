"""Resume import use cases.

The pipeline in ``docs/09-mvp-roadmap.md``, split by responsibility rather than
into one service: ``imports`` starts and reads, ``pipeline`` runs the background
work, ``parsing`` talks to the model, ``validation`` decides what is trustworthy
enough to show, and ``confirm`` applies what the user accepted.
"""

from jip_api.application.resumes.confirm import (
    ConfirmAction,
    ConfirmationResult,
    ConfirmOutcome,
    Decision,
    InvalidDecisionError,
    confirm_extraction,
    load_extraction,
)
from jip_api.application.resumes.imports import (
    RESUME_IMPORT_TASK,
    StartedImport,
    dispatch,
    extraction_items,
    get_document,
    latest_extraction,
    latest_job_for_document,
    list_documents,
    signed_download_url,
    start_resume_import,
)
from jip_api.application.resumes.parsing import ResumeParseOutcome, ResumeParsingService
from jip_api.application.resumes.pipeline import PipelineResult, run_import
from jip_api.application.resumes.schema import ResumeParseResult, resume_parse_json_schema
from jip_api.application.resumes.validation import (
    CandidateDraft,
    ValidatedExtraction,
    validate_parse_result,
)

__all__ = [
    "RESUME_IMPORT_TASK",
    "CandidateDraft",
    "ConfirmAction",
    "ConfirmOutcome",
    "ConfirmationResult",
    "Decision",
    "InvalidDecisionError",
    "PipelineResult",
    "ResumeParseOutcome",
    "ResumeParseResult",
    "ResumeParsingService",
    "StartedImport",
    "ValidatedExtraction",
    "confirm_extraction",
    "dispatch",
    "extraction_items",
    "get_document",
    "latest_extraction",
    "latest_job_for_document",
    "list_documents",
    "load_extraction",
    "resume_parse_json_schema",
    "run_import",
    "signed_download_url",
    "start_resume_import",
    "validate_parse_result",
]
