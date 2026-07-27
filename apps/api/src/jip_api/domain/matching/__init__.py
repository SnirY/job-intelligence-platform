"""Matching domain.

The deterministic comparison of a job's requirements against a user's career
evidence. No AI anywhere in this package: the rules live in :mod:`rules`, the
transferability relation in :mod:`transferable`, and both are pure functions of
their inputs so the same profile and posting always produce the same number.
"""

from jip_api.domain.matching.models import (
    EvidenceType,
    JobMatch,
    JobMatchEvidence,
    JobMatchItem,
    MatchCategory,
    MatchStatus,
    Recommendation,
)
from jip_api.domain.matching.rules import (
    BLOCKER_CAP,
    MATCHING_ENGINE_VERSION,
    alignment_label,
    can_block,
    category_for,
    recommend,
    score_for,
    weight_for,
    weighted_score,
)
from jip_api.domain.matching.transferable import TRANSFER_GROUPS, TransferGroup, find_transfer

__all__ = [
    "BLOCKER_CAP",
    "MATCHING_ENGINE_VERSION",
    "TRANSFER_GROUPS",
    "EvidenceType",
    "JobMatch",
    "JobMatchEvidence",
    "JobMatchItem",
    "MatchCategory",
    "MatchStatus",
    "Recommendation",
    "TransferGroup",
    "alignment_label",
    "can_block",
    "category_for",
    "find_transfer",
    "recommend",
    "score_for",
    "weight_for",
    "weighted_score",
]
