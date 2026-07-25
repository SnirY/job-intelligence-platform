"""Alembic migrations must run against a genuinely clean database."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_head_from_clean_database(
    clean_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # migrations/env.py reads the URL from settings, so point settings at the
    # throwaway database this test created.
    monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)

    config = _alembic_config(clean_database_url)
    command.upgrade(config, "head")

    expected_head = ScriptDirectory.from_config(config).get_current_head()

    engine = sqlalchemy.create_engine(clean_database_url)
    try:
        with engine.connect() as connection:
            applied = connection.execute(
                sqlalchemy.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    assert applied == expected_head


def test_downgrade_to_base_is_reversible(
    clean_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration chain that cannot be unwound is a migration chain that cannot
    be rolled back in production."""
    monkeypatch.setenv("JIP_DATABASE_URL", clean_database_url)

    config = _alembic_config(clean_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = sqlalchemy.create_engine(clean_database_url)
    try:
        with engine.connect() as connection:
            remaining = connection.execute(
                sqlalchemy.text("SELECT count(*) FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    assert remaining == 0


def test_migration_chain_has_a_single_head(clean_database_url: str) -> None:
    """Two heads mean an unmerged branch, and `upgrade head` becomes ambiguous."""
    script = ScriptDirectory.from_config(_alembic_config(clean_database_url))

    assert len(script.get_heads()) == 1
