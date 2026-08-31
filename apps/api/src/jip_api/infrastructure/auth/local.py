"""Token verification with no external issuer, for local runs and demos.

The JWKS path in :mod:`jip_api.infrastructure.auth.oidc` needs an OIDC provider,
which means anyone wanting to look at this system has to register with a third
party before the first screen renders. That is the whole barrier this module
removes: a symmetric secret this process already holds, and nothing to sign up
for.

**It is not an authentication scheme.** Anyone holding the secret can mint a
token for any subject, so the secret *is* the credential and there is exactly
one of it. That is acceptable for a machine running a demo and unacceptable
anywhere else, which is why :func:`build_verifier` refuses to construct this in
production rather than trusting configuration to be right.

What it deliberately keeps from the real path: signature checking, `exp`
enforcement, the pinned algorithm, and the same :class:`VerifiedIdentity`
output. A token that is expired or forged is rejected here exactly as it would
be against a JWKS — the key source is what changes, not the discipline.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import jwt

from jip_api.infrastructure.auth.oidc import (
    TokenVerificationError,
    VerifiedIdentity,
)

# Pinned for the same reason RS256 is pinned on the JWKS path: honouring the
# token's own `alg` is what enables `alg: none`.
ALGORITHM = "HS256"

MINIMUM_SECRET_LENGTH = 32
"""Short enough to type, long enough that guessing it is not the easy path."""

DEFAULT_SUBJECT = "local-demo-user"
"""Who a minted token is for when the caller does not say.

Stored as ``external_user_id`` under the ``local`` provider. The users table is
unique on ``(auth_provider, external_user_id)``, so this identity cannot collide
with one issued by a real provider even in a database that holds both.
"""


class LocalTokenVerifier:
    """:class:`~jip_api.infrastructure.auth.oidc.TokenVerifier` over a shared secret."""

    def __init__(self, secret: str, *, leeway_seconds: int = 5) -> None:
        if len(secret) < MINIMUM_SECRET_LENGTH:
            raise ValueError(
                f"JIP_AUTH_LOCAL_SECRET must be at least {MINIMUM_SECRET_LENGTH} "
                f"characters; got {len(secret)}."
            )
        self._secret = secret
        self._leeway = leeway_seconds

    def verify(self, token: str) -> VerifiedIdentity:
        """Verify ``token`` and return its identity claims."""
        if not token or token.count(".") != 2:
            raise TokenVerificationError("token is not a well-formed JWS")

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                leeway=self._leeway,
                options={
                    "require": ["exp", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    # No issuer and no audience: there is no third party to
                    # name, and asserting one we mint ourselves would check our
                    # own arithmetic rather than the token's provenance.
                    "verify_iss": False,
                    "verify_aud": False,
                },
            )
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError(f"token rejected: {exc}") from exc

        return VerifiedIdentity.from_claims(claims)


def mint_local_token(
    secret: str,
    *,
    subject: str = DEFAULT_SUBJECT,
    email: str | None = None,
    display_name: str | None = None,
    ttl_seconds: int = 86_400,
) -> str:
    """Mint a token the matching :class:`LocalTokenVerifier` will accept.

    Kept beside the verifier rather than in a script, so the two cannot drift
    apart in which claims they consider required.
    """
    if len(secret) < MINIMUM_SECRET_LENGTH:
        raise ValueError(
            f"secret must be at least {MINIMUM_SECRET_LENGTH} characters; got {len(secret)}."
        )

    now = dt.datetime.now(dt.UTC)
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl_seconds),
    }
    if email:
        claims["email"] = email
    if display_name:
        claims["name"] = display_name

    return jwt.encode(claims, secret, algorithm=ALGORITHM)
