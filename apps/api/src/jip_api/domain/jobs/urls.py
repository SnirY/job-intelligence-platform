"""Reducing a job URL to a comparison key.

Two links to the same posting rarely match byte for byte: one carries a
tracking parameter, one has a trailing slash, one came from a mobile
subdomain. Comparing raw URLs would report almost nothing as a duplicate,
which is the same as having no duplicate detection at all.

Normalization is deliberately conservative. Over-normalizing is worse than
under-normalizing here: a false duplicate blocks a genuinely new job behind a
409 the user has to override, while a missed one costs them a second card in
the list.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Campaign and referral parameters. Present or absent, the page is the same —
# these describe how the user arrived, not what they arrived at.
_TRACKING_PREFIXES = ("utm_", "pk_", "mc_", "ga_")
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "msclkid",
        "igshid",
        "mkt_tok",
        "ref",
        "referer",
        "referrer",
        "source",
        "src",
        "trk",
        "trackingid",
        "tracking_id",
        "originalsubdomain",
        "refid",
    }
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(raw: str) -> str | None:
    """Return a comparison key for ``raw``, or ``None`` if it is not a web URL.

    Applies only changes that cannot alter which page is addressed:

    - scheme and host lowercased (both are case-insensitive by definition);
    - ``https`` and ``http`` treated as the same page, since a posting served
      over both is one posting;
    - default port dropped;
    - a leading ``www.`` and a leading ``m.`` dropped;
    - tracking parameters removed and the rest sorted;
    - the fragment dropped, since it never reaches the server.

    The path keeps its case: plenty of sites route on case-sensitive
    identifiers, and lowercasing one would merge two different postings.
    """
    parsed = urlsplit(raw.strip())

    if parsed.scheme.lower() not in _DEFAULT_PORTS or not parsed.hostname:
        return None

    host = parsed.hostname.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix) and host.count(".") > 1:
            host = host[len(prefix) :]
            break

    netloc = host
    if parsed.port is not None and parsed.port != _DEFAULT_PORTS[parsed.scheme.lower()]:
        netloc = f"{host}:{parsed.port}"

    query = urlencode(sorted(_keep_meaningful(parsed.query)))
    path = parsed.path.rstrip("/") or "/"

    # Scheme is fixed rather than preserved: the key exists to answer "is this
    # the same posting", and http vs https never changes the answer.
    return urlunsplit(("https", netloc, path, query, ""))


def _keep_meaningful(query: str) -> list[tuple[str, str]]:
    """Drop tracking parameters, keep everything else.

    Everything else is kept because a query parameter is how most job boards
    identify the posting at all — dropping an unrecognised one would collapse
    every job on the site into a single key.
    """
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PREFIXES):
            continue
        kept.append((key, value))
    return kept
