"""Fetching and reading remote pages.

Two responsibilities kept apart, as ``docs/04-system-architecture.md``
requires: getting the bytes safely, and turning them into text. Neither knows
anything about jobs.
"""

from jip_api.infrastructure.fetching.content import (
    ExtractedContent,
    extract_content,
    has_useful_content,
)
from jip_api.infrastructure.fetching.fetcher import FetchError, FetchResult, fetch_url
from jip_api.infrastructure.fetching.safety import (
    SafeTarget,
    UnsafeUrlError,
    is_public_address,
    validate_url,
)

__all__ = [
    "ExtractedContent",
    "FetchError",
    "FetchResult",
    "SafeTarget",
    "UnsafeUrlError",
    "extract_content",
    "fetch_url",
    "has_useful_content",
    "is_public_address",
    "validate_url",
]
