# Path: tests/test_ticket_attribution_dwb576.py
# File: test_ticket_attribution_dwb576.py
# Created: 2026-09-16
# Purpose: DWB-576 - a worker's session lands on the right ticket even though
#          the ticket is assigned after the worker is spawned. Covers the
#          ticket-side claim, self-assignment on starting an unassigned ticket,
#          and re-resolution on a later hook event.
# Caller: pytest
# Callees: app/services/hook_tracking (claim_unattributed_sessions,
#          _resolve_ticket), app/services/ticket.update_ticket
# Data In: pytest fixtures
# Data Out: assertions
# Last Modified: 2026-09-16

"""Resolution asked the question before the answer existed.

A hook_session records which ticket its work belongs to by asking, at the
moment a hook event fires, "what ticket is assigned to this agent". On this
project workers are spawned and briefed BEFORE their tickets are assigned. On
2026-09-16 the session rows were created 15:07-15:15 and every ticket was
assigned at 15:32, so the honest answer at asking time was "none" and five of
six workers' entire sessions fell to the ad_hoc bucket.

The control that proves it is timing rather than code: Barry's ticket had been
assigned the previous evening, the same resolver ran, and his session
attributed correctly.

Note on a hypothesis these tests deliberately DO NOT encode: the original brief
suspected that resolution only matched in_progress, which would have meant the
in_review instruction in our own playbook destroyed attribution. It does not.
_resolve_ticket has always handled in_review (priority 3) and recently-done
(priority 4). TestStatusIsNotTheDiscriminator pins that so the theory is not
re-derived later.
"""

import pytest

from app.models.hook_session import HookSession, HookSessionStatus
from app.models.ticket import TicketStatus
from app.services import hook_tracking as ht


@pytest.fixture
def worker_and_sprint(client, db_session, make_project, make_agent, make_sprint):
    project = make_project()
    agent = make_agent(project_id=project["id"], role="backend-worker")
    sprint = make_sprint(project_id=project["id"], status="active",
                         start_date="2026-09-01")
    return {"project": project, "agent": agent, "sprint": sprint}


def _session(db_session, project_id, agent_id, ticket_id=None, sid="s"):
    row = HookSession(
        session_id=sid, agent_id=agent_id, project_id=project_id,
        ticket_id=ticket_id, total_tokens=0, status=HookSessionStatus.completed,
    )
    db_session.add(row)
    db_session.flush()
    return row


class TestTicketSideClaim:
    """The inversion: the ticket tells the sessions, rather than being asked."""

    def test_assigning_a_ticket_claims_the_agents_orphan_sessions(
        self, client, db_session, worker_and_sprint
    ):
        ctx = worker_and_sprint
        pid, aid = ctx["project"]["id"], ctx["agent"]["id"]
        # The worker is spawned and works before anyone assigns it a ticket.
        orphan = _session(db_session, pid, aid, sid="aWorker-576a")
        assert orphan.ticket_id is None

        ticket = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 901, "ticket_key": "TKT-901",
            "title": "assigned after the worker started",
        }).json()

        # Assignment lands later, which is the real sequence.
        r = client.patch(f"/api/tickets/{ticket['id']}",
                         json={"assigned_agent_id": aid},
                         headers={"X-Agent-ID": str(aid)})
        assert r.status_code == 200

        db_session.refresh(orphan)
        assert orphan.ticket_id == ticket["id"]
        assert orphan.sprint_id == ctx["sprint"]["id"]

    def test_claim_never_repoints_an_already_attributed_session(
        self, client, db_session, worker_and_sprint
    ):
        """Re-attributing finished work is worse than leaving it unattributed:
        it moves a cost somebody may already have read."""
        ctx = worker_and_sprint
        pid, aid = ctx["project"]["id"], ctx["agent"]["id"]

        first = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 902, "ticket_key": "TKT-902", "title": "first",
        }).json()
        attributed = _session(db_session, pid, aid, ticket_id=first["id"],
                              sid="aWorker-576b")

        second = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 903, "ticket_key": "TKT-903", "title": "second",
        }).json()
        client.patch(f"/api/tickets/{second['id']}",
                     json={"assigned_agent_id": aid},
                     headers={"X-Agent-ID": str(aid)})

        db_session.refresh(attributed)
        assert attributed.ticket_id == first["id"], (
            "a later ticket stole a session that was already attributed"
        )

    def test_claim_does_not_reach_another_agents_sessions(
        self, client, db_session, worker_and_sprint, make_agent
    ):
        ctx = worker_and_sprint
        pid = ctx["project"]["id"]
        other = make_agent(project_id=pid, role="frontend-worker")
        theirs = _session(db_session, pid, other["id"], sid="aOther-576")

        ticket = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 904, "ticket_key": "TKT-904", "title": "mine",
        }).json()
        client.patch(f"/api/tickets/{ticket['id']}",
                     json={"assigned_agent_id": ctx["agent"]["id"]},
                     headers={"X-Agent-ID": str(ctx["agent"]["id"])})

        db_session.refresh(theirs)
        assert theirs.ticket_id is None

    def test_claim_is_bounded_to_the_sprint_window(
        self, client, db_session, worker_and_sprint
    ):
        """A session from before the sprint started belongs to earlier work."""
        from datetime import datetime

        ctx = worker_and_sprint
        pid, aid = ctx["project"]["id"], ctx["agent"]["id"]
        stale = _session(db_session, pid, aid, sid="aWorker-576-old")
        stale.created_at = datetime(2026, 8, 1, 12, 0, 0)
        db_session.flush()

        ticket = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 905, "ticket_key": "TKT-905", "title": "this sprint",
        }).json()
        client.patch(f"/api/tickets/{ticket['id']}",
                     json={"assigned_agent_id": aid},
                     headers={"X-Agent-ID": str(aid)})

        db_session.refresh(stale)
        assert stale.ticket_id is None, "the claim reached into a previous sprint"

    def test_starting_work_also_claims(self, client, db_session, worker_and_sprint):
        """Assignment is not the only moment the answer becomes knowable."""
        ctx = worker_and_sprint
        pid, aid = ctx["project"]["id"], ctx["agent"]["id"]

        ticket = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 906, "ticket_key": "TKT-906", "title": "start later",
            "assigned_agent_id": aid,
        }).json()
        orphan = _session(db_session, pid, aid, sid="aWorker-576c")

        client.patch(f"/api/tickets/{ticket['id']}",
                     json={"status": "in_progress"},
                     headers={"X-Agent-ID": str(aid)})

        db_session.refresh(orphan)
        assert orphan.ticket_id == ticket["id"]


class TestSelfAssignment:
    """Two tickets were worked start to finish with no assignee and can never
    be costed. Nothing keys on anything but assigned_agent_id."""

    def test_starting_an_unassigned_ticket_assigns_it_to_you(
        self, client, worker_and_sprint
    ):
        ctx = worker_and_sprint
        aid = ctx["agent"]["id"]
        ticket = client.post("/api/tickets", json={
            "project_id": ctx["project"]["id"], "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 907, "ticket_key": "TKT-907", "title": "nobody's",
        }).json()
        assert ticket["assigned_agent_id"] is None

        r = client.patch(f"/api/tickets/{ticket['id']}",
                         json={"status": "in_progress"},
                         headers={"X-Agent-ID": str(aid)})

        assert r.status_code == 200
        assert r.json()["assigned_agent_id"] == aid

    def test_starting_someone_elses_ticket_does_not_steal_it(
        self, client, worker_and_sprint, make_agent
    ):
        """A lead restarting a worker's ticket is a real workflow. Silently
        reassigning it would be worse than the bug being fixed."""
        ctx = worker_and_sprint
        owner = ctx["agent"]["id"]
        other = make_agent(project_id=ctx["project"]["id"], role="team-lead")

        ticket = client.post("/api/tickets", json={
            "project_id": ctx["project"]["id"], "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 908, "ticket_key": "TKT-908", "title": "owned",
            "assigned_agent_id": owner,
        }).json()

        r = client.patch(f"/api/tickets/{ticket['id']}",
                         json={"status": "in_progress"},
                         headers={"X-Agent-ID": str(other["id"])})

        assert r.json()["assigned_agent_id"] == owner

    def test_self_assignment_needs_an_acting_agent(self, client, worker_and_sprint):
        """No X-Agent-ID means no one to assign to; the ticket stays unowned
        rather than acquiring a guessed owner."""
        ctx = worker_and_sprint
        ticket = client.post("/api/tickets", json={
            "project_id": ctx["project"]["id"], "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 909, "ticket_key": "TKT-909", "title": "anonymous",
        }).json()

        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        assert r.status_code == 200
        assert r.json()["assigned_agent_id"] is None


class TestStatusIsNotTheDiscriminator:
    """Pinning the hypothesis that was killed, so it is not re-derived."""

    @pytest.mark.parametrize("status", ["in_progress", "todo", "in_review"])
    def test_resolver_finds_a_ticket_in_each_working_status(
        self, db_session, worker_and_sprint, client, status
    ):
        ctx = worker_and_sprint
        aid = ctx["agent"]["id"]
        ticket = client.post("/api/tickets", json={
            "project_id": ctx["project"]["id"], "sprint_id": ctx["sprint"]["id"],
            "ticket_number": 910, "ticket_key": "TKT-910", "title": "statuses",
            "assigned_agent_id": aid,
        }).json()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": status},
                     headers={"X-Agent-ID": str(aid)})

        from app.models.agent import Agent
        agent = db_session.get(Agent, aid)
        found = ht._resolve_ticket(db_session, agent, ctx["project"]["id"])

        assert found is not None, (
            f"resolution missed a ticket in {status}; following our own "
            "in_review instruction would cost the worker its attribution"
        )
        assert found.id == ticket["id"]


class TestLaterEventReResolves:
    """Part 3, and after DWB-580 this is the main mechanism rather than a tidy.

    The session-side lookup used to be nested inside `if not session.agent_id:`.
    The marker resolves the agent correctly at row creation, so that branch
    essentially never ran again and the ticket question was asked exactly once,
    at the moment the row was created. DWB-580 made later events arrive; this
    makes them ask again.
    """

    def test_a_later_event_fills_a_null_ticket(
        self, client, db_session, make_project, make_agent, make_sprint, tmp_path
    ):
        repo = tmp_path / "repo576"
        repo.mkdir()
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sprint = make_sprint(project_id=project["id"], status="active",
                             start_date="2026-09-01")

        # The session exists and is attributed to the agent, but no ticket was
        # assigned when it was created - the real 15:07 vs 15:32 sequence.
        row = _session(db_session, project["id"], agent["id"], sid="aLater-576")
        assert row.ticket_id is None

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 920, "ticket_key": "TKT-920",
            "title": "assigned after the session row existed",
            "assigned_agent_id": agent["id"], "status": "in_progress",
        }).json()
        # Clear the ticket-side claim's work so ONLY the session-side path can
        # be what fills this in.
        row.ticket_id = None
        db_session.flush()

        ht.handle_session_end(db_session, {
            "session_id": "aLater-576",
            "hook_event": "SessionEnd",
            "cwd": str(repo),
        })

        db_session.refresh(row)
        assert row.ticket_id == ticket["id"], (
            "a later hook event did not re-ask which ticket this agent is on"
        )

    def test_a_later_event_does_not_repoint_an_attributed_session(
        self, client, db_session, make_project, make_agent, make_sprint, tmp_path
    ):
        repo = tmp_path / "repo576b"
        repo.mkdir()
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sprint = make_sprint(project_id=project["id"], status="active",
                             start_date="2026-09-01")

        first = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 921, "ticket_key": "TKT-921", "title": "first",
        }).json()
        row = _session(db_session, project["id"], agent["id"],
                       ticket_id=first["id"], sid="aLater-576b")

        # A newer in_progress ticket would outrank it if this were not fill-only.
        client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 922, "ticket_key": "TKT-922", "title": "newer",
            "assigned_agent_id": agent["id"], "status": "in_progress",
        })

        ht.handle_session_end(db_session, {
            "session_id": "aLater-576b",
            "hook_event": "SessionEnd",
            "cwd": str(repo),
        })

        db_session.refresh(row)
        assert row.ticket_id == first["id"]
