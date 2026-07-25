"""Alembic environment.

The connection URL comes from the shared settings object rather than
``alembic.ini`` so there is exactly one place where the database is configured.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from jip_api.infrastructure.db import registry  # noqa: F401  (populates Base.metadata)
from jip_api.infrastructure.db.base import Base
from jip_config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A URL set explicitly on the config wins; settings are the default. Overriding
# unconditionally would silently ignore a caller that passed its own URL — which
# is exactly what a test targeting a throwaway database does, and the symptom is
# a migration run against the wrong database rather than an error.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
