"""Clerk token verification.

These are the rejection rules that stand between the database and anyone with a
JWT library. Each case here is an attack that must not work.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import jwt
import pytest

from jip_api.infrastructure.auth.oidc import (
    JwksTokenVerifier,
    TokenVerificationError,
)
from tests.auth_fixtures import AUTHORIZED_PARTY, ISSUER, TokenFactory, serve_jwks


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory.create()


@pytest.fixture
def verifier(factory: TokenFactory) -> Iterator[JwksTokenVerifier]:
    with serve_jwks(factory) as jwks_url:
        yield JwksTokenVerifier(
            jwks_url,
            issuer=ISSUER,
            authorized_parties=[AUTHORIZED_PARTY],
            leeway_seconds=0,
        )


def test_valid_token_yields_its_identity(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    identity = verifier.verify(factory.token(subject="user_abc", email="a@example.com", name="Ada"))

    assert identity.subject == "user_abc"
    assert identity.email == "a@example.com"
    assert identity.display_name == "Ada"


def test_expired_token_is_rejected(verifier: JwksTokenVerifier, factory: TokenFactory) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(expires_in=dt.timedelta(seconds=-30)))


def test_not_yet_valid_token_is_rejected(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(not_before=dt.timedelta(minutes=5)))


def test_token_signed_by_a_different_key_is_rejected(verifier: JwksTokenVerifier) -> None:
    """An attacker with their own keypair must not be able to mint access."""
    attacker = TokenFactory.create(key_id="test-key-1")  # same kid, different key

    with pytest.raises(TokenVerificationError):
        verifier.verify(attacker.token())


def test_unknown_key_id_is_rejected(verifier: JwksTokenVerifier) -> None:
    other = TokenFactory.create(key_id="not-in-jwks")

    with pytest.raises(TokenVerificationError):
        verifier.verify(other.token(key_id="not-in-jwks"))


def test_unsigned_token_is_rejected(verifier: JwksTokenVerifier) -> None:
    """`alg: none` is the classic JWT bypass; the verifier pins RS256."""
    unsigned = jwt.encode(
        {"sub": "user_attacker", "iss": ISSUER, "azp": AUTHORIZED_PARTY, "exp": 9_999_999_999},
        key="",
        algorithm="none",
    )

    with pytest.raises(TokenVerificationError):
        verifier.verify(unsigned)


def test_token_from_a_different_issuer_is_rejected(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    """A correctly signed token from another Clerk instance is still not ours."""
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(issuer="https://someone-else.clerk.accounts.dev"))


def test_unauthorized_party_is_rejected(verifier: JwksTokenVerifier, factory: TokenFactory) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(azp="https://evil.example.com"))


def test_missing_azp_is_rejected_when_parties_are_configured(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(azp=None))


@pytest.mark.parametrize(
    "malformed",
    ["", "not-a-token", "a.b", "a.b.c.d", "Bearer something", "...."],
)
def test_malformed_tokens_are_rejected(verifier: JwksTokenVerifier, malformed: str) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(malformed)


def test_token_without_subject_is_rejected(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    with pytest.raises(TokenVerificationError):
        verifier.verify(factory.token(extra_claims={"sub": ""}))


def test_absent_optional_claims_become_none(
    verifier: JwksTokenVerifier, factory: TokenFactory
) -> None:
    """Clerk's default session token carries no email or name."""
    identity = verifier.verify(factory.token(subject="user_minimal"))

    assert identity.subject == "user_minimal"
    assert identity.email is None
    assert identity.display_name is None
