# Path: tests/test_ticket_source_dwb581.py
# File: test_ticket_source_dwb581.py
# Created: 2026-09-17
# Purpose: DWB-581 - hook_sessions.ticket_source records WHICH MECHANISM supplied
#          ticket_id, so a claimed session (a best guess) is distinguishable from
#          a resolved one (a fact). Includes a structural guard that every
#          ticket_id write carries a source, since there are six such writes.
# Caller: pytest
# Callees: app/models/hook_session, app/services/hook_tracking, app/schemas/hook_session
# Data In: pytest fixtures
# Data Out: assertions
# Last Modified: 2026-09-17

"""ticket_id said WHICH ticket. It never said how confident we were.

Three mechanisms write it and they are not equally trustworthy. A lookup that
found the ticket already assigned is a fact. A ticket that reached out and
claimed a session afterwards (DWB-576) is the best available guess, and it is
the only one that can be wrong. Before this column they were identical in the
row, so anyone investigating a strange per-ticket number had to re-derive the
whole distinction from the code.

There are SIX ticket_id writes across three paths. TestEveryWriteCarriesASource
is the guard against a seventh being added without one: the failure mode is
silent, since a missing source looks exactly like a legitimately unknown one.
"""

import ast
import inspect
import textwrap

import pytest

from app.models.hook_session import (
    TICKET_SOURCE_CLAIMED_BY_TICKET,
    TICKET_SOURCE_RESOLVED_AT_START,
    TICKET_SOURCE_RESOLVED_LATER,
    TICKET_SOURCES,
    HookSession,
    HookSessionStatus,
)
from app.services import hook_tracking as ht


class TestEveryWriteCarriesASource:
    """AC 1. Six sites, one rule, and nothing runtime would catch a miss."""

    def test_every_hooksession_constructor_with_a_ticket_passes_a_source(self):
        tree = ast.parse(inspect.getsource(ht))
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "HookSession":
                continue
            kwargs = {k.arg for k in node.keywords}
            if "ticket_id" in kwargs and "ticket_source" not in kwargs:
                missing.append(node.lineno)
        assert not missing, (
            f"HookSession constructed with ticket_id but no ticket_source at "
            f"lines {missing}; a row will carry a ticket nobody can grade"
        )

    def test_every_function_assigning_ticket_id_also_assigns_a_source(self):
        """Covers the three assignment sites the constructor check cannot see."""
        offenders = []
        for fname in ("handle_session_end", "_handle_subagent_stop",
                      "claim_unattributed_sessions"):
            func = getattr(ht, fname)
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            assigns = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for t in node.targets:
                    if isinstance(t, ast.Attribute):
                        assigns.add(t.attr)
            if "ticket_id" in assigns and "ticket_source" not in assigns:
                offenders.append(fname)
        assert not offenders, (
            f"{offenders} assign ticket_id without assigning ticket_source"
        )

    def test_the_vocabulary_is_closed_and_null_is_not_in_it(self):
        assert set(TICKET_SOURCES) == {
            TICKET_SOURCE_RESOLVED_AT_START,
            TICKET_SOURCE_RESOLVED_LATER,
            TICKET_SOURCE_CLAIMED_BY_TICKET,
        }
        assert None not in TICKET_SOURCES, (
            "NULL is the absence of a value, not one of them: it means we do "
            "not know how the row got its ticket"
        )


class TestClaimedIsDistinguishableFromResolved:
    """AC 2. The entire point of the column."""

    def test_a_claimed_session_is_marked_as_a_guess(
        self, client, db_session, make_project, make_agent, make_sprint
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sprint = make_sprint(project_id=project["id"], status="active",
                             start_date="2026-09-01")
        row = HookSession(
            session_id="aClaimed-581", agent_id=agent["id"],
            project_id=project["id"], total_tokens=0,
            status=HookSessionStatus.completed,
        )
        db_session.add(row)
        db_session.flush()
        assert row.ticket_source is None

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 931, "ticket_key": "SRC-931", "title": "claims later",
        }).json()
        client.patch(f"/api/tickets/{ticket['id']}",
                     json={"assigned_agent_id": agent["id"]},
                     headers={"X-Agent-ID": str(agent["id"])})

        db_session.refresh(row)
        assert row.ticket_id == ticket["id"]
        assert row.ticket_source == TICKET_SOURCE_CLAIMED_BY_TICKET

    def test_a_resolved_session_is_marked_as_a_fact(
        self, client, db_session, make_project, make_agent, make_sprint, tmp_path
    ):
        """The same end state, ticket_id set, reached by the trustworthy path."""
        repo = tmp_path / "repo581"
        repo.mkdir()
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sprint = make_sprint(project_id=project["id"], status="active",
                             start_date="2026-09-01")
        ticket = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 932, "ticket_key": "SRC-932", "title": "already assigned",
            "assigned_agent_id": agent["id"], "status": "in_progress",
        }).json()

        # The ticket exists and is assigned BEFORE the session is ever seen.
        ht.handle_session_end(db_session, {
            "session_id": "aResolved-581",
            "hook_event": "SessionEnd",
            "cwd": str(repo),
            "agent_name": agent["name"],
        })

        row = db_session.query(HookSession).filter_by(
            session_id="aResolved-581").one()
        assert row.ticket_id == ticket["id"]
        assert row.ticket_source == TICKET_SOURCE_RESOLVED_AT_START, (
            "a session whose ticket was already assigned must not be recorded "
            "as a guess"
        )

    def test_a_later_resolve_is_marked_as_such(
        self, client, db_session, make_project, make_agent, make_sprint, tmp_path
    ):
        repo = tmp_path / "repo581b"
        repo.mkdir()
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sprint = make_sprint(project_id=project["id"], status="active",
                             start_date="2026-09-01")
        row = HookSession(
            session_id="aLater-581", agent_id=agent["id"],
            project_id=project["id"], total_tokens=0,
            status=HookSessionStatus.completed,
        )
        db_session.add(row)
        db_session.flush()

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 933, "ticket_key": "SRC-933", "title": "later",
            "assigned_agent_id": agent["id"], "status": "in_progress",
        }).json()
        # Undo the ticket-side claim so only the session-side path can fill it.
        row.ticket_id = None
        row.ticket_source = None
        db_session.flush()

        ht.handle_session_end(db_session, {
            "session_id": "aLater-581",
            "hook_event": "SessionEnd",
            "cwd": str(repo),
        })

        db_session.refresh(row)
        assert row.ticket_id == ticket["id"]
        assert row.ticket_source == TICKET_SOURCE_RESOLVED_LATER


class TestUnknownStaysUnknown:
    """AC 3. NULL is a real answer and must not be manufactured."""

    def test_a_session_with_no_ticket_has_no_source(
        self, db_session, make_project, make_agent
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        row = HookSession(
            session_id="aNoTicket-581", agent_id=agent["id"],
            project_id=project["id"], total_tokens=0,
            status=HookSessionStatus.completed,
        )
        db_session.add(row)
        db_session.flush()

        assert row.ticket_id is None
        assert row.ticket_source is None

    def test_a_pre_existing_row_reads_null_rather_than_a_guess(
        self, db_session, make_project, make_agent, make_ticket
    ):
        """A row written before this column existed carries a ticket and no
        source. That is the honest reading and nothing may backfill it."""
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        ticket = make_ticket(project_id=project["id"])
        legacy = HookSession(
            session_id="aLegacy-581", agent_id=agent["id"],
            project_id=project["id"], ticket_id=ticket["id"], total_tokens=0,
            status=HookSessionStatus.completed,
        )
        db_session.add(legacy)
        db_session.flush()

        assert legacy.ticket_id == ticket["id"]
        assert legacy.ticket_source is None


class TestReadSchema:
    """AC 4. Visible without opening the database."""

    def test_hook_sessions_listing_exposes_ticket_source(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        ticket = make_ticket(project_id=project["id"])
        db_session.add(HookSession(
            session_id="aSchema-581", agent_id=agent["id"],
            project_id=project["id"], ticket_id=ticket["id"],
            ticket_source=TICKET_SOURCE_CLAIMED_BY_TICKET,
            total_tokens=0, status=HookSessionStatus.completed,
        ))
        db_session.flush()

        rows = client.get("/api/hooks/sessions").json()
        mine = [r for r in rows if r["session_id"] == "aSchema-581"]
        assert mine, "session missing from the listing"
        assert "ticket_source" in mine[0]
        assert mine[0]["ticket_source"] == TICKET_SOURCE_CLAIMED_BY_TICKET
