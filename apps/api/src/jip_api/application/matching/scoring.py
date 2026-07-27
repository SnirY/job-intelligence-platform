"""Turning verdicts into a score, category scores, and a recommendation.

Pure arithmetic over the rules in :mod:`jip_api.domain.matching.rules`. No AI
touches this file — ``docs/05-ai-and-matching.md`` puts final deterministic
scoring on the list of things AI must not control, and the goal repeats it.

The formula is the document's:

```text
Weighted Match = sum(requirement_score * requirement_weight)
                 / sum(requirement_weight)
```

with one deviation, which the goal requires: NO_EVIDENCE items are dropped from
*both* sides of the division rather than scored zero. An incomplete profile
must not automatically reduce the score, and scoring an unknown as a failure is
exactly that reduction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from jip_api.application.matching.matcher import Verdict
from jip_api.domain.matching.models import MatchCategory, MatchStatus, Recommendation
from jip_api.domain.matching.rules import (
    BLOCKER_CAP,
    alignment_label,
    recommend,
    weighted_score,
)


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """One category's contribution."""

    category: MatchCategory
    score: int | None
    weight: float
    item_count: int
    scored_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "category": str(self.category),
            "score": self.score,
            "weight": round(self.weight, 2),
            "item_count": self.item_count,
            "scored_count": self.scored_count,
        }


@dataclass(slots=True)
class MatchResult:
    """Everything scoring produced."""

    overall_score: int | None
    alignment_label: str
    recommendation: Recommendation
    recommendation_reasons: list[str]
    confidence: int
    category_scores: list[CategoryScore]
    status_counts: dict[str, int]
    has_blockers: bool
    score_cap: int | None
    score_cap_reason: str | None
    scored_requirements: int
    total_requirements: int
    warnings: list[str] = field(default_factory=list)

    def category_scores_json(self) -> dict[str, object]:
        return {str(c.category): c.as_dict() for c in self.category_scores}


def score_match(verdicts: list[Verdict]) -> MatchResult:
    """Score a set of verdicts. Deterministic and total.

    Handles the empty case rather than dividing by zero: a posting whose
    requirements we could not assess at all produces a null score and a
    recommendation that says why, which is more useful than a confident 0%.
    """
    status_counts = _count_statuses(verdicts)
    scored = [(v.score, v.weight) for v in verdicts if v.status.is_scored]

    # A score needs at least one verdict that actually engaged with the
    # profile. Without this, a posting whose only assessable requirement is an
    # UNKNOWN — work authorisation, say — reports 35 against an empty profile,
    # which looks like a measurement and is really just the neutral constant
    # wearing a percentage sign. UNKNOWN keeps its documented 35 in every mixed
    # case; what it may not do is be the whole basis of a number.
    engaged = any(
        verdict.status.is_positive or verdict.status in {MatchStatus.GAP, MatchStatus.BLOCKER}
        for verdict in verdicts
    )
    raw_score = weighted_score(scored) if engaged else None

    blockers = [v for v in verdicts if v.is_blocker]
    has_blockers = bool(blockers)

    score = raw_score
    cap: int | None = None
    cap_reason: str | None = None

    if has_blockers and raw_score is not None and raw_score > BLOCKER_CAP:
        # docs/05-ai-and-matching.md: real blockers may cap the overall score.
        # Capping rather than zeroing, because the rest of the match is still
        # true and the user may well disagree with our reading of the blocker.
        cap = BLOCKER_CAP
        cap_reason = (
            f"Capped at {BLOCKER_CAP} because "
            f"{len(blockers)} essential requirement{'s' if len(blockers) != 1 else ''} "
            "has no evidence in your profile."
        )
        score = BLOCKER_CAP

    unmet_core = len(blockers)
    unmet_required = sum(
        1
        for v in verdicts
        if v.status in {MatchStatus.GAP, MatchStatus.BLOCKER} and v.weight >= Decimal("2.00")
    )

    total = len(verdicts)
    scored_count = len(scored)
    assessable_ratio = scored_count / total if total else 0.0

    recommendation, reasons = recommend(
        score=score,
        has_blockers=has_blockers,
        unmet_core=unmet_core,
        unmet_required=unmet_required,
        assessable_ratio=assessable_ratio,
    )

    warnings: list[str] = []
    if total and scored_count < total:
        skipped = total - scored_count
        warnings.append(
            f"{skipped} requirement{'s' if skipped != 1 else ''} could not be checked against "
            "your profile and {} left out of the score.".format("were" if skipped != 1 else "was")
        )

    return MatchResult(
        overall_score=score,
        alignment_label=alignment_label(score),
        recommendation=recommendation,
        recommendation_reasons=reasons,
        confidence=_confidence(verdicts, assessable_ratio),
        category_scores=_category_scores(verdicts),
        status_counts=status_counts,
        has_blockers=has_blockers,
        score_cap=cap,
        score_cap_reason=cap_reason,
        scored_requirements=scored_count,
        total_requirements=total,
        warnings=warnings,
    )


def _count_statuses(verdicts: list[Verdict]) -> dict[str, int]:
    """Every status, including the zeroes.

    All eight keys always present: a client rendering a bar chart should not
    have to know which statuses exist, and a missing key reads as a rendering
    bug rather than as an empty bucket.
    """
    counts = {str(status): 0 for status in MatchStatus}
    for verdict in verdicts:
        counts[str(verdict.status)] += 1
    return counts


def _category_scores(verdicts: list[Verdict]) -> list[CategoryScore]:
    """Per-category scores, in a stable order.

    PROJECTS is derived rather than assigned: no requirement asks for "a
    project", so the category measures how much of the alignment is carried by
    things the user built. An item can therefore appear in both its own
    category and in PROJECTS, which is the intent — the two answer different
    questions.
    """
    scores: list[CategoryScore] = []

    for category in MatchCategory:
        if category is MatchCategory.PROJECTS:
            continue
        items = [v for v in verdicts if v.category is category]
        if items:
            scores.append(_score_group(category, items))

    project_items = [v for v in verdicts if v.from_project]
    if project_items:
        scores.append(_score_group(MatchCategory.PROJECTS, project_items))

    return scores


def _score_group(category: MatchCategory, items: list[Verdict]) -> CategoryScore:
    scored = [(v.score, v.weight) for v in items if v.status.is_scored]
    return CategoryScore(
        category=category,
        score=weighted_score(scored),
        weight=float(sum((v.weight for v in items), Decimal("0"))),
        item_count=len(items),
        scored_count=len(scored),
    )


def _confidence(verdicts: list[Verdict], assessable_ratio: float) -> int:
    """How much to trust this match.

    Two things drag it down: requirements we could not assess at all, and
    verdicts we were individually unsure about. Both matter — a match built
    from ten confident readings of two thirds of a posting deserves a different
    caveat from one built on shaky readings of all of it.
    """
    if not verdicts:
        return 0

    mean_item_confidence = sum(v.confidence for v in verdicts) / len(verdicts)
    return max(0, min(100, int(mean_item_confidence * 0.6 + assessable_ratio * 100 * 0.4)))
