# Path:          tests/conftest.py
# File:          conftest.py
# Created:       2026-03-28
# Purpose:       Shared pytest fixtures — DB session, test client, factory helpers
# Caller:        pytest (auto-loaded by all test modules)
# Callees:       app.main (FastAPI TestClient), app.database (engine, session)
# Data In:       MySQL lat_test database connection
# Data Out:      Rolled-back test transactions; factory-created API objects
# Last Modified: 2026-03-29

"""Shared fixtures for backend API tests.

Uses a separate 'lat_test' MySQL database. Tables are created fresh per session
and dropped after. Each test function gets a rolled-back transaction so tests
stay isolated without needing to reseed.
"""

import os

# Must set BEFORE any app module is imported so Settings picks it up
os.environ["MYSQL_DATABASE"] = "lat_test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Build the test DB URL from the same settings (which now has MYSQL_DATABASE=lat_test)
_TEST_DB_URL = (
    f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/lat_test"
)

engine = create_engine(_TEST_DB_URL, pool_pre_ping=True)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


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
    """FastAPI test client wired to the test DB session."""
    return TestClient(app)


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
def make_agent(client):
    """Factory that POST-creates an agent and returns the response dict."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
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
    """Factory that POST-creates a sprint (auto-creates project + epic if needed)."""
    _counter = [0]

    def _make(**overrides):
        _counter[0] += 1
        if "project_id" not in overrides:
            project = make_project()
            overrides["project_id"] = project["id"]
        if "epic_id" not in overrides:
            epic = make_epic(project_id=overrides["project_id"])
            overrides["epic_id"] = epic["id"]
        data = {
            "sprint_number": _counter[0],
            "status": "active",
            **overrides,
        }
        r = client.post("/api/sprints", json=data)
        assert r.status_code == 201
        return r.json()

    return _make


@pytest.fixture
def make_ticket(client, make_project, make_sprint):
    """Factory that POST-creates a ticket (auto-creates project, epic, and active sprint if needed)."""
    _counter = [0]
    _project_sprints = {}

    def _make(**overrides):
        _counter[0] += 1
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
            "ticket_key": f"T-{_counter[0]}-{id(overrides)}",
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
