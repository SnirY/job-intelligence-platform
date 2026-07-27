"""Fetching a job posting from a URL, safely.

Implements the ``JobFetcher`` interface from ``docs/10-api-contracts.md``:
``fetch(url) -> FetchResult``.

Built on ``http.client`` rather than a higher-level library for one reason: it
is the level at which the connection target and the ``Host`` header can be set
separately. Every convenient HTTP client takes a URL and resolves it itself,
which reopens the DNS-rebinding window that :mod:`~.safety` exists to close.
Redirects are followed by hand for the same reason — a library that follows
them for us would follow one to ``169.254.169.254`` without asking.
"""

from __future__ import annotations

import gzip
import http.client
import logging
import socket
import ssl
import zlib
from dataclasses import dataclass, field

from jip_api.infrastructure.fetching.safety import SafeTarget, UnsafeUrlError, validate_url

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5
MAX_CONTENT_BYTES = 3 * 1024 * 1024
"""Ceiling on what is read from a remote server.

An unbounded read from an address the user chose is a denial-of-service the
user can trigger. Three megabytes is far more than any job posting.
"""

USER_AGENT = "JobIntelligencePlatform/0.1 (+resume and job workspace)"

# Textual types worth parsing. The header is not trusted as a security control
# — the body is parsed on its own merits either way — but there is no point
# downloading three megabytes of video to look for a job description in it.
_TEXTUAL_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/")


class FetchError(Exception):
    """The page could not be retrieved. Message is safe to show the user."""

    def __init__(self, message: str, *, code: str, details: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What came back."""

    final_url: str
    status: int
    content_type: str | None
    """As reported by the server. Recorded, never trusted."""

    body: str
    byte_count: int
    redirect_chain: list[str] = field(default_factory=list)


def fetch_url(
    raw_url: str,
    *,
    timeout_seconds: float = 15.0,
    max_bytes: int = MAX_CONTENT_BYTES,
    resolver: object | None = None,
) -> FetchResult:
    """Fetch ``raw_url``, validating every hop.

    Raises :class:`FetchError` for anything that goes wrong, including a URL
    that fails validation — the caller records it against the job and the user
    pastes the description instead.
    """
    chain: list[str] = []
    current = raw_url

    for hop in range(MAX_REDIRECTS + 1):
        try:
            target = validate_url(current, resolver=resolver)
        except UnsafeUrlError as exc:
            # A blocked redirect and a blocked original URL are the same
            # refusal. Saying which hop was blocked would help someone map the
            # internal network one redirect at a time.
            raise FetchError(str(exc), code="BLOCKED_URL") from exc

        response = _request(target, timeout_seconds=timeout_seconds)

        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader("Location")
            response.close()
            if not location:
                raise FetchError("That page redirected to nowhere.", code="BAD_REDIRECT")
            if hop == MAX_REDIRECTS:
                raise FetchError("That page redirected too many times.", code="TOO_MANY_REDIRECTS")

            chain.append(current)
            current = _absolute(target, location)
            continue

        return _read(response, target, current, chain, max_bytes=max_bytes)

    raise FetchError("That page redirected too many times.", code="TOO_MANY_REDIRECTS")


def _pin_to_address(connection: http.client.HTTPConnection, address: str) -> None:
    """Make ``connection`` dial ``address`` instead of resolving its hostname.

    This is the mechanism that closes the DNS-rebinding window. The connection
    keeps the hostname — which is what supplies the ``Host`` header and, over
    TLS, SNI and the certificate check — while the socket goes to the address
    :mod:`~jip_api.infrastructure.fetching.safety` actually validated. Letting
    the socket resolve the name again would let DNS answer a second time with
    something that was never checked.

    Assigned on the *instance*, not overridden as a method, because
    ``HTTPConnection.__init__`` sets ``self._create_connection`` as an instance
    attribute — which shadows any subclass method of the same name. A subclass
    override here looks correct and silently never runs.
    """

    def create_connection(
        target: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        _, port = target
        return socket.create_connection((address, port), timeout, source_address)

    # setattr rather than a direct assignment: `_create_connection` is private
    # to http.client and carries no type stub, so the attribute is invisible to
    # a type checker even though it is exactly what `connect()` calls.
    setattr(connection, "_create_connection", create_connection)  # noqa: B010


def _request(target: SafeTarget, *, timeout_seconds: float) -> http.client.HTTPResponse:
    """Open a connection to the validated address and send the request.

    The socket goes to ``target.address``; the ``Host`` header and, for TLS,
    SNI and the certificate check use ``target.host``. That pairing is the
    whole point: the request reaches the address that was checked, and the
    server still sees and proves the name it was asked for.
    """
    connection: http.client.HTTPConnection
    if target.is_tls:
        connection = http.client.HTTPSConnection(
            target.host,
            port=target.port,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
    else:
        connection = http.client.HTTPConnection(
            target.host, port=target.port, timeout=timeout_seconds
        )
    _pin_to_address(connection, target.address)

    headers = {
        "Host": target.host if target.port in (80, 443) else f"{target.host}:{target.port}",
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }

    try:
        connection.request("GET", target.path, headers=headers)
        return connection.getresponse()
    except ssl.SSLError as exc:
        connection.close()
        raise FetchError(
            "That site's security certificate could not be verified.",
            code="TLS_ERROR",
            details=str(exc),
        ) from exc
    except TimeoutError as exc:
        connection.close()
        raise FetchError("That page took too long to respond.", code="TIMEOUT") from exc
    except OSError as exc:
        connection.close()
        raise FetchError(
            "That page could not be reached.", code="CONNECTION_ERROR", details=str(exc)
        ) from exc


def _read(
    response: http.client.HTTPResponse,
    target: SafeTarget,
    current_url: str,
    chain: list[str],
    *,
    max_bytes: int = MAX_CONTENT_BYTES,
) -> FetchResult:
    """Read a bounded body and decode it."""
    try:
        if response.status >= 400:
            raise FetchError(
                f"That page returned an error ({response.status}).",
                code="HTTP_ERROR",
                details=f"status={response.status}",
            )

        content_type = response.getheader("Content-Type")
        if content_type and not _looks_textual(content_type):
            raise FetchError(
                "That link is not a web page we can read.",
                code="UNSUPPORTED_CONTENT",
                details=f"content_type={content_type}",
            )

        # One byte over the limit is read deliberately, so a body at exactly the
        # limit is distinguishable from one that was truncated.
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise FetchError("That page is too large to import.", code="TOO_LARGE")

        body = _decode(raw, response.getheader("Content-Encoding"), content_type)
    finally:
        response.close()

    logger.info(
        "Fetched job source",
        extra={"host": target.host, "status": response.status, "bytes": len(raw)},
    )

    return FetchResult(
        final_url=current_url,
        status=response.status,
        content_type=content_type,
        body=body,
        byte_count=len(raw),
        redirect_chain=chain,
    )


def _decode(raw: bytes, encoding: str | None, content_type: str | None) -> str:
    """Decompress and decode a response body.

    Errors are replaced rather than raised: a posting with one bad byte in it
    is still a posting, and failing the whole import over an encoding
    disagreement would be worse than a single replacement character.
    """
    if encoding:
        lowered = encoding.lower()
        try:
            if "gzip" in lowered:
                raw = gzip.decompress(raw)
            elif "deflate" in lowered:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except (OSError, zlib.error) as exc:
            raise FetchError(
                "That page's content could not be read.",
                code="DECODE_ERROR",
                details=str(exc),
            ) from exc

    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip() or "utf-8"

    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        # An unknown charset name is the server's problem, not a reason to lose
        # the page.
        return raw.decode("utf-8", errors="replace")


def _looks_textual(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(lowered.startswith(prefix) or prefix in lowered for prefix in _TEXTUAL_TYPES)


def _absolute(target: SafeTarget, location: str) -> str:
    """Resolve a ``Location`` header against the URL that produced it."""
    from urllib.parse import urljoin

    base = f"{target.scheme}://{target.host}"
    if target.port not in (80, 443):
        base = f"{base}:{target.port}"
    return urljoin(f"{base}{target.path}", location.strip())
