"""Reading public applicant-tracking boards into postings.

Three providers — Greenhouse, Ashby, Lever — each a documented, public,
unauthenticated JSON endpoint. Auth-gated sources are deliberately absent and
belong nowhere near this package.

The boundary this package keeps: **a board is a source of text, never a source
of judgement.** Nothing here produces a requirement, a score, a seniority or a
role family, and nothing here writes to a database. A discovered posting enters
the same pipeline a pasted one does, which is what stops discovery becoming a
second, quieter way of deciding what a job is.
"""

from jip_sources.base import JobSource
from jip_sources.http import BoardUnavailable
from jip_sources.models import BoardRef, InvalidBoard, RawPosting
from jip_sources.registry import (
    PROVIDERS,
    BoardOutcome,
    ScanResult,
    UnknownProvider,
    get_provider,
    scan,
)

__all__ = [
    "PROVIDERS",
    "BoardOutcome",
    "BoardRef",
    "BoardUnavailable",
    "InvalidBoard",
    "JobSource",
    "RawPosting",
    "ScanResult",
    "UnknownProvider",
    "get_provider",
    "scan",
]
