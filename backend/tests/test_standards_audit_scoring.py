# Path: tests/test_standards_audit_scoring.py
# File: test_standards_audit_scoring.py
# Created: 2026-08-11 (DWB-016)
# Purpose: DWB-016 acceptance - applying an audit scorecard writes correctly
#          attributed score_event rows (worker/Archie/Pam paths), a clean PASS
#          writes worker carrots, application is idempotent, and unresolvable /
#          off-roster / zero-delta entries are skipped.
# Caller: pytest
# Callees: POST /api/standards-audits, POST /api/standards-audits/{id}/apply-scorecard
# Data In: Factory-created project/agents/sprint via conftest fixtures
# Data Out: Assertions on ScoreEvent rows + apply-result payloads
# Last Modified: 2026-08-11 (DWB-016)

import pytest
from sqlalchemy import select

from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType


def _assign(client, project_id, agent_id):
    r = client.post(
        "/api/project-agents",
        json={"project_id": project_id, "agent_id": agent_id},
    )
    assert r.status_code == 201


@pytest.fixture
def env(client, make_project, make_agent):
    """Project with worker + Archie (TL) + Pam (PM) on the roster and an active
    sprint."""
    project = make_project()
    pid = project["id"]
    worker = make_agent(project_id=pid, name="AuditWorker", role="backend-worker",
                        api_key="aud-worker")
    archie = make_agent(project_id=pid, name="AuditArchie", role="team-lead",
                        api_key="aud-archie")
    pam = make_agent(project_id=pid, name="AuditPam", role="pm", api_key="aud-pam")
    for a in (worker, archie, pam):
        _assign(client, pid, a["id"])
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    sprint = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "audit sprint",
        "sprint_number": 1, "status": "active",
    }).json()
    return {
        "pid": pid, "sprint_id": sprint["id"],
        "worker": worker["id"], "archie": archie["id"], "pam": pam["id"],
    }


def _create_audit(client, pid, scorecard, verdict="reject", **overrides):
    payload = {
        "project_id": pid,
        "pr_ref": "PR#99",
        "verdict": verdict,
        "scorecard": scorecard,
    }
    payload.update(overrides)
    r = client.post("/api/standards-audits", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _events_for_audit(db, audit_id):
    return list(db.scalars(
        select(ScoreEvent)
        .where(ScoreEvent.ref_type == "standards_audit")
        .where(ScoreEvent.ref_id == audit_id)
    ).all())


class TestApplyRejectAudit:
    def test_worker_archie_pam_paths(self, client, db_session, env):
        # Worker docked for a violation on their ticket; Archie docked for a
        # repeat violation surviving review; Pam credited (ticketing was clear,
        # dev ignored it -> dev stick already on worker, Pam carrot).
        audit = _create_audit(
            client, env["pid"],
            scorecard=[
                {"agent": "AuditWorker", "delta": -3, "reason": "missing headers on 2 files"},
                {"agent": "AuditArchie", "delta": -2, "reason": "repeat: headers flagged last audit, survived review"},
                {"agent": "AuditPam", "delta": 1, "reason": "ticket was explicit; dev ignored it"},
            ],
            sprint_id=env["sprint_id"],
        )
        r = client.post(f"/api/standards-audits/{audit['id']}/apply-scorecard")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_applied"] is False
        assert len(body["applied"]) == 3
        assert body["skipped"] == []

        evs = {e.subject_agent_id: e for e in _events_for_audit(db_session, audit["id"])}
        assert len(evs) == 3

        w = evs[env["worker"]]
        assert w.delta == -3
        assert w.source == ScoreSource.audit
        assert w.trigger_type == ScoreTriggerType.audit_demerit
        assert w.ref_type == "standards_audit" and w.ref_id == audit["id"]
        assert w.sprint_id == env["sprint_id"]
        assert "missing headers" in w.reason

        a = evs[env["archie"]]
        assert a.delta == -2
        assert a.trigger_type == ScoreTriggerType.audit_demerit
        assert "repeat" in a.reason

        p = evs[env["pam"]]
        assert p.delta == 1
        assert p.trigger_type == ScoreTriggerType.audit_grant
        assert p.source == ScoreSource.audit


class TestApplyPassAudit:
    def test_clean_pass_writes_worker_carrot(self, client, db_session, env):
        audit = _create_audit(
            client, env["pid"],
            scorecard=[{"agent": "AuditWorker", "delta": 2, "reason": "clean, headers + tests present"}],
            verdict="pass",
            sprint_id=env["sprint_id"],
        )
        r = client.post(f"/api/standards-audits/{audit['id']}/apply-scorecard")
        assert r.status_code == 200
        body = r.json()
        assert len(body["applied"]) == 1
        assert body["applied"][0]["agent_id"] == env["worker"]
        assert body["applied"][0]["delta"] == 2
        assert body["applied"][0]["trigger_type"] == "audit_grant"

        evs = _events_for_audit(db_session, audit["id"])
        assert len(evs) == 1
        assert evs[0].delta == 2
        assert evs[0].trigger_type == ScoreTriggerType.audit_grant


class TestIdempotency:
    def test_reapply_is_noop(self, client, db_session, env):
        audit = _create_audit(
            client, env["pid"],
            scorecard=[{"agent": "AuditWorker", "delta": -3, "reason": "v"}],
            sprint_id=env["sprint_id"],
        )
        first = client.post(f"/api/standards-audits/{audit['id']}/apply-scorecard").json()
        assert first["already_applied"] is False
        assert len(first["applied"]) == 1

        second = client.post(f"/api/standards-audits/{audit['id']}/apply-scorecard").json()
        assert second["already_applied"] is True
        assert second["applied"] == []
        assert second["skipped"] == []

        # Still exactly one ledger row for this audit - no double-write.
        assert len(_events_for_audit(db_session, audit["id"])) == 1


class TestSkips:
    def test_unresolved_offroster_and_zero_delta_skipped(
        self, client, db_session, env, make_agent
    ):
        # An agent that exists globally but is NOT on this project's roster.
        # Created on its own auto-provisioned project (no project_id given), so
        # resolve_agent_ref finds it by name but is_project_member is False here.
        offroster = make_agent(name="AuditOffRoster",
                               role="backend-worker", api_key="aud-off")
        audit = _create_audit(
            client, env["pid"],
            scorecard=[
                {"agent": "AuditWorker", "delta": -3, "reason": "real"},
                {"agent": "NoSuchAgent", "delta": -2, "reason": "ghost"},
                {"agent": "AuditOffRoster", "delta": -1, "reason": "off roster"},
                {"agent": "AuditPam", "delta": 0, "reason": "zero"},
            ],
            sprint_id=env["sprint_id"],
        )
        body = client.post(
            f"/api/standards-audits/{audit['id']}/apply-scorecard"
        ).json()

        assert len(body["applied"]) == 1
        assert body["applied"][0]["agent_id"] == env["worker"]

        reasons = {s["agent"]: s["reason"] for s in body["skipped"]}
        assert reasons["NoSuchAgent"] == "agent not found"
        assert reasons["AuditOffRoster"] == "agent not on project roster"
        assert reasons["AuditPam"] == "zero delta (no-op)"

        # Only the worker's row hit the ledger.
        evs = _events_for_audit(db_session, audit["id"])
        assert len(evs) == 1
        assert evs[0].subject_agent_id == env["worker"]
