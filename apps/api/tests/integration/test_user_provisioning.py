"""Provisioning against a real database, at the application layer.

These cover the property the identity boundary exists for: the same person from
a different issuer is a different row, and a provider migration can therefore
run with both issuers live instead of needing a flag day.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from jip_api.application.users.provisioning import provision_user
from jip_api.infrastructure.auth.oidc import VerifiedIdentity

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


def identity(subject: str, *, email: str | None = None) -> VerifiedIdentity:
    return VerifiedIdentity(subject=subject, session_id="sess_test", email=email, display_name=None)


@pytest.fixture
def session(clean_database_url: str) -> Iterator[Session]:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", clean_database_url)
    command.upgrade(config, "head")

    engine = sqlalchemy.create_engine(clean_database_url)
    try:
        with Session(engine) as db_session:
            yield db_session
    finally:
        engine.dispose()


def test_first_call_creates_the_user(session: Session) -> None:
    user = provision_user(session, identity("sub_1"), provider="clerk")
    session.commit()

    assert user.id is not None
    assert user.auth_provider == "clerk"
    assert user.external_user_id == "sub_1"


def test_repeated_calls_return_the_same_user(session: Session) -> None:
    first = provision_user(session, identity("sub_1"), provider="clerk")
    session.commit()
    second = provision_user(session, identity("sub_1"), provider="clerk")
    session.commit()

    assert first.id == second.id


def test_same_subject_from_a_different_provider_is_a_different_user(session: Session) -> None:
    """The reason uniqueness is scoped by provider.

    Subject strings are only unique within an issuer. If uniqueness were on the
    subject alone, a second provider issuing a colliding `sub` would hand one
    person's account to someone else — and a migration could not run with both
    issuers live.
    """
    clerk_user = provision_user(session, identity("sub_1"), provider="clerk")
    session.commit()
    keycloak_user = provision_user(session, identity("sub_1"), provider="keycloak")
    session.commit()

    assert clerk_user.id != keycloak_user.id

    count = session.execute(sqlalchemy.text("SELECT count(*) FROM users")).scalar_one()
    assert count == 2


def test_profile_is_refreshed_but_never_cleared(session: Session) -> None:
    provision_user(session, identity("sub_1", email="old@example.com"), provider="clerk")
    session.commit()

    provision_user(session, identity("sub_1", email="new@example.com"), provider="clerk")
    session.commit()
    refreshed = provision_user(session, identity("sub_1"), provider="clerk")
    session.commit()

    assert refreshed.email == "new@example.com"


def test_internal_id_is_stable_across_sign_ins(session: Session) -> None:
    """Every user-owned foreign key will reference this id; it must not move."""
    original = provision_user(session, identity("sub_1"), provider="clerk").id
    session.commit()

    for _ in range(3):
        assert provision_user(session, identity("sub_1"), provider="clerk").id == original
        session.commit()
