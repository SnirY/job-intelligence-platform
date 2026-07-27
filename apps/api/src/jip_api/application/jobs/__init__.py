"""Job workspace use cases.

Split by responsibility: ``creation`` adds and detects duplicates, ``queries``
reads, ``updates`` edits and archives, ``importing`` runs the URL fetch.
"""

from jip_api.application.jobs.creation import (
    DuplicateJobError,
    JobInput,
    apply_fetched_content,
    content_hash,
    create_job,
    find_duplicate,
    latest_import,
    list_imports,
    mark_fetch_failed,
    record_import,
)
from jip_api.application.jobs.importing import FETCH_JOB_TASK, ImportOutcome, run_url_import
from jip_api.application.jobs.queries import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ArchivedFilter,
    JobFilters,
    JobPage,
    JobSort,
    get_job,
    known_companies,
    list_jobs,
)
from jip_api.application.jobs.updates import (
    JobUpdate,
    archive_job,
    delete_job,
    supply_description,
    unarchive_job,
    update_job,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "FETCH_JOB_TASK",
    "MAX_PAGE_SIZE",
    "ArchivedFilter",
    "DuplicateJobError",
    "ImportOutcome",
    "JobFilters",
    "JobInput",
    "JobPage",
    "JobSort",
    "JobUpdate",
    "apply_fetched_content",
    "archive_job",
    "content_hash",
    "create_job",
    "delete_job",
    "find_duplicate",
    "get_job",
    "known_companies",
    "latest_import",
    "list_imports",
    "list_jobs",
    "mark_fetch_failed",
    "record_import",
    "run_url_import",
    "supply_description",
    "unarchive_job",
    "update_job",
]
