"""Matching use cases."""

from jip_api.application.matching.evidence import ProfileSnapshot, load_profile_snapshot
from jip_api.application.matching.matcher import EvidenceRef, Verdict, match_requirements
from jip_api.application.matching.pipeline import (
    JobNotMatchableError,
    MatchOutcome,
    run_match,
)
from jip_api.application.matching.scoring import CategoryScore, MatchResult, score_match

__all__ = [
    "CategoryScore",
    "EvidenceRef",
    "JobNotMatchableError",
    "MatchOutcome",
    "MatchResult",
    "ProfileSnapshot",
    "Verdict",
    "load_profile_snapshot",
    "match_requirements",
    "run_match",
    "score_match",
]
