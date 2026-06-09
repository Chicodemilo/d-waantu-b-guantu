# Path: tests/test_dwb_session_migration.py
# File: test_dwb_session_migration.py
# Created: 2026-06-09
# Purpose: Verify the DWB-335 migration applies cleanly (downgrade + re-upgrade against lat_test)
# Caller: pytest
# Callees: alembic.command, sqlalchemy.inspect
# Data In: lat_test (already at head via conftest create_all)
# Data Out: Assertions on schema after up/down round-trip
# Last Modified: 2026-06-09

"""Round-trips the DWB-335 migration against the test database to verify the
hand-written upgrade + downgrade both succeed and produce the expected
schema. We can't replay the full migration history from scratch because
older data-migrations (e.g. dwb287) assume existing rows, so the test
strategy is:

1. lat_test already has the full schema from `Base.metadata.create_all`
   (via conftest's session-scoped fixture).
2. Stamp alembic_version at head.
3. Downgrade one step (removes dwb_sessions + the hook_sessions FK).
4. Upgrade one step (re-applies my migration).
5. Inspect the resulting schema.

This proves both up and down work, and that the schema after up matches
what the model declares (covered by the rest of the conftest-driven tests).
"""

import contextlib
import io
import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings

PRIOR_REVISION = "dwb328e7a91b"
THIS_REVISION = "dwb335a7b3c91"


@pytest.fixture(scope="module")
def alembic_cfg():
    backend_dir = pathlib.Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def _engine():
    return create_engine(
        f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/lat_test"
    )


def test_migration_round_trip(alembic_cfg):
    """Downgrade removes dwb_sessions + the hook_sessions FK; upgrade rebuilds
    them exactly. This catches drift between model and migration."""
    engine = _engine()
    try:
        # Stamp at head so the down step has a known starting point. The
        # create_all session fixture left the schema at head but never wrote
        # alembic_version. Idempotent in case a prior run left it stamped.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            conn.execute(text("DELETE FROM alembic_version"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": THIS_REVISION},
            )

        # Downgrade one step.
        command.downgrade(alembic_cfg, PRIOR_REVISION)

        insp = inspect(engine)
        assert "dwb_sessions" not in insp.get_table_names(), (
            "downgrade should drop dwb_sessions"
        )
        hs_cols = {c["name"] for c in insp.get_columns("hook_sessions")}
        assert "dwb_session_id" not in hs_cols, (
            "downgrade should drop hook_sessions.dwb_session_id"
        )

        # Upgrade back.
        command.upgrade(alembic_cfg, THIS_REVISION)

        insp = inspect(engine)
        assert "dwb_sessions" in insp.get_table_names()
        cols = {c["name"]: c for c in insp.get_columns("dwb_sessions")}
        for required in (
            "id",
            "project_id",
            "opened_at",
            "closed_at",
            "open_phrase",
            "close_phrase",
            "open_method",
            "close_method",
            "close_reason",
            "total_tokens",
            "total_time_seconds",
            "is_open",
            "created_at",
            "updated_at",
        ):
            assert required in cols, f"missing column {required}"

        # is_open is a STORED generated column — verify via information_schema.
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT EXTRA FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = 'lat_test' AND "
                    "TABLE_NAME = 'dwb_sessions' AND COLUMN_NAME = 'is_open'"
                )
            ).fetchone()
            assert row is not None
            assert "STORED GENERATED" in row.EXTRA.upper()

        # Single-active unique index present + correct columns.
        indexes = insp.get_indexes("dwb_sessions")
        unique_idx = next(
            (
                ix
                for ix in indexes
                if ix["name"] == "uq_dwb_sessions_one_open_per_project"
            ),
            None,
        )
        assert unique_idx is not None
        assert unique_idx["unique"] is True
        assert unique_idx["column_names"] == ["project_id", "is_open"]

        # hook_sessions FK rebuilt.
        hs_cols = {c["name"] for c in insp.get_columns("hook_sessions")}
        assert "dwb_session_id" in hs_cols
        fks = insp.get_foreign_keys("hook_sessions")
        dwb_fk = next(
            (f for f in fks if f["referred_table"] == "dwb_sessions"), None
        )
        assert dwb_fk is not None
        assert dwb_fk["constrained_columns"] == ["dwb_session_id"]
    finally:
        # Leave alembic_version table behind but cleared so subsequent
        # test runs don't trip on a stale revision pointer.
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM alembic_version"))
        engine.dispose()


def test_migration_offline_sql_contains_expected_ddl(alembic_cfg, tmp_path):
    """Belt-and-braces: render the upgrade SQL offline for the single
    migration step and verify the key statements are present. This catches
    typos / dialect mistakes without requiring a live DB to apply against.

    Range syntax `prior:this` restricts the offline render to only my
    migration; rendering from base hits earlier data-migrations that use
    `bind.execute().fetchall()`, which isn't supported in offline mode.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command.upgrade(
            alembic_cfg, f"{PRIOR_REVISION}:{THIS_REVISION}", sql=True
        )
    sql = buffer.getvalue()
    assert "CREATE TABLE dwb_sessions" in sql
    # Generated column with STORED persistence
    assert "GENERATED ALWAYS AS" in sql.upper()
    assert "STORED" in sql.upper()
    # Unique single-active index
    assert "uq_dwb_sessions_one_open_per_project" in sql
    # hook_sessions FK
    assert "fk_hook_sessions_dwb_session_id" in sql
    assert "dwb_session_id" in sql
