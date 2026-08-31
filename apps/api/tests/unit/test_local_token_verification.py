"""The local verifier, and the environments that must refuse to build it.

The refusal tests are the point of this file. A verifier that accepts tokens
anyone holding the secret can mint is a demo convenience in one environment and
a total authentication bypass in the next, and the only thing separating those
two readings is a configuration string.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest

from jip_api.infrastructure.auth.local import (
    ALGORITHM,
    DEFAULT_SUBJECT,
    MINIMUM_SECRET_LENGTH,
    LocalTokenVerifier,
    mint_local_token,
)
from jip_api.infrastructure.auth.oidc import TokenVerificationError, build_verifier
from jip_config import Environment, Settings

SECRET = "x" * MINIMUM_SECRET_LENGTH
OTHER_SECRET = "y" * MINIMUM_SECRET_LENGTH


def _settings(**overrides: object) -> Settings:
    """Settings with the two required connection strings already filled in."""
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/jip",
        "redis_url": "redis://localhost:6379/0",
        "environment": Environment.LOCAL,
        "auth_provider": "local",
        "auth_local_secret": SECRET,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- round trip ---


def test_a_minted_token_verifies() -> None:
    identity = LocalTokenVerifier(SECRET).verify(mint_local_token(SECRET))

    assert identity.subject == DEFAULT_SUBJECT


def test_optional_claims_survive_the_round_trip() -> None:
    token = mint_local_token(SECRET, subject="s-1", email="a@b.test", display_name="A B")

    identity = LocalTokenVerifier(SECRET).verify(token)

    assert (identity.subject, identity.email, identity.display_name) == ("s-1", "a@b.test", "A B")


# --- what it still refuses ---


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    token = mint_local_token(OTHER_SECRET)

    with pytest.raises(TokenVerificationError):
        LocalTokenVerifier(SECRET).verify(token)


def test_an_expired_token_is_rejected() -> None:
    token = mint_local_token(SECRET, ttl_seconds=-3600)

    with pytest.raises(TokenVerificationError):
        LocalTokenVerifier(SECRET).verify(token)


def test_a_token_without_a_subject_is_rejected() -> None:
    token = jwt.encode(
        {"exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)}, SECRET, algorithm=ALGORITHM
    )

    with pytest.raises(TokenVerificationError):
        LocalTokenVerifier(SECRET).verify(token)


def test_the_algorithm_is_pinned_so_an_unsigned_token_cannot_pass() -> None:
    """`alg: none` is the classic bypass, and it must not survive the pin."""
    token = jwt.encode(
        {"sub": "attacker", "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)},
        key="",
        algorithm="none",
    )

    with pytest.raises(TokenVerificationError):
        LocalTokenVerifier(SECRET).verify(token)


def test_a_short_secret_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match=str(MINIMUM_SECRET_LENGTH)):
        LocalTokenVerifier("too-short")


# --- the guard that actually matters ---


@pytest.mark.parametrize("environment", [Environment.PRODUCTION, Environment.STAGING])
def test_local_auth_is_refused_outside_local_and_test(environment: Environment) -> None:
    with pytest.raises(ValueError, match="must never run in"):
        build_verifier(_settings(environment=environment))


@pytest.mark.parametrize("environment", [Environment.LOCAL, Environment.TEST])
def test_local_auth_builds_where_it_is_allowed(environment: Environment) -> None:
    assert isinstance(build_verifier(_settings(environment=environment)), LocalTokenVerifier)


def test_local_auth_without_a_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="JIP_AUTH_LOCAL_SECRET"):
        build_verifier(_settings(auth_local_secret=None))


def test_the_default_provider_still_builds_the_jwks_verifier() -> None:
    """The Clerk path must be untouched by the presence of the local one."""
    verifier = build_verifier(
        _settings(
            auth_provider="clerk",
            auth_local_secret=None,
            auth_issuer="https://example.clerk.accounts.dev",
        )
    )

    assert not isinstance(verifier, LocalTokenVerifier)


def test_authentication_is_configured_by_the_secret_in_local_mode() -> None:
    assert _settings().authentication_configured
    assert not _settings(auth_local_secret=None).authentication_configured
