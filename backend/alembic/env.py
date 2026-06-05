# Path: backend/alembic/env.py
# File: env.py
# Created: 2026-03-29
# Purpose: Alembic environment configuration for online and offline migrations
# Caller: alembic CLI (upgrade, downgrade, revision)
# Callees: app.config.settings, app.database.Base, app.models
# Data In: alembic.ini config, app settings (DB URL)
# Data Out: Migration execution against target database
# Last Modified: 2026-04-09

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add backend dir to sys.path so app imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    Project, Sprint, Epic, Agent, ProjectAgent,
    Ticket, Comment, Alert, Instruction, ActivityLog,
    TestResult, HookSession, AgentConsolidationAck,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "format"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
