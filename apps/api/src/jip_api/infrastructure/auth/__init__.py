"""Authentication adapters: OIDC token verification, and a local-only fallback."""

from jip_api.infrastructure.auth.local import LocalTokenVerifier, mint_local_token
from jip_api.infrastructure.auth.oidc import (
    JwksTokenVerifier,
    TokenVerificationError,
    TokenVerifier,
    VerifiedIdentity,
    build_verifier,
    get_token_verifier,
    reset_verifier_cache,
)

__all__ = [
    "JwksTokenVerifier",
    "LocalTokenVerifier",
    "TokenVerificationError",
    "TokenVerifier",
    "VerifiedIdentity",
    "build_verifier",
    "get_token_verifier",
    "mint_local_token",
    "reset_verifier_cache",
]
