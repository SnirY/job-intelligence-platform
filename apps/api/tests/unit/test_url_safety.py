"""SSRF protection for URL import.

``docs/11-engineering-standards.md`` lists "private-network URL fetching is
blocked" as a minimum security test. These are that test, and they are real
assertions rather than a comment claiming safety.

The threat: the server can reach things the user cannot — the cloud metadata
endpoint, the database, an internal admin panel — and URL import is the user
handing the server an address to fetch.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from jip_api.infrastructure.fetching.safety import (
    ALLOWED_PORTS,
    UnsafeUrlError,
    is_public_address,
    validate_url,
)


def resolver_returning(*addresses: str) -> object:
    """A fake DNS resolver.

    Injected because the interesting cases — a public name resolving to a
    private address — are exactly the ones that cannot be arranged with a real
    hostname.
    """

    def resolve(host: str, port: int, family: int, kind: int) -> list[tuple[Any, ...]]:
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                kind,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


PUBLIC = resolver_returning("93.184.216.34")


# --- schemes ------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://evil.example.com/",
        "ftp://example.com/jobs",
        "data:text/html,<script>alert(1)</script>",
        "javascript:alert(1)",
        "//example.com/jobs",
    ],
)
def test_only_http_and_https_are_allowed(url: str) -> None:
    """An allowlist, so a scheme nobody thought about is refused by default."""
    with pytest.raises(UnsafeUrlError, match="http"):
        validate_url(url, resolver=PUBLIC)


def test_https_is_allowed() -> None:
    target = validate_url("https://jobs.example.com/role/1", resolver=PUBLIC)

    assert target.scheme == "https"
    assert target.host == "jobs.example.com"
    assert target.is_tls


def test_http_is_allowed() -> None:
    assert validate_url("http://jobs.example.com/role", resolver=PUBLIC).scheme == "http"


# --- literal addresses --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8080/",
        "http://0.0.0.0/",
        "http://10.0.0.5/internal",
        "http://172.16.4.2/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
    ],
)
def test_private_and_local_addresses_are_blocked(url: str) -> None:
    """The metadata endpoint at 169.254.169.254 is the one that returns cloud
    credentials, and it is just another link-local address."""
    with pytest.raises(UnsafeUrlError):
        validate_url(url, resolver=resolver_returning("127.0.0.1"))


def test_ipv4_mapped_ipv6_is_blocked() -> None:
    """``::ffff:127.0.0.1`` is loopback wearing an IPv6 hat, and is the standard
    way past a check that only inspects IPv6 properties."""
    with pytest.raises(UnsafeUrlError):
        validate_url("http://[::ffff:127.0.0.1]/", resolver=PUBLIC)


def test_sixtofour_wrapped_private_address_is_blocked() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url("http://[2002:a00:1::]/", resolver=PUBLIC)


# --- DNS ----------------------------------------------------------------------


def test_a_public_name_resolving_to_a_private_address_is_blocked() -> None:
    """The core of the attack: the name is innocent, the answer is not."""
    with pytest.raises(UnsafeUrlError):
        validate_url("https://jobs.example.com/role", resolver=resolver_returning("10.1.2.3"))


def test_every_resolved_address_is_checked() -> None:
    """A name answering with one public and one private address is refused.

    Fetching over the public one would be a coin flip: whoever controls the
    record controls which address a second lookup returns.
    """
    mixed = resolver_returning("93.184.216.34", "192.168.0.9")

    with pytest.raises(UnsafeUrlError):
        validate_url("https://jobs.example.com/role", resolver=mixed)


def test_the_validated_address_is_returned_for_the_caller_to_connect_to() -> None:
    """Closing the rebinding window.

    Validating a name and then handing the *name* to a socket leaves DNS free
    to answer differently the second time, so the caller is given the address
    that was actually checked.
    """
    target = validate_url("https://jobs.example.com/role", resolver=PUBLIC)

    assert target.address == "93.184.216.34"
    assert target.host == "jobs.example.com", "the Host header must keep the name"


def test_an_unresolvable_name_is_refused() -> None:
    def failing(host: str, port: int, family: int, kind: int) -> list[tuple[Any, ...]]:
        raise OSError("NXDOMAIN")

    with pytest.raises(UnsafeUrlError, match="could not be found"):
        validate_url("https://nope.example.com/", resolver=failing)


def test_a_name_resolving_to_nothing_is_refused() -> None:
    with pytest.raises(UnsafeUrlError, match="could not be found"):
        validate_url("https://nope.example.com/", resolver=resolver_returning())


# --- other URL tricks ---------------------------------------------------------


def test_embedded_credentials_are_refused() -> None:
    """``https://jobs.example.com@10.0.0.1/`` is a request to 10.0.0.1 wearing a
    familiar name."""
    with pytest.raises(UnsafeUrlError, match="credentials"):
        validate_url("https://jobs.example.com@10.0.0.1/", resolver=PUBLIC)


@pytest.mark.parametrize("port", [22, 25, 3306, 5432, 6379, 9200, 11211, 27017])
def test_service_ports_are_refused(port: int) -> None:
    """An allowlist, because a blocklist of dangerous ports is always one
    service out of date — and a job posting has never been served on 6379."""
    with pytest.raises(UnsafeUrlError, match="port"):
        validate_url(f"http://jobs.example.com:{port}/", resolver=PUBLIC)


@pytest.mark.parametrize("port", sorted(ALLOWED_PORTS))
def test_web_ports_are_allowed(port: int) -> None:
    assert validate_url(f"http://jobs.example.com:{port}/x", resolver=PUBLIC).port == port


def test_a_url_without_a_host_is_refused() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url("http:///nohost", resolver=PUBLIC)


def test_the_query_string_survives_validation() -> None:
    """Job boards identify the posting in the query string more often than not."""
    target = validate_url("https://jobs.example.com/search?id=42&x=1", resolver=PUBLIC)

    assert target.path == "/search?id=42&x=1"


# --- the address predicate ----------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.20.0.1", "169.254.169.254", "::1", "fe80::1"],
)
def test_is_public_address_rejects_internal_addresses(address: str) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::"])
def test_is_public_address_accepts_routable_addresses(address: str) -> None:
    assert is_public_address(address)


def test_is_public_address_rejects_nonsense() -> None:
    assert not is_public_address("not-an-address")
