"""Truth validation: does this rewrite still say only what the evidence says?

``docs/06-resume-engine.md`` is categorical:

> Never invent metrics.
> The system may ask the user for missing real metrics, but must not generate
> them.

and ``docs/05-ai-and-matching.md`` requires every generated statement to be
decomposed into claims and checked against verified evidence.

This module is that check, and it is **deterministic**. The model proposes
words; our own code decides whether those words are supported. A validator that
asked a model whether its own output was truthful would be asking the same
system to mark its own homework.

The four things a rewrite can add, from ``docs/06``'s high-risk list:

```text
new technology | new responsibility | new scale | new achievement
```

Numbers are the tractable one and the most damaging, so they get the strictest
rule: a digit that is not in the source facts is BLOCKED, full stop. The others
are caught by comparing content words against the evidence and reporting what
has no support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jip_api.domain.resumes.tailoring import ClaimStatus, SuggestionRisk

_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?%?")
"""A figure, not a digit inside a word.

The lookbehind is what keeps ``p99``, ``S3``, ``IPv6``, and ``OAuth2`` out. They
are names, and treating the digits in them as fabricated metrics would fire the
strictest rule in the module on a technology the person plainly used.
"""

_WORD = re.compile(r"[a-z0-9+#.]+")

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "over",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "under",
        "was",
        "were",
        "will",
        "with",
        "within",
        "your",
        "you",
    ]
)

HIGH_RISK_MARKERS = (
    "led",
    "founded",
    "architected",
    "owned",
    "managed",
    "directed",
    "headed",
    "invented",
    "pioneered",
    "spearheaded",
    "scaled",
    "grew",
    "reduced",
    "increased",
    "improved",
    "saved",
    "generated",
)
"""Verbs that assert scope, leadership, or measurable effect.

Not forbidden — many are true. They raise the *risk* so a person looks, which
is what ``docs/06`` asks for: medium and high-risk suggestions require review.
"""


@dataclass(frozen=True, slots=True)
class Claim:
    """One assertion extracted from a rewrite, with its verdict."""

    text: str
    status: ClaimStatus
    explanation: str
    confidence: int = 50


@dataclass(slots=True)
class TruthReport:
    """Everything validation concluded about one rewrite."""

    claims: list[Claim] = field(default_factory=list)
    risk: SuggestionRisk = SuggestionRisk.LOW

    @property
    def status(self) -> ClaimStatus:
        """The worst claim decides the whole.

        A rewrite is only as trustworthy as its least supported assertion —
        one invented number makes the sentence false regardless of how well the
        rest of it is evidenced.
        """
        for worst in (
            ClaimStatus.BLOCKED,
            ClaimStatus.UNSUPPORTED,
            ClaimStatus.REQUIRES_CONFIRMATION,
        ):
            if any(claim.status is worst for claim in self.claims):
                return worst
        return ClaimStatus.SAFE

    @property
    def may_apply_automatically(self) -> bool:
        return self.status.may_apply_automatically and self.risk is SuggestionRisk.LOW


def validate_rewrite(*, original: str, suggested: str, source_facts: list[str]) -> TruthReport:
    """Check a proposed rewrite against the facts it is allowed to draw on.

    ``source_facts`` is the career evidence behind the item — the achievement's
    own text, the role's description, the skill names. Anything the rewrite
    says that is not traceable to that list is reported.

    Returns a report rather than raising. A suggestion that fails is still
    shown to the user with its problem attached: they may know the number is
    real and add it to their profile, which is the outcome ``docs/06`` wants
    when it says the system may *ask* for missing metrics.
    """
    report = TruthReport()
    haystack = " ".join(source_facts).casefold()

    _check_numbers(report, original=original, suggested=suggested, haystack=haystack)
    _check_content(report, original=original, suggested=suggested, haystack=haystack)

    report.risk = _classify_risk(report, original=original, suggested=suggested)

    if not report.claims:
        report.claims.append(
            Claim(
                text=suggested,
                status=ClaimStatus.SAFE,
                explanation="Says nothing your profile does not already support.",
                confidence=85,
            )
        )

    return report


def _check_numbers(report: TruthReport, *, original: str, suggested: str, haystack: str) -> None:
    """A digit that is not in the evidence is a fabricated metric.

    The strictest rule here, and BLOCKED rather than UNSUPPORTED, because
    ``docs/06`` does not treat an invented number as a judgement call. "Improved
    performance" becoming "improved performance by 40%" is the exact failure it
    names.

    Numbers already in the original are fine: preserving what the user wrote is
    not inventing.
    """
    original_numbers = set(_NUMBER.findall(original))
    evidence_numbers = set(_NUMBER.findall(haystack))

    for number in _NUMBER.findall(suggested):
        if number in original_numbers or number in evidence_numbers:
            continue
        report.claims.append(
            Claim(
                text=number,
                status=ClaimStatus.BLOCKED,
                explanation=(
                    f"“{number}” does not appear anywhere in your profile or in the "
                    "original line. We never add a figure you did not write — if it is "
                    "real, add it to your profile and it becomes usable."
                ),
                confidence=95,
            )
        )


def _check_content(report: TruthReport, *, original: str, suggested: str, haystack: str) -> None:
    """Words the rewrite introduced that nothing supports.

    Weaker than the number rule and deliberately so: rewording is the point of
    a rewrite, and most new words are connective rather than factual. What
    matters is a *content* word that appears in neither the original nor the
    evidence — that is where a new technology or a new responsibility enters.
    """
    # Compared on stems, reported as written. "Engineered features" in the
    # original and "feature engineering" in the rewrite is the same claim in a
    # different grammatical form, and 2026-08-11's walkthrough had the guard
    # report both halves of it as terms the profile does not use. A check that
    # flags plurals teaches people to skim past it, which costs the real
    # warnings sitting in the same list.
    supported = {_stem(word) for word in _words(original)}
    supported |= {_stem(word) for word in _words(haystack)}

    introduced = [word for word in _words(suggested) if _stem(word) not in supported]
    if not introduced:
        return

    # Reported as one claim rather than one per word: a list of six unfamiliar
    # words is a question about the sentence, not six separate questions.
    unique = sorted(set(introduced))[:6]
    report.claims.append(
        Claim(
            text=", ".join(unique),
            status=ClaimStatus.REQUIRES_CONFIRMATION,
            explanation=(
                "This wording introduces terms your profile does not use: "
                f"{', '.join(unique)}. Check that each is something you actually did."
            ),
            confidence=60,
        )
    )


def _classify_risk(report: TruthReport, *, original: str, suggested: str) -> SuggestionRisk:
    """How much a person needs to look at this.

    ``docs/06`` calls grammar, shortening, reordering, and equivalent
    terminology low risk, and a new technology, responsibility, scale, or
    achievement high. The three signals below approximate that ordering
    without pretending to read intent.
    """
    if any(claim.status is ClaimStatus.BLOCKED for claim in report.claims):
        return SuggestionRisk.HIGH

    introduced = set(_words(suggested)) - set(_words(original))
    if introduced & set(HIGH_RISK_MARKERS):
        # A new claim of leadership, ownership, or measurable effect.
        return SuggestionRisk.HIGH

    if any(claim.status is not ClaimStatus.SAFE for claim in report.claims):
        return SuggestionRisk.MEDIUM

    if len(suggested) <= len(original):
        # Shortening or rewording within the same material.
        return SuggestionRisk.LOW

    return SuggestionRisk.MEDIUM


def _words(text: str) -> list[str]:
    """Content words, lowercased.

    Stopwords and short tokens are dropped: "the" appearing in a rewrite and
    not in the evidence is not a factual claim, and treating it as one would
    bury the words that are.

    The trailing full stop has to go with them. ``_WORD`` admits ``.`` so that
    "node.js" and ".net" survive as one token, which also means a sentence-final
    period rides along — and "second." then fails to match "second" in the
    evidence. Left in, the last word of every rewritten sentence looks like a
    newly introduced term, which is exactly the signal this is meant to carry.
    """
    words = []
    for raw in _WORD.findall(text.casefold()):
        word = raw.rstrip(".")
        if len(word) > 2 and word not in _STOPWORDS:
            words.append(word)
    return words


def _stem(word: str) -> str:
    """A crude comparison key, for deciding whether two words are the same claim.

    Used only by :func:`_check_content`, and only for matching — never for
    display, and never by the risk classifier, whose markers are exact words.

    Not linguistics. The stem does not have to be a real word; it has to be the
    *same* for "engineered", "engineering" and "engineer", and *different* for
    "managed" and "manager", which are a thing done and a title held.

    Stripping the trailing ``e`` after the suffix is what makes "manages" and
    "managed" agree — ``manage`` and ``manag`` would otherwise not. The four-
    character floor keeps the rule off short words, where removing two letters
    stops being a suffix and starts being most of the word.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    return word.rstrip("e") if len(word) > 4 else word
