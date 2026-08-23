"""The rules that read a posting for signs it is not what it claims.

```text
posting text + how long it has been open  ->  a list of concerns, or nothing
```

Deterministic and versioned, like the matcher and for the same reason: a reader
has to be able to ask why, and "the model thought so" is not an answer anyone
can check or argue with. **No model call happens anywhere in this module.**

**The rule that governs everything here, and the reason the module is shaped
this way:**

> A concern never changes the match score, the recommendation, or any ranking.

That is structural rather than a promise. Nothing in `application/matching`
imports this module, nothing here writes to the database, and a concern is not
a number, so there is no value for a future change to accidentally average into
something. A role can be an excellent match and a suspicious posting at once,
and folding either into the other destroys both readings — the user could no
longer tell whether a low figure meant "you do not fit" or "we do not trust this
listing".

## Rules career-ops has and this does not

Worth naming, because their absence is a decision rather than an oversight.

**Company verification.** Checking that an employer exists needs a source of
company data this system does not have and has no plan to buy. A rule that
guessed from a domain name would be confidently wrong about every small company
without a big web presence, which is most of them.

**Compensation plausibility.** Judging a salary as too good to be true needs
market data per role and per region. `salary_text` is deliberately free text —
`docs/03` explains why — and inventing a benchmark to compare it against would
be the fabrication this whole product exists to refuse.

Both are real signals. Neither is one this system can currently evidence, and a
concern it cannot evidence is one it must not raise.
"""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from jip_api.domain.discovery.models import DiscoveredPosting
from jip_api.domain.jobs.legitimacy import (
    ConcernConfidence,
    LegitimacyReading,
    PostingConcern,
    PostingConcernType,
)
from jip_api.domain.jobs.models import Job

RULES_VERSION = "1.0.0"
"""Versioned like the matcher. A concern raised by one version and not the next
is a change worth being able to point at."""

THIN_DESCRIPTION_CHARS = 400
"""Below this, there is not enough posting to judge.

Four hundred characters is roughly a short paragraph. Chosen to sit well under
any real posting rather than near the boundary: a rule that fires on ordinary
short postings teaches the reader to ignore it, and an ignored warning is worse
than none.
"""

LONG_RUNNING_DAYS = 120
"""Four months. Long enough that an ordinary hard-to-fill role has usually
either closed or been re-posted, and long enough not to fire on a role that is
simply taking a while."""

_PAYMENT_PATTERNS = (
    r"\b(?:training|registration|application|onboarding|processing|admin(?:istration)?)\s+fee\b",
    r"\bpay(?:ment)?\s+(?:a\s+)?(?:deposit|fee|upfront)\b",
    r"\bpurchase\s+(?:your own\s+)?(?:equipment|starter kit|software)"
    r"\s+(?:upfront|first|in advance)\b",
    r"\bsend\s+(?:us\s+)?(?:money|funds|payment)\b",
    # "you", not merely "cover": an employer covering the candidate's costs is a
    # benefit, and the first version of this pattern read it as a demand. The
    # false-positive test caught it, which is what that half of the suite is for.
    r"\byou\s+(?:will\s+|must\s+|are\s+expected\s+to\s+)?cover\s+the\s+cost\s+of\b",
)
"""Phrases that describe the applicant paying to be hired.

Written narrowly and anchored on both halves — a payment *and* an obligation on
the applicant. "We cover the cost of your equipment" must not match, and there
is a test that says so.
"""

_NEGATION = re.compile(r"\b(?:no|not|never|without|free\s+of\s+charge)\b", re.IGNORECASE)
"""A denial earlier in the same sentence as a match.

"There is no registration fee" contains "registration fee" and means the
opposite of it. One check in the matcher rather than a negated variant of every
pattern, because the patterns are already the part most likely to be got wrong.

**Scoped to the sentence**, which took two wrong attempts to get right. Looking
only immediately before the match missed "we *never ask you to* pay a deposit" —
a sentence a legitimate employer writes as reassurance, and flagging it would be
the crying-wolf failure this module cares most about. Widening to a fixed window
of characters then swallowed the opposite case, because "There is no
registration fee. **You will pay a deposit of $300**" puts the denial thirty
characters before the demand it does not deny.

A sentence boundary is the thing that actually separates them, and it is also
the rule a reader would give if asked.
"""

_SENTENCE_END = re.compile(r"[.!?\n]")

_OFF_PLATFORM_PATTERNS = (
    r"\b(?:contact|message|text|reach|write to)\s+(?:me|us)\s+(?:on|via|through)\s+"
    r"(?:whats\s?app|telegram|signal|wechat)\b",
    r"\b(?:whats\s?app|telegram)\s*(?:me|us|number|chat)\b",
    r"\binterview\s+(?:will be\s+)?(?:conducted\s+)?(?:on|via|over)\s+"
    r"(?:whats\s?app|telegram|google\s+hangouts?)\b",
)
"""Directing applicants to a personal messaging account.

Naming a messaging app is not enough on its own — a role at a messaging company
mentions them constantly. Each pattern requires the app *and* an instruction to
use it for hiring.
"""

_PAYMENT = tuple(re.compile(p, re.IGNORECASE) for p in _PAYMENT_PATTERNS)
_OFF_PLATFORM = tuple(re.compile(p, re.IGNORECASE) for p in _OFF_PLATFORM_PATTERNS)

_QUOTE_CONTEXT = 60
"""Characters of posting either side of a match, so the quote reads as a
sentence rather than as the fragment the regex happened to catch."""


def read_posting(
    *,
    description: str | None,
    first_seen_at: dt.datetime | None = None,
    posted_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
) -> LegitimacyReading:
    """Every concern the rules raise about one posting.

    Takes values rather than a `Job` so it stays pure and testable, and so
    nothing in here can reach the database and quietly become expensive on a
    list of fifty.

    An empty reading means **no rule fired**. It does not mean the posting is
    trustworthy, and no caller may render it as though it did.
    """
    moment = now or dt.datetime.now(tz=dt.UTC)
    concerns: list[PostingConcern] = []

    if description:
        concerns.extend(_text_concerns(description))
        if len(description.strip()) < THIN_DESCRIPTION_CHARS:
            concerns.append(
                PostingConcern(
                    type=PostingConcernType.THIN_DESCRIPTION,
                    confidence=ConcernConfidence.OBSERVED,
                    summary=(
                        "There is very little text in this posting — not enough to read it "
                        "into requirements with much confidence."
                    ),
                )
            )

    age = _open_days(first_seen_at=first_seen_at, posted_at=posted_at, now=moment)
    if age is not None and age >= LONG_RUNNING_DAYS:
        concerns.append(
            PostingConcern(
                type=PostingConcernType.LONG_RUNNING,
                confidence=ConcernConfidence.OBSERVED,
                summary=(
                    f"This posting has been open for about {age // 30} months. "
                    "That can mean a hard role to fill, or a listing with no headcount "
                    "behind it."
                ),
            )
        )

    # Most serious first, so a screen that truncates does not drop the one that
    # mattered. Stable within a level, which keeps the order reproducible.
    order = {
        ConcernConfidence.NEAR_CERTAIN: 0,
        ConcernConfidence.SUSPICIOUS: 1,
        ConcernConfidence.OBSERVED: 2,
    }
    concerns.sort(key=lambda concern: order[concern.confidence])
    return LegitimacyReading(concerns=concerns)


def for_job(session: Session, job: Job) -> LegitimacyReading:
    """`read_posting` for a stored job, with the dates looked up.

    The only function here that touches the database, and it does nothing but
    gather inputs. `read_posting` stays pure beneath it so the rules can be
    tested without a session and so nothing in them can quietly become a query.

    A job that arrived through discovery has a `first_seen_at` worth using: it
    is a lower bound on how long the role has been advertised, and for a board
    that publishes no date it is the only bound there is.
    """
    first_seen = session.scalar(
        select(DiscoveredPosting.first_seen_at).where(DiscoveredPosting.promoted_job_id == job.id)
    )
    return read_posting(
        description=job.description,
        first_seen_at=first_seen,
        posted_at=job.posted_at,
    )


def _text_concerns(description: str) -> list[PostingConcern]:
    concerns: list[PostingConcern] = []

    payment = _first_match(description, _PAYMENT)
    if payment is not None:
        concerns.append(
            PostingConcern(
                type=PostingConcernType.PAYMENT_REQUESTED,
                confidence=ConcernConfidence.NEAR_CERTAIN,
                summary="This posting asks you to pay something to be hired.",
                evidence=payment,
            )
        )

    off_platform = _first_match(description, _OFF_PLATFORM)
    if off_platform is not None:
        concerns.append(
            PostingConcern(
                type=PostingConcernType.OFF_PLATFORM_CONTACT,
                confidence=ConcernConfidence.SUSPICIOUS,
                summary=(
                    "This posting directs applicants to a personal messaging account rather "
                    "than a company channel."
                ),
                evidence=off_platform,
            )
        )

    return concerns


def _first_match(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    """The posting's own words around the first match, or ``None``.

    Quoted with context because the fragment a regex matches is rarely a
    sentence, and a warning that quotes two words out of context is one the
    reader cannot evaluate.
    """
    for pattern in patterns:
        for found in pattern.finditer(text):
            if _is_denied(text, found.start()):
                # Keep looking rather than stopping: a posting can deny one fee
                # in one sentence and demand another in the next.
                continue
            return _quote(text, found.start(), found.end())
    return None


def _is_denied(text: str, match_start: int) -> bool:
    """Whether a denial appears earlier in the same sentence as the match."""
    sentence_start = 0
    for boundary in _SENTENCE_END.finditer(text, 0, match_start):
        sentence_start = boundary.end()
    return _NEGATION.search(text[sentence_start:match_start]) is not None


def _quote(text: str, start_at: int, end_at: int) -> str:
    """The posting's own words around a match, trimmed to whole whitespace."""
    start = max(0, start_at - _QUOTE_CONTEXT)
    end = min(len(text), end_at + _QUOTE_CONTEXT)
    quote = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{quote}{suffix}"


def _open_days(
    *,
    first_seen_at: dt.datetime | None,
    posted_at: dt.datetime | None,
    now: dt.datetime,
) -> int | None:
    """How long the posting has been open, in days, or ``None`` if unknown.

    The board's own `posted_at` is preferred where it exists: it is when the
    employer published, which is the question. `first_seen_at` is when *we* first
    saw it, which is a lower bound and the best available answer for anything
    that arrived another way.

    Unknown returns `None` and raises nothing. An absent date is not an old
    posting, and this is the same rule invariant 14 keeps on the screen.
    """
    earliest = posted_at or first_seen_at
    if earliest is None:
        return None

    # A naive value is still possible — nothing stops one being constructed —
    # and is read as UTC rather than discarded. Losing "posted three weeks ago"
    # over a missing offset would be the wrong trade.
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=dt.UTC)

    days = (now - earliest).days
    return days if days >= 0 else None
