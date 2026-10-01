# Path: tests/test_human_memory_schema_dwb584.py
# File: test_human_memory_schema_dwb584.py
# Created: 2026-09-29 (DWB-584)
# Purpose: Guard the human_memory substrate - that the schema the ORM declares
#          and the schema `alembic upgrade head` PRODUCES both match the spec,
#          and that neither has ever grown a stored score.
# Caller: pytest
# Callees: alembic CLI (subprocess), sqlalchemy.inspect, app.models
# Data In: Base.metadata; a scratch MySQL database replayed from base
# Data Out: Assertions on declared and migrated schema
# Last Modified: 2026-09-30 (DWB-605: journal_entries gains created_at)

"""Schema guards for DWB-584, the human_memory substrate.

Three classes, and the split between them is the point. Each proves a claim the
others do not, and collapsing any two loses one of the claims.

`TestDeclaredSchema` reads `Base.metadata` only. It needs no database, runs on
every clone, and guards what the MODELS say.

`TestMigratedSchema` replays the migration history from BASE into an empty
scratch database and introspects the result. It guards what the MIGRATION says,
which is a different claim: inspecting the live development database proves the
database is right, never that the migration is, and Miles's requirement is that
someone cloning this repo on another machine gets the current schema from the
migration alone. So this class shells out to the real `alembic` CLI rather than
inspecting anything that already exists.

`TestUpgradeAgainstLiveStructure` copies the LIVE schema's structure into the
scratch database, walks it back to the prior revision with `alembic downgrade`,
puts rows in, and upgrades. This is the case every existing installation is
actually in, and it is the only one of the three where "add a NOT NULL column"
can fail on existing rows. An empty database cannot fail that way, so the
from-base replay alone would pass while the migration was broken for everybody
who already has data.

A note on the scratch database, because it is a SINGLETON: there is one grant
for one name, so every run shares it and each fixture drops and recreates it.
Concurrent pytest sessions cannot collide on it because conftest already
serializes whole sessions on an fcntl lock for lat_test. Ad-hoc `alembic`
commands run by hand WHILE a suite is running can collide, and will look like a
flaky failure in whichever one loses.

It is SKIPPED, loudly, when the scratch database is not reachable. The grant in
this environment is scoped to one database name, so the name is configurable
through LAT_MIGRATION_TEST_DB and a clone without that grant skips instead of
failing. Everything cheap enough to run unconditionally lives in the first
class, deliberately - including the no-score-column guard, which is asserted in
BOTH classes because a stored score could be reintroduced through either the
model or the migration and the two failures look nothing alike.
"""

import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.database import Base
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.agent_memory import MemoryCaughtBy, MemoryCost
from app.models.journal_entry import JournalEntry
from app.models.project import MemoryMode, Project
from app.models.hook_session import HookSession

PRIOR_REVISION = "dwb581a1b2c3"
THIS_REVISION = "dwb584a1b2c3"

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent

# Grant-scoped in this environment: lat_user holds ALL PRIVILEGES on exactly
# this database name and only USAGE on *.*, so it can drop and recreate this
# one and nothing else. Overridable for a clone that provisions a different
# name.
SCRATCH_DB = os.environ.get("LAT_MIGRATION_TEST_DB", "dwb584_scratch")

# The column sets the spec fixes. Written out in full rather than derived, so
# that ADDING a column is also a test failure and has to be argued for. `score`
# and `band` are absent from the first set on purpose; see the guards below.
AGENT_MEMORIES_COLUMNS = {
    "id",
    "agent_id",
    "tier",
    "body",
    "context_key",
    "cost",
    "caught_by",
    "surprised",
    "created_session_id",
    "last_reinforced_session_id",
    "fired_count",
    "source_journal_id",
    "created_at",
    "updated_at",
}

JOURNAL_ENTRIES_COLUMNS = {
    "id",
    "agent_id",
    "dwb_session_id",
    "entered_at",
    # DWB-605: the memory's ORIGINAL date, distinct from entered_at's
    # journal-arrival date. See alembic/versions/dwb605a1b2c3_journal_created_at.py.
    "created_at",
    "tags",
    "retrieval_count",
    "body",
}

PROJECT_COLUMNS_ADDED = {
    "memory_mode",
    "memory_schema_version",
    "topoff_enabled",
    "topoff_interval",
}

# Any of these appearing on agent_memories means the derived score has been
# turned back into a stored one. `score` and `band` are the two shapes the
# ticket names; the reinforcement ones are here because storing a session COUNT
# or a reinforcement TIMESTAMP reintroduces the same defect one step back - a
# second authoritative copy of something section 3 derives.
FORBIDDEN_MEMORY_COLUMNS = {
    "score",
    "band",
    "sessions_since_reinforced",
    "last_reinforced",
    "last_reinforced_at",
}


def _server_url() -> str:
    return (
        f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/"
    )


def _alembic(db_name: str, *args: str) -> subprocess.CompletedProcess:
    """Run the real alembic CLI against `db_name`.

    A subprocess rather than alembic.command in-process, for a reason that is
    not style: alembic/env.py calls `config.set_main_option("sqlalchemy.url",
    settings.database_url)` unconditionally, and `settings` is a module-level
    singleton that conftest has already bound to lat_test. Setting the URL on a
    Config object in this process would be silently overwritten. Handing the
    child a different MYSQL_DATABASE is the only way the override survives, and
    it has the side benefit of exercising the command a person actually types.
    """
    env = dict(os.environ)
    env["MYSQL_DATABASE"] = db_name
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _reset_scratch() -> None:
    """Drop and recreate the scratch database, or skip with the reason."""
    server = create_engine(_server_url(), pool_pre_ping=True)
    try:
        with server.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{SCRATCH_DB}`"))
            conn.execute(text(f"CREATE DATABASE `{SCRATCH_DB}`"))
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - the reason belongs in the skip
        pytest.skip(
            f"scratch database {SCRATCH_DB!r} unavailable ({exc.__class__.__name__}: "
            f"{exc}); set LAT_MIGRATION_TEST_DB to a database this user may "
            "drop and create"
        )
    finally:
        server.dispose()


def _clone_structure_into_scratch(source_db: str) -> str:
    """Copy `source_db`'s TABLE STRUCTURE (no rows) into the scratch database.

    Structure only, through SHOW CREATE TABLE, rather than mysqldump: this needs
    nothing on PATH and nothing outside the database connection the tests
    already have. Foreign key checks are off for the duration so the tables can
    go in in any order.

    Returns the alembic revision the source is stamped at.
    """
    src = create_engine(f"{_server_url()}{source_db}", pool_pre_ping=True)
    dst = create_engine(f"{_server_url()}{SCRATCH_DB}", pool_pre_ping=True)
    try:
        with src.connect() as sconn:
            names = [
                r[0] for r in sconn.execute(text("SHOW TABLES")) if r[0] != "alembic_version"
            ]
            ddl = [
                sconn.execute(text(f"SHOW CREATE TABLE `{n}`")).one()[1] for n in names
            ]
            revision = sconn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        with dst.connect() as dconn:
            dconn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for statement in ddl:
                dconn.execute(text(statement))
            dconn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            dconn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            dconn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": revision},
            )
            dconn.commit()
    finally:
        src.dispose()
        dst.dispose()
    return revision


def _insert_minimal(conn, db_name: str, table: str, values: dict) -> None:
    """INSERT into `table`, filling every NOT NULL column that has no database
    default with a type-appropriate placeholder.

    Discovered from information_schema rather than hardcoded, and that is not
    tidiness. A schema built by `Base.metadata.create_all` and a schema built by
    the migration chain DISAGREE about which columns carry a server default:
    several of `projects.force_*` are NOT NULL with no default on the live
    database and NOT NULL WITH one on a migration-built database. A hardcoded
    column list would therefore be correct against one target and wrong against
    the other, which is exactly the difference these tests exist to span.

    Placeholders are deliberately boring. Nothing here asserts on them; they
    exist only so a row can exist for the migration to act on.
    """
    required = conn.execute(
        text(
            "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :t AND IS_NULLABLE = 'NO' "
            "AND COLUMN_DEFAULT IS NULL AND EXTRA NOT LIKE '%auto_increment%' "
            "AND EXTRA NOT LIKE '%GENERATED%'"
        ),
        {"db": db_name, "t": table},
    ).all()

    row = dict(values)
    for name, data_type, column_type in required:
        if name in row:
            continue
        if data_type == "enum":
            # column_type looks like enum('a','b'); take the first member.
            row[name] = column_type[len("enum('") : -2].split("','")[0]
        elif data_type in ("datetime", "timestamp", "date"):
            row[name] = "1970-01-01 00:00:00"
        elif data_type in ("varchar", "char", "text", "longtext", "mediumtext", "json"):
            row[name] = f"dwb584-{name}"
        else:
            row[name] = 0

    cols = ", ".join(f"`{c}`" for c in row)
    binds = ", ".join(f":{c}" for c in row)
    conn.execute(text(f"INSERT INTO `{table}` ({cols}) VALUES ({binds})"), row)


class TestDeclaredSchema:
    """What the ORM models say. No database, runs on every clone."""

    def test_agent_memories_has_no_stored_score(self):
        """Spec section 3: the score is derived at read time and NEVER stored.

        A stored score has to be rewritten on every row every session and
        drifts out of sync with the rule it is supposed to express, where a
        derived score cannot disagree with itself.
        """
        present = FORBIDDEN_MEMORY_COLUMNS & set(AgentMemory.__table__.columns.keys())
        assert present == set(), (
            f"agent_memories has grown {sorted(present)}. The score is DERIVED "
            "from (tier, sessions_since_reinforced) at read time and must never "
            "be persisted - see docs/human_memory_spec.md section 3."
        )

    def test_agent_memories_column_set_is_exactly_the_spec(self):
        assert set(AgentMemory.__table__.columns.keys()) == AGENT_MEMORIES_COLUMNS

    def test_journal_entries_column_set_is_exactly_the_spec(self):
        assert set(JournalEntry.__table__.columns.keys()) == JOURNAL_ENTRIES_COLUMNS

    def test_tier_carries_raw_and_not_journal(self):
        """`raw` is the untiered state DWB-586 appends in (spec section 4).

        It is an enum VALUE rather than a nullable tier, so the scoring query
        has to name it to exclude it. `journal` is NOT a tier: the journal is
        its own table, scored by retrieval rather than by tier.
        """
        values = [t.value for t in MemoryTier]
        # DWB-611: scar_context_bound collapsed into scar - four values, not
        # five. Miles's ruling was four buckets, all scars context-bound.
        assert values == ["raw", "core", "scar", "working"]
        assert "journal" not in values

    def test_tier_is_not_nullable(self):
        """The corollary of `raw` being a value: every row has an answer.

        A nullable tier would let a join or an IS NOT NULL drop untiered rows
        silently, where naming `raw` forces DWB-585 to be explicit about them.
        """
        assert AgentMemory.__table__.c.tier.nullable is False

    def test_reinforcement_is_a_session_reference_not_a_timestamp(self):
        """Spec section 3: THE CLOCK IS SESSIONS, NOT DAYS.

        Section 6 was amended on 2026-09-29 to replace a `last_reinforced`
        timestamp with this reference for exactly this reason. A timestamp here
        would quietly reintroduce the calendar the ruling removed.
        """
        col = AgentMemory.__table__.c.last_reinforced_session_id
        targets = {fk.column.table.name for fk in col.foreign_keys}
        assert targets == {"dwb_sessions"}

    def test_created_session_id_is_a_session_reference(self):
        col = AgentMemory.__table__.c.created_session_id
        assert {fk.column.table.name for fk in col.foreign_keys} == {"dwb_sessions"}

    def test_session_references_are_nullable(self):
        """A memory can be created or reinforced outside any open DWB session.

        DWB-585's session count has to define its behaviour for NULL rather
        than assume a row exists.
        """
        assert AgentMemory.__table__.c.created_session_id.nullable is True
        assert AgentMemory.__table__.c.last_reinforced_session_id.nullable is True

    def test_journal_does_not_point_back_at_memories(self):
        """One direction only (spec section 7 hard rule 4).

        agent_memories.source_journal_id points at the story; journal_entries
        carries no pointer the other way, so evicting a memory cannot strand
        the entry it came from.
        """
        referred = {
            fk.column.table.name for fk in JournalEntry.__table__.foreign_keys
        }
        assert "agent_memories" not in referred
        assert {
            fk.column.table.name
            for fk in AgentMemory.__table__.c.source_journal_id.foreign_keys
        } == {"journal_entries"}

    def test_memory_mode_defaults_to_stock(self):
        """Acceptance 2: an existing DB upgrades with zero behaviour change."""
        # DWB-593 appended `adopting` and `reverting`. This list is exhaustive
        # on purpose and went red when the vocabulary grew, which is the job.
        # Order matters beyond tidiness: MySQL stores an ENUM as the ordinal of
        # its value, so a new member inserted in the middle would renumber
        # `human_memory` on every existing row.
        assert [m.value for m in MemoryMode] == [
            "stock",
            "human_memory",
            "adopting",
            "reverting",
        ]
        assert Project.__table__.c.memory_mode.server_default.arg == "stock"
        assert Project.__table__.c.memory_mode.nullable is False

    def test_memory_schema_version_defaults_to_one(self):
        assert Project.__table__.c.memory_schema_version.server_default.arg == "1"

    def test_topoff_columns_exist_and_are_off_by_default(self):
        """Top-off is INDEPENDENT of memory mode (Miles's ruling, spec § 8).

        These columns share the projects table with memory_mode for delivery
        reasons only. Asserting the default is off is the part that matters
        here: nothing about top-off may turn on because a project switched
        memory modes.
        """
        assert Project.__table__.c.topoff_enabled.server_default.arg == "0"
        assert Project.__table__.c.topoff_interval.server_default.arg == "10"

    def test_prompt_count_on_hook_sessions(self):
        """Stored, not derived, and that was checked: nothing in the schema
        records a prompt, so there is no trace to count from."""
        col = HookSession.__table__.c.prompt_count
        assert col.nullable is False
        assert col.server_default.arg == "0"

    def test_memory_tag_enums(self):
        assert [c.value for c in MemoryCost] == ["none", "low", "high"]
        assert [c.value for c in MemoryCaughtBy] == ["me", "worker", "human", "ci"]

    def test_surprised_is_tri_state(self):
        """True, False, and "nobody said". NULL is not False.

        Section 1 makes prediction error the driver of encoding strength, so
        "was not surprised" and "was never asked" are different facts.
        """
        assert AgentMemory.__table__.c.surprised.nullable is True

    def test_tags_are_on_the_memory_not_the_journal(self):
        """Spec section 6, second amendment: cost, caught_by and surprised
        moved onto agent_memories and came OFF journal_entries.

        The negative half is the half worth testing. Section 7 opens by naming
        two stores that both look authoritative and disagree as the failure
        mode, so these three existing in BOTH places is the specific defect the
        ruling exists to prevent, and it is the state the schema was in before
        the amendment.
        """
        moved = {"cost", "caught_by", "surprised"}
        assert moved <= set(AgentMemory.__table__.columns.keys())
        assert moved & set(JournalEntry.__table__.columns.keys()) == set()

    def test_moved_tags_are_all_nullable(self):
        """Section 4: tag only what the moment knows. Untagged is normal."""
        for name in ("cost", "caught_by", "surprised"):
            assert AgentMemory.__table__.c[name].nullable is True

    def test_journal_keeps_its_own_retrieval_path(self):
        """Section 5: a journal read is tags plus date plus term. Those two
        columns are what makes that possible and must not move."""
        assert "tags" in JournalEntry.__table__.columns
        assert "entered_at" in JournalEntry.__table__.columns

    def test_both_tables_are_registered_on_the_metadata(self):
        """A table the ORM does not know about is not created on a fresh DB,
        because conftest builds the test schema from create_all."""
        assert "agent_memories" in Base.metadata.tables
        assert "journal_entries" in Base.metadata.tables


@pytest.fixture(scope="module")
def migrated_scratch_db():
    """Replay the whole history from BASE into an empty scratch database.

    This is the fresh-clone claim and nothing weaker. It does NOT look at the
    development database, which would only prove the development database is
    right.

    Skips rather than fails when the scratch database is unreachable, so a
    clone without the grant still gets the declared-schema guards above.
    """
    _reset_scratch()

    result = _alembic(SCRATCH_DB, "upgrade", "head")
    assert result.returncode == 0, (
        "`alembic upgrade head` failed from BASE. A fresh clone cannot build "
        f"this schema.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    engine = create_engine(
        f"{_server_url()}{SCRATCH_DB}", pool_pre_ping=True
    )
    yield engine
    engine.dispose()


class TestMigratedSchema:
    """What `alembic upgrade head` PRODUCES, replayed from base."""

    def test_upgrade_from_base_creates_both_tables(self, migrated_scratch_db):
        tables = set(inspect(migrated_scratch_db).get_table_names())
        assert {"agent_memories", "journal_entries"} <= tables

    def test_migrated_agent_memories_has_no_stored_score(self, migrated_scratch_db):
        """Acceptance 4, asserted against the MIGRATED table rather than the
        model. A score column added to the migration alone would pass the
        declared-schema guard and fail here."""
        cols = {
            c["name"] for c in inspect(migrated_scratch_db).get_columns("agent_memories")
        }
        assert FORBIDDEN_MEMORY_COLUMNS & cols == set()

    def test_migrated_column_sets_match_the_models(self, migrated_scratch_db):
        insp = inspect(migrated_scratch_db)
        assert {
            c["name"] for c in insp.get_columns("agent_memories")
        } == AGENT_MEMORIES_COLUMNS
        assert {
            c["name"] for c in insp.get_columns("journal_entries")
        } == JOURNAL_ENTRIES_COLUMNS

    def test_migrated_tier_enum_values(self, migrated_scratch_db):
        with migrated_scratch_db.connect() as conn:
            col_type = conn.execute(
                text(
                    "SELECT column_type FROM information_schema.columns "
                    "WHERE table_schema = :db AND table_name = 'agent_memories' "
                    "AND column_name = 'tier'"
                ),
                {"db": SCRATCH_DB},
            ).scalar_one()
        # DWB-611: scar_context_bound collapsed into scar via
        # dwb611a1b2c3_collapse_scar_context_bound.py.
        assert col_type == "enum('raw','core','scar','working')"

    def test_migrated_tags_are_on_the_memory_not_the_journal(self, migrated_scratch_db):
        """The amendment, asserted against the MIGRATED tables.

        A move applied to the model but not to the migration would pass the
        declared-schema guard and fail here, and the two failures look nothing
        alike.
        """
        insp = inspect(migrated_scratch_db)
        moved = {"cost", "caught_by", "surprised"}
        assert moved <= {c["name"] for c in insp.get_columns("agent_memories")}
        assert moved & {c["name"] for c in insp.get_columns("journal_entries")} == set()

    def test_migrated_tag_enum_values(self, migrated_scratch_db):
        with migrated_scratch_db.connect() as conn:
            types = dict(
                conn.execute(
                    text(
                        "SELECT column_name, column_type FROM information_schema.columns "
                        "WHERE table_schema = :db AND table_name = 'agent_memories' "
                        "AND column_name IN ('cost', 'caught_by')"
                    ),
                    {"db": SCRATCH_DB},
                ).all()
            )
        assert types["cost"] == "enum('none','low','high')"
        assert types["caught_by"] == "enum('me','worker','human','ci')"

    def test_migrated_foreign_keys(self, migrated_scratch_db):
        insp = inspect(migrated_scratch_db)
        memory_fks = {
            tuple(fk["constrained_columns"]): fk["referred_table"]
            for fk in insp.get_foreign_keys("agent_memories")
        }
        assert memory_fks == {
            ("agent_id",): "agents",
            ("created_session_id",): "dwb_sessions",
            ("last_reinforced_session_id",): "dwb_sessions",
            ("source_journal_id",): "journal_entries",
        }
        journal_fks = {
            tuple(fk["constrained_columns"]): fk["referred_table"]
            for fk in insp.get_foreign_keys("journal_entries")
        }
        assert journal_fks == {
            ("agent_id",): "agents",
            ("dwb_session_id",): "dwb_sessions",
        }

    def test_migrated_project_and_hook_columns(self, migrated_scratch_db):
        insp = inspect(migrated_scratch_db)
        assert PROJECT_COLUMNS_ADDED <= {
            c["name"] for c in insp.get_columns("projects")
        }
        assert "prompt_count" in {
            c["name"] for c in insp.get_columns("hook_sessions")
        }

    def test_migrated_memory_mode_defaults_to_stock(self, migrated_scratch_db):
        col = next(
            c
            for c in inspect(migrated_scratch_db).get_columns("projects")
            if c["name"] == "memory_mode"
        )
        assert col["nullable"] is False
        assert "stock" in str(col["default"])


class TestExistingDatabaseUpgrade:
    """Acceptance 2 and 3, which the fresh-clone replay does not cover.

    An empty database says nothing about what happens to ROWS that already
    exist, and every added column here is NOT NULL. This walks back one
    revision, puts real rows in, and walks forward again.
    """

    def test_round_trip_over_existing_rows(self, migrated_scratch_db):
        engine = migrated_scratch_db

        # --- down one revision ---------------------------------------
        result = _alembic(SCRATCH_DB, "downgrade", PRIOR_REVISION)
        assert result.returncode == 0, (
            f"downgrade failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        assert not (tables & {"agent_memories", "journal_entries"})
        assert not (
            PROJECT_COLUMNS_ADDED & {c["name"] for c in insp.get_columns("projects")}
        )
        assert "prompt_count" not in {
            c["name"] for c in insp.get_columns("hook_sessions")
        }

        # --- rows that predate the migration -------------------------
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO projects (prefix, name, status) "
                    "VALUES ('MIG', 'pre-existing project', 'active')"
                )
            )
            project_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            # total_tokens is NOT NULL with a PYTHON-side default only, so a raw
            # INSERT that skips it is rejected. Named explicitly rather than
            # relying on the ORM, because the ORM is exactly what this test is
            # trying not to go through.
            conn.execute(
                text(
                    "INSERT INTO hook_sessions (session_id, project_id, status, "
                    "session_type, total_tokens) VALUES ('dwb584-pre-existing', "
                    ":pid, 'active', 'teammate', 0)"
                ),
                {"pid": project_id},
            )
            conn.commit()

        # --- back up -------------------------------------------------
        result = _alembic(SCRATCH_DB, "upgrade", "head")
        assert result.returncode == 0, (
            f"re-upgrade failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        insp = inspect(engine)
        assert {"agent_memories", "journal_entries"} <= set(insp.get_table_names())

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT memory_mode, memory_schema_version, topoff_enabled, "
                    "topoff_interval FROM projects WHERE id = :pid"
                ),
                {"pid": project_id},
            ).one()
            # The whole point of acceptance 2: the row that was already there
            # comes out in stock mode, which is zero behaviour change.
            assert row.memory_mode == "stock"
            assert row.memory_schema_version == 1
            assert row.topoff_enabled == 0
            assert row.topoff_interval == 10

            prompt_count = conn.execute(
                text(
                    "SELECT prompt_count FROM hook_sessions "
                    "WHERE session_id = 'dwb584-pre-existing'"
                )
            ).scalar_one()
            assert prompt_count == 0


@pytest.fixture(scope="module")
def live_structure_at_prior_revision():
    """A scratch copy of the LIVE schema, walked back to the prior revision.

    This is the target the TL identified as the one that matters, and it tests a
    different claim from the from-base replay above. From base proves a fresh
    clone can build the schema from the migration alone. THIS proves the upgrade
    works against a real, already-populated schema at the real previous
    revision - which is the situation every existing installation is actually
    in, and the only one where "add a NOT NULL column" can fail on rows.

    The walk-back is done by `alembic downgrade` rather than by hand-removing
    columns, so the downgrade is exercised against real structure too.
    """
    live_db = os.environ.get("LAT_LIVE_DB", "local_agent_tracker")

    _reset_scratch()
    try:
        revision = _clone_structure_into_scratch(live_db)
    except Exception as exc:  # noqa: BLE001 - the reason belongs in the skip
        pytest.skip(
            f"could not clone structure from {live_db!r} "
            f"({exc.__class__.__name__}: {exc}); set LAT_LIVE_DB to a readable "
            "database at or above " + PRIOR_REVISION
        )

    if revision != PRIOR_REVISION:
        result = _alembic(SCRATCH_DB, "downgrade", PRIOR_REVISION)
        assert result.returncode == 0, (
            f"downgrade to {PRIOR_REVISION} failed against a copy of the live "
            f"structure.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    engine = create_engine(f"{_server_url()}{SCRATCH_DB}", pool_pre_ping=True)
    yield engine
    engine.dispose()


class TestUpgradeAgainstLiveStructure:
    """Acceptance 2 and 3 against a REAL schema, not an empty database."""

    def test_upgrade_over_live_structure_with_existing_rows(
        self, live_structure_at_prior_revision
    ):
        engine = live_structure_at_prior_revision

        # The copy really is at the prior revision: nothing from this ticket.
        insp = inspect(engine)
        assert not (set(insp.get_table_names()) & {"agent_memories", "journal_entries"})
        assert not (
            PROJECT_COLUMNS_ADDED & {c["name"] for c in insp.get_columns("projects")}
        )
        assert "prompt_count" not in {
            c["name"] for c in insp.get_columns("hook_sessions")
        }

        # Rows that predate the migration. Every column this ticket adds is NOT
        # NULL, so these are what a server_default has to cover.
        with engine.connect() as conn:
            _insert_minimal(
                conn,
                SCRATCH_DB,
                "projects",
                {"prefix": "LIVE", "name": "structure clone", "status": "active"},
            )
            project_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
            _insert_minimal(
                conn,
                SCRATCH_DB,
                "hook_sessions",
                {
                    "session_id": "dwb584-live-clone",
                    "project_id": project_id,
                    "status": "active",
                    "session_type": "teammate",
                    "total_tokens": 0,
                },
            )
            conn.commit()

        result = _alembic(SCRATCH_DB, "upgrade", "head")
        assert result.returncode == 0, (
            "upgrade failed against a copy of the LIVE structure. This is the "
            "case that matters: every existing installation is in it.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        insp = inspect(engine)
        assert {"agent_memories", "journal_entries"} <= set(insp.get_table_names())
        assert FORBIDDEN_MEMORY_COLUMNS & {
            c["name"] for c in insp.get_columns("agent_memories")
        } == set()
        assert {
            c["name"] for c in insp.get_columns("agent_memories")
        } == AGENT_MEMORIES_COLUMNS

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT memory_mode, memory_schema_version, topoff_enabled, "
                    "topoff_interval FROM projects WHERE id = :pid"
                ),
                {"pid": project_id},
            ).one()
            assert row.memory_mode == "stock"
            assert row.memory_schema_version == 1
            assert row.topoff_enabled == 0
            assert row.topoff_interval == 10
            assert conn.execute(
                text(
                    "SELECT prompt_count FROM hook_sessions "
                    "WHERE session_id = 'dwb584-live-clone'"
                )
            ).scalar_one() == 0
