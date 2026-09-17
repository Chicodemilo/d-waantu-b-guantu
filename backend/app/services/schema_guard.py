# Path: app/services/schema_guard.py
# File: schema_guard.py
# Created: 2026-09-17
# Purpose: Refuse to boot on a database behind the alembic head, instead of half-building the schema with create_all (DWB-040)
# Caller: app/main.lifespan
# Callees: app/database (Base), alembic.config, alembic.script
# Data In: engine: Engine
# Data Out: None; raises SchemaOutOfDate, or creates tables on a virgin database
# Last Modified: 2026-09-17 (DWB-040: initial)

# Base.metadata.create_all creates whole missing TABLES from the models but can
# never add a column to a table that already exists. Run against a database
# behind the migrations it therefore produces a HALF-schema: the tables a pull
# introduced appear, the columns it added to existing tables do not, and the
# alembic pointer never moves. A health route that touches none of the new
# columns still answers 200, so the only symptom is a 500 on whichever route
# reads one. It also blocks its own repair - `alembic upgrade head` then dies
# on "table already exists" for the table create_all made, so the migration
# never reaches the add_column below it.
#
# Hence: migrations own the schema wherever migration history exists, and
# create_all survives only for a database that has none. The suite always
# lands on that fallback - conftest builds lat_test with its own create_all and
# never runs alembic.

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import Base

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class SchemaOutOfDate(RuntimeError):
    pass


def _head_revision() -> str | None:
    # None when the alembic config cannot be read; an unknown head is not
    # evidence the database is behind, so the caller boots rather than
    # failing on the guard's own inability to check.
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        return ScriptDirectory.from_config(
            Config(str(_ALEMBIC_INI))
        ).get_current_head()
    except Exception:
        logger.warning("schema_guard: could not read the alembic head", exc_info=True)
        return None


def _applied_revision(engine: Engine) -> str | None:
    # None means the database has never been migrated.
    if "alembic_version" not in set(inspect(engine).get_table_names()):
        return None
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()


def verify_schema(engine: Engine) -> None:
    applied = _applied_revision(engine)

    if applied is None:
        logger.warning(
            "schema_guard: no alembic_version table, treating this as a virgin "
            "database and creating tables from the models. Run "
            "'alembic upgrade head' to put it under migration control."
        )
        Base.metadata.create_all(bind=engine)
        return

    head = _head_revision()
    if head is None or applied == head:
        return

    raise SchemaOutOfDate(
        f"Database is at alembic revision {applied} but the code is at {head}. "
        "Refusing to start: creating tables from the models would add the new "
        "tables without the new columns, leave the pointer where it is, and "
        "then break 'alembic upgrade head' on a table that already exists. "
        "Run 'cd backend && .venv/bin/alembic upgrade head' first."
    )
