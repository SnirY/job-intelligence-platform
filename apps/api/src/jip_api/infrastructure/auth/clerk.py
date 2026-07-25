"""Clerk session-token verification.

Verification is offline: the token is checked against Clerk's public JWKS, which
this process caches. No Clerk credential is held and no request is made to Clerk
on the authentication path.

See ``docs/adr/0004-clerk-as-authentication-provider.md``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from jip_config import Settings, get_settings

logger = logging.getLogger(__name__)

# Pinned, never read from the token. Honouring the token's own `alg` is what
# enables `alg: none` and the RS256->HS256 confusion attack, where a token is
# signed with the *public* key used as an HMAC secret.
ALGORITHMS = ["RS256"]


class TokenVerificationError(Exception):
    """The presented token is not a valid credential.

    Carries a reason for the server log only. The reason must never reach the
    client: telling a caller which check failed helps them iterate towards one
    that passes.
    """


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Identity claims from a token that passed every check."""

    subject: str
    """The Clerk user id (`sub`). The external identity reference."""

    session_id: str | None
    email: str | None
    display_name: str | None

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> VerifiedIdentity:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise TokenVerificationError("token has no usable `sub` claim")

        return cls(
            subject=subject,
            session_id=_optional_str(claims.get("sid")),
            # Clerk's default session token carries neither of these. They
            # appear only when a custom session-token claim is configured, so
            # both stay optional rather than being treated as guaranteed.
            email=_optional_str(claims.get("email")),
            display_name=_optional_str(claims.get("name")),
        )


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class ClerkTokenVerifier:
    """Verifies Clerk session tokens against a cached JWKS."""

    def __init__(
        self,
        jwks_url: str,
        *,
        issuer: str | None,
        authorized_parties: list[str],
        cache_seconds: int = 3600,
        leeway_seconds: int = 5,
    ) -> None:
        self._issuer = issuer
        self._authorized_parties = authorized_parties
        self._leeway = leeway_seconds
        self._jwk_client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=cache_seconds,
            # An unknown `kid` triggers a JWKS refetch. Without a bound, a
            # stream of forged tokens carrying random `kid` values turns into a
            # request flood against Clerk — and a self-inflicted outage once
            # Clerk rate-limits us back.
            max_cached_keys=16,
        )

    def verify(self, token: str) -> VerifiedIdentity:
        """Verify ``token`` and return its identity claims.

        Raises :class:`TokenVerificationError` if any check fails.
        """
        if not token or token.count(".") != 2:
            raise TokenVerificationError("token is not a well-formed JWS")

        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        except PyJWKClientError as exc:
            raise TokenVerificationError(f"no signing key for token: {exc}") from exc
        except Exception as exc:  # network failure, malformed JWKS document
            logger.warning("JWKS lookup failed", exc_info=exc)
            raise TokenVerificationError(f"JWKS lookup failed: {exc}") from exc

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    "require": ["exp", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": self._issuer is not None,
                    # Clerk session tokens carry no `aud`; `azp` is the
                    # equivalent binding and is checked below.
                    "verify_aud": False,
                },
            )
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError(f"token rejected: {exc}") from exc

        self._check_authorized_party(claims)
        return VerifiedIdentity.from_claims(claims)

    def _check_authorized_party(self, claims: dict[str, Any]) -> None:
        """Reject tokens minted for a different origin.

        A token can be perfectly valid and still not be ours: `azp` binds it to
        the frontend that requested it.
        """
        if not self._authorized_parties:
            return

        azp = claims.get("azp")
        if azp is None:
            raise TokenVerificationError("token has no `azp` claim but authorized parties are set")
        if azp not in self._authorized_parties:
            raise TokenVerificationError(f"unauthorized party: {azp!r}")


def build_verifier(settings: Settings) -> ClerkTokenVerifier:
    """Construct a verifier from settings."""
    return ClerkTokenVerifier(
        settings.resolved_clerk_jwks_url,
        issuer=settings.clerk_issuer,
        authorized_parties=settings.clerk_authorized_parties,
        cache_seconds=settings.clerk_jwks_cache_seconds,
        leeway_seconds=settings.clerk_leeway_seconds,
    )


@lru_cache(maxsize=1)
def get_token_verifier() -> ClerkTokenVerifier:
    """Process-wide verifier, so the JWKS cache is shared across requests."""
    return build_verifier(get_settings())


def reset_verifier_cache() -> None:
    """Drop the cached verifier. Used by tests that reconfigure authentication."""
    get_token_verifier.cache_clear()


def utc_now_epoch() -> int:
    """Current time as a UNIX timestamp, for token construction in tests."""
    return int(time.time())
