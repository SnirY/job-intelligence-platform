"""One HTTP client, for talking to boards.

Separate from `apps/api`'s `infrastructure/fetching` on purpose, and the reason
is the threat, not the layering. That module fetches a URL **the user typed**,
so it spends most of its code closing SSRF: resolving the host, refusing private
addresses, pinning the socket to the checked address, re-validating every
redirect.

Nothing here takes a URL from anyone. The host is a constant inside each
provider module and the only variable is a board token, which `BoardRef`
validates before it can exist. So this client's job is smaller: be a polite
client of somebody else's API, and never hang.

What it does carry, because a package that makes outbound requests must:

- a bounded timeout, so a slow board cannot hold a worker;
- a bounded read, so a board cannot be a memory exhaustion;
- an honest User-Agent, because a blank one is both rude and widely blocked;
- refusal of any redirect that leaves the host it was given.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "JobIntelligencePlatform/0.1 (+resume and job workspace)"

DEFAULT_TIMEOUT_SECONDS = 15.0

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
"""Boards return every open role in one document, so this is larger than the
per-page limit the URL fetcher uses. Eight megabytes is still far beyond any
board observed and well short of a problem."""


class BoardUnavailable(Exception):
    """The board could not be read. Never raised for an empty board.

    A board with no open roles is a successful answer, and treating it as a
    failure would turn a quiet week into an error the user has to dismiss.
    """

    def __init__(self, message: str, *, code: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    These are documented JSON APIs at fixed hosts. A redirect means the host is
    doing something this code was not written against — a login wall, a
    consent interstitial, a move to another domain — and following it would mean
    parsing whatever came back as if it were a board. Failing is the honest
    answer, and the provider module records which board it was.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def get_json(url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> Any:
    """Fetch ``url`` and parse it as JSON.

    Raises :class:`BoardUnavailable` for everything that can go wrong, so a
    caller scanning ten boards can lose one without losing the run.
    """
    if urlsplit(url).scheme != "https":
        # Not a user-supplied URL, so this is an assertion about this package's
        # own provider modules rather than a defence. It costs nothing and would
        # catch a template edited into plain HTTP.
        raise BoardUnavailable("Board URLs must be HTTPS.", code="INSECURE_URL")

    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )

    try:
        with _OPENER.open(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        # 404 here means the board token is wrong, which is a configuration
        # problem the user can fix, so the status travels with the failure.
        raise BoardUnavailable(
            f"The board returned {error.code}.", code="HTTP_ERROR", status=error.code
        ) from error
    except urllib.error.URLError as error:
        raise BoardUnavailable(
            f"The board could not be reached: {error.reason}", code="UNREACHABLE"
        ) from error
    except TimeoutError as error:
        raise BoardUnavailable("The board did not answer in time.", code="TIMEOUT") from error

    if len(raw) > MAX_RESPONSE_BYTES:
        raise BoardUnavailable("The board returned more than we will read.", code="TOO_LARGE")

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        # Usually an HTML error page served with a 200. Distinct from a
        # transport failure because it means the endpoint shape has changed,
        # which is a defect here rather than a bad day at the far end.
        raise BoardUnavailable("The board did not return JSON.", code="NOT_JSON") from error
