"""What a board returns, before this system has an opinion about it.

`RawPosting` is deliberately not a `Job`. It carries what the board said and
nothing derived from it: no requirements, no seniority, no role family, no
score. Those are readings, they come from `JOB_PARSE` and `JOB_ANALYSIS`, and a
posting arriving through discovery goes through exactly the same pipeline as one
a person pasted.

That separation is the whole reason this package holds no ORM model and imports
nothing from the API. A board is a source of text. It is not a source of
judgement, and there must be no shape here that could carry one.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

BOARD_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
"""What a board identifier is allowed to look like.

Every provider here builds a URL by putting this straight into the path. The
host is fixed by the provider module and never comes from configuration, so the
one thing a token could otherwise do is walk out of the path it was given —
`../../` , a `?` that rewrites the query, a `@` that moves the authority.

Validated at construction rather than at the call site, so there is no way to
reach a provider with a token nobody checked.
"""


class InvalidBoard(ValueError):
    """The board identifier is not usable in a URL path."""


@dataclass(frozen=True, slots=True)
class BoardRef:
    """One company's board on one provider.

    These endpoints are per-company: there is no global search across
    Greenhouse, only `boards-api.greenhouse.io/.../{board}`. Discovery is
    therefore "watch these companies", which is a different product promise from
    "search the market" and the honest one to build.
    """

    provider: str
    token: str
    """The company's identifier on that provider. Greenhouse calls it a board
    token, Lever a site, Ashby a job-board name."""

    label: str | None = None
    """What to call the company on screen, when the board does not say."""

    def __post_init__(self) -> None:
        if not BOARD_TOKEN.match(self.token):
            raise InvalidBoard(f"{self.token!r} is not a valid board identifier")


@dataclass(frozen=True, slots=True)
class RawPosting:
    """One posting, as the board described it.

    Every field is either something the board stated or `None`. Nothing is
    inferred and nothing is filled in with a default that would read as a fact —
    an absent location is `None`, never "Remote", and an absent date is `None`,
    never today.
    """

    provider: str
    board: str
    external_id: str
    """The board's own id. Stable across runs, which is what makes a second scan
    recognise a posting it has already seen."""

    title: str
    url: str
    company: str | None = None
    location: str | None = None
    posted_at: dt.datetime | None = None

    # Two fields rather than one, because the boards genuinely differ and a
    # single `description` would be text from Lever and Ashby and markup from
    # Greenhouse — a field whose meaning depends on where the row came from.
    # Either may be absent. A caller wanting text prefers `description_text`
    # and extracts from `description_html` when only that is there, which is the
    # same path a pasted page already takes.
    description_text: str | None = None
    description_html: str | None = None
