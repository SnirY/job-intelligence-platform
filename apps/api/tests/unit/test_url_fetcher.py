"""The URL fetcher, against a real local HTTP server.

A live socket rather than a mock, because the properties worth testing are
about what actually goes over the wire: which address the socket dials, what
the ``Host`` header says, and whether a redirect is re-validated. A mocked
client would assert that the code calls itself the way it calls itself.

The IP-pinning test is the important one. It is the mechanism that closes the
DNS-rebinding window, and it is easy to write a version that looks correct and
silently never runs — which is exactly what happened to a subclass-based first
attempt at it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from jip_api.infrastructure.fetching.fetcher import FetchError, _read, _request, fetch_url
from jip_api.infrastructure.fetching.safety import SafeTarget

PAGE = (
    b"<html><head><title>Backend Engineer</title></head><body><main><p>"
    + b"We are hiring a backend engineer in Lisbon. " * 20
    + b"</p></main></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    """Serves whatever the test configured, and records what it received."""

    # Class-level so each test's subclass gets its own, set by the fixture.
    routes: ClassVar[dict[str, tuple[int, dict[str, str], bytes]]] = {}
    seen: ClassVar[dict[str, Any]] = {}

    def do_GET(self) -> None:
        type(self).seen["host"] = self.headers.get("Host")
        type(self).seen["path"] = self.path
        type(self).seen["user_agent"] = self.headers.get("User-Agent")

        status, headers, body = type(self).routes.get(
            self.path.split("?")[0], (200, {"Content-Type": "text/html"}, PAGE)
        )
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


@pytest.fixture
def server() -> Iterator[tuple[int, type[_Handler]]]:
    handler = type("BoundHandler", (_Handler,), {"routes": {}, "seen": {}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def target_for(port: int, path: str = "/role/42", host: str = "jobs.example.com") -> SafeTarget:
    """A target whose *name* is public and whose validated *address* is local.

    Exactly the shape pinning has to honour: connect to the checked address,
    present the checked name.
    """
    return SafeTarget(
        url=f"http://{host}:{port}{path}",
        scheme="http",
        host=host,
        port=port,
        address="127.0.0.1",
        path=path,
    )


# --- pinning ------------------------------------------------------------------


def test_the_socket_dials_the_validated_address(server: tuple[int, type[_Handler]]) -> None:
    """The request reaches the address safety checked, not a re-resolved name.

    The hostname here does not resolve to 127.0.0.1 anywhere; the only reason
    the local server sees the request at all is the pin.
    """
    port, _ = server

    response = _request(target_for(port), timeout_seconds=5)
    result = _read(response, target_for(port), f"http://jobs.example.com:{port}/role/42", [])

    assert result.status == 200


def test_the_host_header_carries_the_name_not_the_address(
    server: tuple[int, type[_Handler]],
) -> None:
    """Sending the IP would break every virtual-hosted site — which is most of
    the web — and the whole point is to keep the name intact."""
    port, handler = server

    _request(target_for(port), timeout_seconds=5).close()

    assert handler.seen["host"] == f"jobs.example.com:{port}"


def test_the_path_and_query_are_sent_intact(server: tuple[int, type[_Handler]]) -> None:
    port, handler = server

    _request(target_for(port, "/role/42?id=7"), timeout_seconds=5).close()

    assert handler.seen["path"] == "/role/42?id=7"


def test_a_user_agent_identifies_the_platform(server: tuple[int, type[_Handler]]) -> None:
    """A blank user agent gets blocked by a good share of sites, and an honest
    one is what a well-behaved fetcher sends."""
    port, handler = server

    _request(target_for(port), timeout_seconds=5).close()

    assert "JobIntelligencePlatform" in handler.seen["user_agent"]


# --- reading ------------------------------------------------------------------


def test_reads_the_body(server: tuple[int, type[_Handler]]) -> None:
    port, _ = server
    target = target_for(port)

    result = _read(_request(target, timeout_seconds=5), target, target.url, [])

    assert "backend engineer in Lisbon" in result.body
    assert result.byte_count == len(PAGE)


def test_an_http_error_is_reported(server: tuple[int, type[_Handler]]) -> None:
    port, handler = server
    handler.routes["/gone"] = (404, {"Content-Type": "text/html"}, b"not found")
    target = target_for(port, "/gone")

    with pytest.raises(FetchError) as caught:
        _read(_request(target, timeout_seconds=5), target, target.url, [])

    assert caught.value.code == "HTTP_ERROR"


def test_a_non_textual_response_is_refused(server: tuple[int, type[_Handler]]) -> None:
    """Not a security control — the body is parsed on its own merits either way
    — but there is no point downloading a video to look for prose in it."""
    port, handler = server
    handler.routes["/binary"] = (200, {"Content-Type": "image/png"}, b"\x89PNG" * 100)
    target = target_for(port, "/binary")

    with pytest.raises(FetchError) as caught:
        _read(_request(target, timeout_seconds=5), target, target.url, [])

    assert caught.value.code == "UNSUPPORTED_CONTENT"


def test_an_oversized_body_is_refused(server: tuple[int, type[_Handler]]) -> None:
    """An unbounded read from an address the user chose is a denial of service
    the user can trigger."""
    port, handler = server
    handler.routes["/big"] = (200, {"Content-Type": "text/html"}, b"x" * 5000)
    target = target_for(port, "/big")

    with pytest.raises(FetchError) as caught:
        _read(_request(target, timeout_seconds=5), target, target.url, [], max_bytes=1000)

    assert caught.value.code == "TOO_LARGE"


def test_a_body_at_exactly_the_limit_is_accepted(server: tuple[int, type[_Handler]]) -> None:
    """The off-by-one that would reject a page for being exactly big enough."""
    port, handler = server
    handler.routes["/exact"] = (200, {"Content-Type": "text/html"}, b"x" * 1000)
    target = target_for(port, "/exact")

    result = _read(_request(target, timeout_seconds=5), target, target.url, [], max_bytes=1000)

    assert result.byte_count == 1000


def test_the_declared_charset_is_used(server: tuple[int, type[_Handler]]) -> None:
    port, handler = server
    handler.routes["/latin"] = (
        200,
        {"Content-Type": "text/html; charset=iso-8859-1"},
        "Café Engineer".encode("iso-8859-1"),
    )
    target = target_for(port, "/latin")

    result = _read(_request(target, timeout_seconds=5), target, target.url, [])

    assert "Café Engineer" in result.body


def test_an_unknown_charset_does_not_lose_the_page(server: tuple[int, type[_Handler]]) -> None:
    """A server declaring a charset that does not exist is the server's
    problem, not a reason to drop the posting."""
    port, handler = server
    handler.routes["/weird"] = (200, {"Content-Type": "text/html; charset=nonsense-8"}, PAGE)
    target = target_for(port, "/weird")

    assert (
        "backend engineer"
        in _read(_request(target, timeout_seconds=5), target, target.url, []).body
    )


# --- redirects ----------------------------------------------------------------
#
# The transport is stubbed here and the *policy* is left real. That split is
# deliberate: a redirect to the metadata endpoint has to be refused by the same
# `validate_url` the production path uses, not by a test double that agrees
# with the test. The address policy has its own suite in `test_url_safety.py`;
# the socket has the pinning tests above.


class _StubResponse:
    """The parts of an HTTPResponse the redirect loop touches."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status = status
        self._headers = headers
        self._body = body
        self.closed = False

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name, default)

    def read(self, amount: int | None = None) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


def public_resolver() -> object:
    """Resolves any name to a routable address, so validation passes."""

    def resolve(host: str, port: int, family: int, kind: int) -> list[tuple[Any, ...]]:
        return [(2, kind, 6, "", ("93.184.216.34", port))]

    return resolve


@pytest.fixture
def stubbed_transport(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace only the socket layer, keeping validation real."""
    from jip_api.infrastructure.fetching import fetcher

    state: dict[str, Any] = {"routes": {}, "requested": []}

    def fake_request(target: SafeTarget, *, timeout_seconds: float) -> Any:
        state["requested"].append(target.url)
        path = target.path.split("?")[0]
        status, headers, body = state["routes"].get(
            path, (200, {"Content-Type": "text/html"}, PAGE)
        )
        return _StubResponse(status, headers, body)

    monkeypatch.setattr(fetcher, "_request", fake_request)
    return state


def fetch(path: str = "/role") -> Any:
    return fetch_url(f"https://jobs.example.com{path}", resolver=public_resolver())


def test_a_redirect_is_followed(stubbed_transport: dict[str, Any]) -> None:
    stubbed_transport["routes"]["/old"] = (
        301,
        {"Location": "https://jobs.example.com/new"},
        b"",
    )

    result = fetch("/old")

    assert result.status == 200
    assert result.redirect_chain == ["https://jobs.example.com/old"]
    assert result.final_url == "https://jobs.example.com/new"


def test_a_relative_redirect_resolves_against_the_current_url(
    stubbed_transport: dict[str, Any],
) -> None:
    stubbed_transport["routes"]["/old"] = (302, {"Location": "/moved"}, b"")

    fetch("/old")

    assert "https://jobs.example.com/moved" in stubbed_transport["requested"]


def test_a_redirect_loop_is_stopped(stubbed_transport: dict[str, Any]) -> None:
    stubbed_transport["routes"]["/loop"] = (
        302,
        {"Location": "https://jobs.example.com/loop"},
        b"",
    )

    with pytest.raises(FetchError) as caught:
        fetch("/loop")

    assert caught.value.code == "TOO_MANY_REDIRECTS"


def test_a_redirect_to_the_metadata_endpoint_is_refused(
    stubbed_transport: dict[str, Any],
) -> None:
    """The hop that matters.

    A library following redirects for us would follow this one without asking,
    which is why they are followed by hand and each is re-validated by the real
    policy.
    """
    stubbed_transport["routes"]["/away"] = (
        302,
        {"Location": "http://169.254.169.254/latest/meta-data/"},
        b"",
    )

    with pytest.raises(FetchError) as caught:
        fetch("/away")

    assert caught.value.code == "BLOCKED_URL"
    assert "169.254.169.254" not in str(caught.value), "the blocked address must not be echoed"


@pytest.mark.parametrize(
    "location",
    ["http://127.0.0.1/admin", "http://10.0.0.5/internal", "http://[::1]/", "file:///etc/passwd"],
)
def test_a_redirect_to_any_blocked_destination_is_refused(
    stubbed_transport: dict[str, Any], location: str
) -> None:
    stubbed_transport["routes"]["/away"] = (302, {"Location": location}, b"")

    with pytest.raises(FetchError) as caught:
        fetch("/away")

    assert caught.value.code == "BLOCKED_URL"


def test_a_redirect_with_no_location_is_reported(stubbed_transport: dict[str, Any]) -> None:
    stubbed_transport["routes"]["/nowhere"] = (302, {"Content-Type": "text/html"}, b"")

    with pytest.raises(FetchError) as caught:
        fetch("/nowhere")

    assert caught.value.code == "BAD_REDIRECT"


def test_a_blocked_url_never_opens_a_connection() -> None:
    """Validation runs before any socket, so a refused address is never
    contacted at all — not even to be told no."""
    with pytest.raises(FetchError) as caught:
        fetch_url("http://169.254.169.254/latest/meta-data/", timeout_seconds=1)

    assert caught.value.code == "BLOCKED_URL"
