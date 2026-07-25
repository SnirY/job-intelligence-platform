"""Shared FastAPI dependencies.

The authenticated user is resolved here and nowhere else. Every user-owned query
must scope on the ``User`` this module returns — a ``user_id`` arriving in a
path, query string, or body is data, never an authorization input
(``docs/10-api-contracts.md``).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from jip_api.application.users.provisioning import provision_user
from jip_api.core.errors import APIError
from jip_api.domain.users.models import User
from jip_api.infrastructure.auth.clerk import (
    ClerkTokenVerifier,
    TokenVerificationError,
    get_token_verifier,
)
from jip_api.infrastructure.db.session import get_session

logger = logging.getLogger(__name__)


class UnauthenticatedError(APIError):
    """No usable credential was presented."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"
    message = "Authentication is required."


class AuthenticationUnavailableError(APIError):
    """The service cannot verify credentials right now."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "Authentication is temporarily unavailable."


def _bearer_token(request: Request) -> str:
    """Extract the bearer token, or reject."""
    header = request.headers.get("Authorization")
    if not header:
        raise UnauthenticatedError()

    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthenticatedError()

    return token.strip()


def _resolve_verifier() -> ClerkTokenVerifier:
    """Build the verifier, or report the service as unable to authenticate.

    Deliberately *not* a FastAPI dependency. FastAPI resolves dependencies
    before the handler runs, so a misconfigured instance would fail while
    building the verifier — turning even a request that carries no credential
    at all into an opaque 500, instead of the 401 it plainly deserves.
    """
    try:
        return get_token_verifier()
    except ValueError as exc:
        # Configuration error, not a bad credential: the caller may well hold a
        # perfectly good token and we simply cannot check it.
        logger.error("Authentication is not configured", exc_info=exc)
        raise AuthenticationUnavailableError() from exc


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    """Resolve the authenticated user, provisioning on first sight.

    Every rejection returns the same opaque 401. The specific failure — expired,
    bad signature, wrong issuer, unknown party — is logged but never returned:
    distinguishing them lets a caller probe their way toward a token that
    passes.
    """
    token = _bearer_token(request)
    verifier = _resolve_verifier()

    try:
        identity = verifier.verify(token)
    except TokenVerificationError as exc:
        logger.info("Rejected token", extra={"reason": str(exc)})
        raise UnauthenticatedError() from exc

    try:
        user = provision_user(session, identity)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
"""Use as ``user: CurrentUser`` on any endpoint that requires authentication."""
