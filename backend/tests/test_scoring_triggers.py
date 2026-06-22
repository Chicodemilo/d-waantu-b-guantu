# Path: tests/test_scoring_triggers.py
# File: test_scoring_triggers.py
# Created: 2026-06-22
# Purpose: DWB-425 acceptance - auto-trigger engine fires score_event rows for
#          ticket_closed (+ no-rework bonus), rework, test_failure, stale,
#          zero_token_close, gate_miss, and forgot; attribution by domain owner;
#          idempotent per ticket / failure / sprint.
# Caller: pytest
# Callees: PATCH /api/tickets, PATCH /api/sprints, app.services.scoring_triggers,
#          app.services.ticket.stale_check
# Data In: Factory-created projects/agents/sprints/tickets via conftest fixtures
# Data Out: Assertions on ScoreEvent rows
# Last Modified: 2026-06-22

"""Tests for the agent scoring auto-trigger engine (DWB-425)."""

import pytest
from sqlalchemy import select

from app.config.scoring import points_for
from app.models.failure_record import FailureRecord
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.services import scoring_triggers
from app.services import ticket as ticket_svc


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


def _hdr(agent_id):
    return {"X-Agent-ID": str(agent_id)}


@pytest.fixture
def trig(client, make_project, make_agent):
    """Project with a worker + PM + TL, an active sprint, and a tmp repo."""
    project = make_project()
    pid = project["id"]
    worker = make_agent(project_id=pid, name="TrigWorker", role="backend-worker",
                        api_key="trig-worker")
    pm = make_agent(project_id=pid, name="TrigPM", role="pm", api_key="trig-pm")
    tl = make_agent(project_id=pid, name="TrigTL", role="team-lead", api_key="trig-tl")
    for a in (worker, pm, tl):
        _assign(client, pid, a["id"])
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    sprint = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "trigger sprint",
        "sprint_number": 1, "status": "active",
    }).json()
    return {"pid": pid, "sprint_id": sprint["id"],
            "worker": worker["id"], "pm": pm["id"], "tl": tl["id"]}


def _ticket(make_ticket, trig, status="in_progress"):
    return make_ticket(
        project_id=trig["pid"], sprint_id=trig["sprint_id"],
        assigned_agent_id=trig["worker"], status=status,
    )


def _events(db, *, ref_type, ref_id, trigger=None):
    stmt = (select(ScoreEvent)
            .where(ScoreEvent.ref_type == ref_type)
            .where(ScoreEvent.ref_id == ref_id))
    if trigger is not None:
        stmt = stmt.where(ScoreEvent.trigger_type == trigger)
    return list(db.scalars(stmt).all())


class TestTicketClosed:
    def test_close_awards_ticket_closed_with_no_rework_bonus(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.ticket_closed)
        assert len(evs) == 1
        assert evs[0].subject_agent_id == trig["worker"]
        assert evs[0].delta == points_for("ticket_closed") + points_for("no_rework_bonus")
        assert evs[0].source == ScoreSource.auto
        assert evs[0].sprint_id == trig["sprint_id"]

    def test_close_with_prior_rework_omits_bonus(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        # A rework record exists before the close -> bonus withheld.
        db_session.add(FailureRecord(
            project_id=trig["pid"], ticket_id=t["id"], sprint_id=trig["sprint_id"],
            agent_id=trig["worker"], logged_by_agent_id=trig["pm"],
            failure_type="rework", severity="medium", attempt_number=1,
            resolved=False,
        ))
        db_session.commit()
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.ticket_closed)
        assert len(evs) == 1
        assert evs[0].delta == points_for("ticket_closed")

    def test_ticket_closed_is_idempotent_across_reopen(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        # reopen (rework) then close again
        client.patch(f"/api/tickets/{t['id']}", json={"status": "in_progress"},
                     headers=_hdr(trig["worker"]))
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.ticket_closed)
        assert len(evs) == 1  # never double-awarded


class TestZeroTokenClose:
    def test_zero_token_close_fires_when_no_tokens(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.zero_token_close)
        assert len(evs) == 1
        assert evs[0].delta == points_for("zero_token_close")


class TestForgot:
    def test_forgot_fires_when_never_in_progress(self, client, db_session, trig, make_ticket):
        # Created straight as todo, closed without ever going in_progress.
        t = _ticket(make_ticket, trig, status="todo")
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.forgot)
        assert len(evs) == 1
        assert evs[0].delta == points_for("forgot")
        assert "never moved to in_progress" in evs[0].reason


class TestRework:
    def test_reopen_after_done_penalizes_rework(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        client.patch(f"/api/tickets/{t['id']}", json={"status": "done"},
                     headers=_hdr(trig["worker"]))
        client.patch(f"/api/tickets/{t['id']}", json={"status": "in_progress"},
                     headers=_hdr(trig["worker"]))
        # rework failure record was created -> rework penalty for the worker
        evs = db_session.scalars(
            select(ScoreEvent)
            .where(ScoreEvent.ref_type == "failure_record")
            .where(ScoreEvent.trigger_type == ScoreTriggerType.rework)
            .where(ScoreEvent.subject_agent_id == trig["worker"])
        ).all()
        assert len(evs) == 1
        assert evs[0].delta == points_for("rework")


class TestTestFailure:
    def test_test_failure_scores_ticket_owner(self, db_session, trig):
        # A test_failure record tied to a ticket -> penalize the ticket owner.
        fr = FailureRecord(
            project_id=trig["pid"], ticket_id=None, sprint_id=trig["sprint_id"],
            agent_id=trig["worker"], logged_by_agent_id=trig["worker"],
            failure_type="test_failure", severity="medium", attempt_number=1,
            resolved=False,
        )
        # attach to a ticket so the owner is resolvable
        db_session.add(fr)
        db_session.flush()
        # no ticket_id -> skipped (does not punish the tester who logged it)
        assert scoring_triggers.score_failure_record(db_session, fr, commit=True) is None

    def test_test_failure_with_ticket_penalizes_assignee(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        fr = FailureRecord(
            project_id=trig["pid"], ticket_id=t["id"], sprint_id=trig["sprint_id"],
            agent_id=trig["pm"], logged_by_agent_id=trig["pm"],
            failure_type="test_failure", severity="medium", attempt_number=1,
            resolved=False,
        )
        db_session.add(fr)
        db_session.flush()
        ev = scoring_triggers.score_failure_record(db_session, fr, commit=True)
        assert ev is not None
        assert ev.subject_agent_id == trig["worker"]  # the ticket's assignee
        assert ev.delta == points_for("test_failure")

    def test_test_failure_idempotent(self, client, db_session, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        fr = FailureRecord(
            project_id=trig["pid"], ticket_id=t["id"], sprint_id=trig["sprint_id"],
            agent_id=trig["pm"], logged_by_agent_id=trig["pm"],
            failure_type="test_failure", severity="medium", attempt_number=1,
            resolved=False,
        )
        db_session.add(fr)
        db_session.flush()
        scoring_triggers.score_failure_record(db_session, fr, commit=True)
        assert scoring_triggers.score_failure_record(db_session, fr, commit=True) is None


class TestStale:
    def test_stale_check_penalizes_assignee(self, db_session, client, trig, make_ticket):
        t = _ticket(make_ticket, trig)
        ticket_obj = ticket_svc.get_ticket(db_session, t["id"])
        ticket_svc.stale_check(db_session, ticket_obj, trig["pid"], 30, "TrigWorker")
        evs = _events(db_session, ref_type="ticket", ref_id=t["id"],
                      trigger=ScoreTriggerType.stale)
        assert len(evs) == 1
        assert evs[0].subject_agent_id == trig["worker"]
        assert evs[0].delta == points_for("stale")


class TestGateMiss:
    def test_blocked_close_records_gate_miss(self, client, db_session, make_agent, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "GM", "name": "GateMiss", "repo_path": str(tmp_path),
            "force_test_run": False, "force_test_coverage": False,
            "force_initial_md": False, "force_architecture_md": False,
            "force_handoff_md": True,
        }).json()
        pid = project["id"]
        tl = make_agent(project_id=pid, name="GateTL", role="team-lead",
                        api_key="gate-tl")
        _assign(client, pid, tl["id"])
        epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
        sprint = client.post("/api/sprints", json={
            "project_id": pid, "epic_id": epic["id"], "goal": "g",
            "sprint_number": 1, "status": "active",
        }).json()
        # No HANDOFF.md at repo_path -> handoff gate blocks the close.
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"},
                         headers=_hdr(tl["id"]))
        assert r.status_code == 400
        evs = _events(db_session, ref_type="sprint", ref_id=sprint["id"],
                      trigger=ScoreTriggerType.gate_miss)
        assert len(evs) == 1
        assert evs[0].subject_agent_id == tl["id"]
        assert evs[0].delta == points_for("gate_miss")

    def test_gate_miss_idempotent_per_sprint(self, client, db_session, make_agent, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "GM2", "name": "GateMiss2", "repo_path": str(tmp_path),
            "force_test_run": False, "force_test_coverage": False,
            "force_initial_md": False, "force_architecture_md": False,
            "force_handoff_md": True,
        }).json()
        pid = project["id"]
        tl = make_agent(project_id=pid, name="GateTL2", role="team-lead",
                        api_key="gate-tl2")
        _assign(client, pid, tl["id"])
        epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
        sprint = client.post("/api/sprints", json={
            "project_id": pid, "epic_id": epic["id"], "goal": "g",
            "sprint_number": 1, "status": "active",
        }).json()
        for _ in range(2):
            client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"},
                         headers=_hdr(tl["id"]))
        evs = _events(db_session, ref_type="sprint", ref_id=sprint["id"],
                      trigger=ScoreTriggerType.gate_miss)
        assert len(evs) == 1  # one gate_miss per sprint, not per attempt
