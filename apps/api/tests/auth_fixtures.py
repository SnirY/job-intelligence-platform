"""Local token minting for authentication tests.

Tests never call Clerk. A keypair is generated once per session, served as a
JWKS document, and used to sign tokens. The verification path under test is the
real one — only the key source is local, so a regression in signature, issuer,
expiry, or authorized-party checking still fails the suite.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.utils import base64url_encode

ISSUER = "https://test-instance.clerk.accounts.dev"
AUTHORIZED_PARTY = "http://localhost:3000"
KEY_ID = "test-key-1"


def _b64_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64url_encode(value.to_bytes(length, "big")).decode("ascii")


@dataclass(frozen=True)
class TokenFactory:
    """Mints signed tokens and the matching JWKS document."""

    private_pem: bytes
    jwks: dict[str, Any]
    key_id: str = KEY_ID

    @classmethod
    def create(cls, key_id: str = KEY_ID) -> TokenFactory:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = key.public_key().public_numbers()

        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": key_id,
                    "n": _b64_uint(numbers.n),
                    "e": _b64_uint(numbers.e),
                }
            ]
        }

        private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return cls(private_pem=private_pem, jwks=jwks, key_id=key_id)

    def token(
        self,
        *,
        subject: str = "user_test_default",
        issuer: str | None = ISSUER,
        azp: str | None = AUTHORIZED_PARTY,
        expires_in: dt.timedelta = dt.timedelta(minutes=1),
        not_before: dt.timedelta | None = None,
        email: str | None = None,
        name: str | None = None,
        key_id: str | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Mint a token. Every argument exists so a test can make it invalid."""
        now = dt.datetime.now(tz=dt.UTC)
        claims: dict[str, Any] = {
            "sub": subject,
            "sid": "sess_test",
            "iat": int(now.timestamp()),
            "exp": int((now + expires_in).timestamp()),
        }
        if issuer is not None:
            claims["iss"] = issuer
        if azp is not None:
            claims["azp"] = azp
        if not_before is not None:
            claims["nbf"] = int((now + not_before).timestamp())
        if email is not None:
            claims["email"] = email
        if name is not None:
            claims["name"] = name
        if extra_claims:
            claims.update(extra_claims)

        return jwt.encode(
            claims,
            self.private_pem,
            algorithm="RS256",
            headers={"kid": key_id or self.key_id},
        )

    def jwks_json(self) -> str:
        return json.dumps(self.jwks)


class _JwksHandler(BaseHTTPRequestHandler):
    """Serves one JWKS document and nothing else."""

    jwks_body: bytes = b"{}"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.jwks_body)))
        self.end_headers()
        self.wfile.write(self.jwks_body)

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log."""


@contextmanager
def serve_jwks(factory: TokenFactory) -> Iterator[str]:
    """Serve ``factory``'s JWKS over HTTP, yielding its URL.

    PyJWKClient only accepts http/https — it refuses ``file://`` to avoid being
    turned into a local-file reader. Binding a real socket also keeps the
    verifier's actual fetch-and-cache path under test instead of stubbing it.
    """
    handler = type(
        "BoundJwksHandler",
        (_JwksHandler,),
        {"jwks_body": factory.jwks_json().encode("utf-8")},
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}/.well-known/jwks.json"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
