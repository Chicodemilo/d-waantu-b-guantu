# Path:          tests/conftest.py
# File:          conftest.py
# Created:       2026-03-28
# Purpose:       Shared pytest fixtures — DB session, test client, factory helpers
# Caller:        pytest (auto-loaded by all test modules)
# Callees:       app.main (FastAPI TestClient), app.database (engine, session)
# Data In:       MySQL lat_test database connection
# Data Out:      Rolled-back test transactions; factory-created API objects
# Last Modified: 2026-10-08 (DWB-653: commit census installed suite-wide; the
#                opt-in `persisting` fixture adds real-commit + second-connection
#                readback for tests that assert PERSISTENCE rather than behaviour)

"""Shared fixtures for backend API tests.

Uses a separate 'lat_test' MySQL database. Tables are created fresh per session
and dropped after. Each test function gets a rolled-back transaction so tests
stay isolated without needing to reseed.

DWB-314: A session-scoped fcntl.flock serializes concurrent pytest invocations
against the shared `lat_test` schema. Without it, two pytest processes hitting
the same MySQL DB race on DDL (`create_all`/`drop_all`, producing mass setup
errors) and on DML (InnoDB lock-wait / deadlock on contended rows like
`projects.tl_overhead_tokens`). The lock is held for the full session — the
second runner waits for the first to finish.
"""

import fcntl
import os
import pathlib

# Must set BEFORE any app module is imported so Settings picks it up
os.environ["MYSQL_DATABASE"] = "lat_test"
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient  # noqa: F401 - re-exported for tests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.schemas.ticket import ticket_number_from_key

# DWB-657/667: the fields every memory write must now carry. ONE DEFINITION,
# imported by the memory test modules, because the write contract changed twice
# in one day (DWB-649 derived the tier, DWB-657 made these mandatory) and the
# second change cost 35 individually-edited inline payloads. The next change
# costs one line here - and DWB-667 was the next change, and it cost one line.
#
# Spread as `**MEMORY_WRITE_EXTRAS` FIRST in a payload literal, so an explicit
# key in the test still wins - a test that deliberately sends a blank
# `condensed` must not have it silently replaced by this.
#
# DWB-667 ADDED `situation`, AND IT IS NOT ARBITRARY FILLER. The gate matches
# `keywords` against it with `memory_consult`'s own predicate, so this sentence
# has to CONTAIN both 'fixture' and 'contract' or every memory test in the suite
# refuses with a 400. If you change the keywords above, change this line in the
# same edit; they are a matched pair and nothing else in the suite will tell you.
MEMORY_WRITE_EXTRAS = {
    "condensed": "state the rule, not the anecdote",
    "keywords": ["fixture", "contract"],
    "situation": "I am editing a shared test fixture that encodes the write contract",
}


# DWB-653: the persistence instruments. `persisting` is re-exported so tests can
# request it by name; the import is what makes pytest see the fixture.
from tests.persistence_instrument import (  # noqa: E402,F401
    CensusClient,
    install_commit_spy,
    persisting,
    write_census,
)

# Build the test DB URL from the same settings (which now has MYSQL_DATABASE=lat_test)
_TEST_DB_URL = (
    f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/lat_test"
)

engine = create_engine(_TEST_DB_URL, pool_pre_ping=True)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redirect app.database.SessionLocal at the test engine. Services that build a
# fresh session via SessionLocal() (e.g., failed_hook logger) would otherwise
# write to the prod DB during tests.
import app.database as _app_database  # noqa: E402
_app_database.SessionLocal = TestingSession

# DWB-314: cross-process lock path. Lives in pytest's cache dir so it's a
# stable per-checkout location and doesn't collide with parallel checkouts.
_LAT_TEST_LOCK_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / ".pytest_cache" / "lat_test.lock"
)



def _truncate_all_tables() -> None:
    """Empty every table in lat_test. Used at session START (see create_tables).

    FOREIGN_KEY_CHECKS is disabled around the loop: there is no ordering of
    these tables that satisfies every FK, and TRUNCATE will not drop a row a
    foreign key still points at. Scoped to this connection and restored before
    it is returned to the pool.

    Shares its body with persistence_instrument._truncate_all rather than
    importing it, because conftest must not depend on a module it also exports
    fixtures from at import time.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for name in names:
            conn.execute(text(f"TRUNCATE TABLE `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session, drop after.

    DWB-314: Acquires an exclusive fcntl lock on `.pytest_cache/lat_test.lock`
    before any DDL runs and holds it for the entire session. A second pytest
    process invoked while this one is running will block at `LOCK_EX` until
    we release on session teardown — zero schema/DML contention possible.

    The Unix fcntl.flock advisory lock auto-releases when the file descriptor
    closes (including on abnormal process exit), so we don't leak the lock
    if pytest is killed.
    """
    _LAT_TEST_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep the fd alive on the fixture for the session lifetime.
    lock_fh = open(_LAT_TEST_LOCK_PATH, "w")
    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    try:
        Base.metadata.create_all(bind=engine)
        # DWB-653: CLEAN ON THE WAY IN, NOT ONLY ON THE WAY OUT.
        #
        # CLEANUP ON ENTRY COVERS EVERY EXIT PATH; CLEANUP ON EXIT COVERS ONLY
        # THE GRACEFUL ONES. `drop_all` below and the `persisting` fixture's own
        # teardown truncate both run only if the process gets that far. A run
        # killed on the lock, crashed, or SIGKILLed inside a `persisting` test
        # runs neither - and because `persisting` gives up rollback isolation to
        # get a REAL commit, its rows are already on disk when that happens.
        # `create_all` is a no-op against tables that already exist, so without
        # this line the next run would start against another run's committed
        # rows and fail somewhere unrelated on data it never created.
        #
        # THREE WAYS STATE SURVIVES A SESSION, AND THIS LINE IS THE ONLY THING
        # THAT COVERS ALL THREE:
        #   1. the process is killed (SIGKILL, crash, a run killed on the lock);
        #   2. an exception propagates during the session - `drop_all` sits AFTER
        #      the yield and INSIDE the try, with only the flock release in the
        #      `finally`, so it is skipped on any such exit, which is far more
        #      common than a kill;
        #   3. the failed_hook logger, which predates all of this. Line 66 above
        #      redirects `app.database.SessionLocal` at `TestingSession`, which
        #      is bound to the ENGINE - so a service that builds its own session
        #      commits on its own connection and the per-test rollback never
        #      reaches it. Those rows have been surviving in lat_test all along.
        # (3) is why this belongs in `create_tables` rather than in the
        # `persisting` fixture: the leak is not that fixture's and a fix scoped
        # to it would leave the oldest path open.
        #
        # This is not belt-and-braces for `drop_all`; it is the guarantee, and
        # `drop_all` is the tidy-up. Measured at ~1.0s once per session against
        # a full schema (3 repetitions). That cost does NOT show up as a
        # reliable 1s in a full-run comparison - run-to-run noise on this suite
        # is several seconds, so the number comes from timing the call itself
        # rather than from differencing two 5-minute runs.
        _truncate_all_tables()
        yield
        Base.metadata.drop_all(bind=engine)
    finally:
        # Releasing the lock is automatic on close, but be explicit for
        # readers — the contract is "lock held until session teardown finishes".
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()


@pytest.fixture(autouse=True)
def db_session():
    """Give each test a fresh DB session with rollback isolation."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSession(bind=connection)

    def override_get_db():
        try:
            yield session
        finally:
            pass  # don't close — we manage lifecycle here

    app.dependency_overrides[get_db] = override_get_db
    yield session

    transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_session):
    """FastAPI test client wired to the test DB session.

    DWB-653: this is a `CensusClient`, a TestClient subclass that records
    whether any `Session.commit()` happened during each request. It is a drop-in
    - same class, same methods, no behaviour change - and it is what lets the
    whole suite be used as a driver for the commit census without touching one
    of the 3000 tests. See tests/persistence_instrument.py.

    NOTE WHAT THIS CLIENT STILL CANNOT DO: it shares `db_session` with the test,
    so its writes are never committed for real and are rolled back at teardown.
    A test that needs to assert PERSISTENCE must use the `persisting` fixture
    instead, which gives up rollback isolation to get a real commit.
    """
    return CensusClient(app)


# ---------------------------------------------------------------------------
# DWB-653: the persistence instruments.
#
# Additive. Nothing above this point changed behaviour, and the ~3000 tests that
# assert behaviour rather than persistence keep the rollback harness, which is
# correct for them.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def engine_():
    """The test engine, for fixtures that need a second, independent connection."""
    return engine


@pytest.fixture(scope="session")
def session_factory_():
    """Builds sessions on their OWN connection - the point being that such a
    session has its own transaction and can only see COMMITTED rows."""
    return TestingSession


@pytest.fixture(scope="session", autouse=True)
def _dwb653_commit_census():
    """Install the commit spy for the whole run and dump the census at the end.

    Session-scoped and autouse so the census covers every test without any test
    opting in. The spy wraps `Session.commit` and calls through to it, so it
    changes no behaviour; it only counts.
    """
    install_commit_spy()
    yield
    write_census()


# ---------------------------------------------------------------------------
# Reusable factory fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_project(client):
    """Factory that POST-creates a project and returns the response dict."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        data = {
            "prefix": f"TST{_counter[0]}",
            "name": f"Test Project {_counter[0]}",
            **overrides,
        }
        r = client.post("/api/projects", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_agent(client, make_project):
    """Factory that POST-creates an agent and returns the response dict.

    project_id is required (DWB-287). Auto-creates a project if not provided,
    mirroring the make_epic/make_sprint/make_ticket pattern.
    """
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        data = {
            "name": f"Test Agent {_counter[0]}",
            "role": "developer",
            "api_key": f"test-key-{_counter[0]}-{id(overrides)}",
            **overrides,
        }
        r = client.post("/api/agents", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_epic(client, make_project):
    """Factory that POST-creates an epic (auto-creates a project if needed)."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        data = {
            "name": f"Test Epic {_counter[0]}",
            **overrides,
        }
        r = client.post("/api/epics", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_sprint(client, make_project, make_epic):
    """Factory that POST-creates a sprint (auto-creates project + epic if needed).

    DWB-331: only one sprint per project can be `active` at a time. Tests that
    make multiple sprints in the same project would now collide on the new
    UNIQUE constraint; the factory transparently falls back to `planned` for
    every sprint after the first one in a given project so existing test
    bodies don't need rewriting. Callers that need a specific status pass it
    explicitly via `status=` override (no auto-fallback in that case).
    """
    _counter = [0]
    _projects_with_active: set[int] = set()

    def _make(**overrides):
        _counter[0] += 1
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        if "epic_id" not in overrides:
            epic = make_epic(project_id=overrides["project_id"])
            overrides["epic_id"] = epic["id"]

        explicit_status = "status" in overrides
        pid = overrides["project_id"]
        if not explicit_status and pid in _projects_with_active:
            default_status = "planned"
        else:
            default_status = "active"

        data = {
            "sprint_number": _counter[0],
            "status": default_status,
            **overrides,
        }
        r = client.post("/api/sprints", json=data)
        assert r.status_code == 201, r.text
        result = r.json()
        if result["status"] == "active":
            _projects_with_active.add(pid)
        return result

    return _make


@pytest.fixture
def make_ticket(client, make_project, make_sprint):
    """Factory that POST-creates a ticket (auto-creates project, epic, and active sprint if needed)."""
    _counter = [0]
    _project_sprints = {}

    def _make(**overrides):
        _counter[0] += 1
        # DWB-529: a test that supplies its own ticket_key (e.g. "PC1-101")
        # gets ticket_number derived from that key's trailing integer, unless
        # it also pins ticket_number explicitly. Keeps every factory ticket
        # consistent with the API rule (key and number are one fact).
        if "ticket_key" in overrides and "ticket_number" not in overrides:
            derived = ticket_number_from_key(overrides["ticket_key"])
            if derived is not None:
                overrides["ticket_number"] = derived
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        pid = overrides["project_id"]
        # Ensure project has an active sprint (needed for ticket auto-assignment)
        if pid not in _project_sprints and "sprint_id" not in overrides:
            sprint = make_sprint(project_id=pid)
            _project_sprints[pid] = sprint["id"]
        data = {
            "ticket_number": _counter[0],
            # DWB-529: the trailing integer of ticket_key MUST equal
            # ticket_number (POST /api/tickets 422s on disagreement), so the
            # uniqueness salt goes in the prefix, the counter at the end.
            "ticket_key": f"T{id(overrides)}-{_counter[0]}",
            "title": f"Test Ticket {_counter[0]}",
            **overrides,
        }
        r = client.post("/api/tickets", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_test_result(client, make_project):
    """Factory that POST-creates a test result."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        data = {
            "suite": f"test-suite-{_counter[0]}",
            "total_tests": 10,
            "passed": 8,
            "failed": 2,
            "skipped": 0,
            "duration_seconds": 1.5,
            "status": "failed",
            **overrides,
        }
        r = client.post("/api/test-results", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_instruction(client):
    """Factory that POST-creates an instruction."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        data = {
            "scope": "global",
            "title": f"Test Instruction {_counter[0]}",
            "body": f"Instruction body {_counter[0]}",
            **overrides,
        }
        r = client.post("/api/instructions", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_project_agent(client, make_project, make_agent):
    """Factory that POST-creates a project-agent assignment."""

    def _make(**overrides):
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        if "agent_id" not in overrides:
            agent = make_agent()
            overrides["agent_id"] = agent["id"]
        data = {**overrides}
        r = client.post("/api/project-agents", json=data)
        assert r.status_code == 201
        return r.json()

    return _make
