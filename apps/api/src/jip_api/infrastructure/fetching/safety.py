"""Deciding whether a URL is safe to fetch.

``docs/04-system-architecture.md`` and ``docs/11-engineering-standards.md`` both
require SSRF protection, and the standards document names the test: private
network URL fetching must be blocked.

The threat is specific. The server can reach things the user cannot — the cloud
metadata endpoint, the database, an internal admin panel — and a URL import is
the user handing the server an address and asking it to fetch. Without checks,
``http://169.254.169.254/latest/meta-data/iam/`` returns credentials.

Three properties this module provides, in order of how often they are missed:

1. **The scheme is allowlisted.** ``file://``, ``gopher://``, and friends are
   refused rather than being refused later by accident.
2. **Every resolved address is checked, not just the first.** A name resolving
   to one public and one private address must be rejected, not fetched
   because the public one sorted first.
3. **The safe address is returned to the caller.** Validating a hostname and
   then handing the hostname to a socket leaves a window in which DNS answers
   differently the second time — the DNS-rebinding attack. The caller connects
   to the address that was actually checked.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_PORTS = {"http": 80, "https": 443}

ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
"""Ports a public job board plausibly serves on.

An allowlist rather than a blocklist: enumerating every dangerous port —
databases, caches, admin panels, message brokers — is a list that is always one
service out of date, and a job posting has never needed port 6379.
"""


class UnsafeUrlError(Exception):
    """The URL must not be fetched.

    The message is written for the user, because it is shown to them. It says
    what was refused and never why in a way that helps someone map the internal
    network.
    """


@dataclass(frozen=True, slots=True)
class SafeTarget:
    """A URL that passed validation, and where to actually connect."""

    url: str
    scheme: str
    host: str
    """The hostname, for the ``Host`` header and TLS certificate validation."""

    port: int
    address: str
    """A validated IP. The socket connects here, so the name cannot be
    re-resolved to something else between the check and the connection."""

    path: str

    @property
    def is_tls(self) -> bool:
        return self.scheme == "https"


def validate_url(raw: str, *, resolver: object | None = None) -> SafeTarget:
    """Check ``raw`` and return where it is safe to connect.

    ``resolver`` is injected so tests can supply DNS answers without needing a
    network or a hostname that really resolves to a private address — the
    interesting cases are precisely the ones that are awkward to arrange for
    real.

    Raises :class:`UnsafeUrlError` for anything that does not pass.
    """
    parsed = urlsplit(raw.strip())
    scheme = parsed.scheme.lower()

    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only http and https links can be imported.")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("That does not look like a web address.")

    if parsed.username or parsed.password:
        # Credentials in a URL are a classic way to make a hostile address look
        # like a familiar one: https://jobs.example.com@10.0.0.1/ is a request
        # to 10.0.0.1.
        raise UnsafeUrlError("Links with embedded credentials cannot be imported.")

    port = parsed.port or DEFAULT_PORTS[scheme]
    if port not in ALLOWED_PORTS:
        raise UnsafeUrlError("That link uses a port we do not fetch from.")

    address = _resolve_to_public_address(host, port, resolver=resolver)

    return SafeTarget(
        url=raw.strip(),
        scheme=scheme,
        host=host,
        port=port,
        address=address,
        path=parsed.path or "/" if not parsed.query else f"{parsed.path or '/'}?{parsed.query}",
    )


def _resolve_to_public_address(host: str, port: int, *, resolver: object | None) -> str:
    """Resolve ``host`` and return one address, having checked them all.

    Every answer is checked. A name that resolves to both a public and a
    private address is rejected outright rather than fetched over the public
    one: an attacker who controls the record controls which one a second
    lookup returns.
    """
    # A literal address skips DNS but not validation — http://127.0.0.1/ is the
    # simplest version of this attack.
    literal = _as_ip(host)
    if literal is not None:
        _reject_if_not_public(literal)
        return str(literal)

    resolve = resolver if callable(resolver) else socket.getaddrinfo
    try:
        answers = resolve(host, port, 0, socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("That address could not be found.") from exc

    addresses = [str(info[4][0]) for info in answers]
    if not addresses:
        raise UnsafeUrlError("That address could not be found.")

    for candidate in addresses:
        parsed = _as_ip(candidate)
        if parsed is None:
            raise UnsafeUrlError("That address could not be reached safely.")
        _reject_if_not_public(parsed)

    return addresses[0]


def _as_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse ``value`` as an IP address, stripping an IPv6 zone if present."""
    try:
        return ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None


def _reject_if_not_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Refuse anything that is not a routable public address.

    An allowlist by exclusion: every category Python can name as non-global is
    refused, which covers loopback, private ranges, link-local (and with it the
    cloud metadata endpoint at 169.254.169.254), multicast, reserved, and
    unspecified.
    """
    # IPv4 addresses wrapped in IPv6 — ::ffff:127.0.0.1 — are the standard way
    # past a check that only looks at IPv6 properties.
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped or (
            address.sixtofour if address.sixtofour is not None else None
        )
        if mapped is not None:
            _reject_if_not_public(mapped)
            return

    if not address.is_global or address.is_multicast:
        raise UnsafeUrlError("That link points somewhere we will not fetch from.")


def is_public_address(value: str) -> bool:
    """Whether ``value`` is a routable public address. For tests and callers
    that want a check without an exception."""
    parsed = _as_ip(value)
    if parsed is None:
        return False
    try:
        _reject_if_not_public(parsed)
    except UnsafeUrlError:
        return False
    return True
