# Path: tests/test_standards_audit_gate.py
# File: test_standards_audit_gate.py
# Created: 2026-08-11 (DWB-017)
# Purpose: DWB-017 acceptance - the force_standards_audit sprint gate. gate-status
#          reports passing across the five states (PASS since start, no audit,
#          reject-only, PASS before start, disabled), the payload shape is
#          correct, PATCH toggles round-trip, and sprint close is actually
#          blocked without a passing audit.
# Caller: pytest
# Callees: GET /api/projects/{id}/gate-status, PATCH /api/projects/{id},
#          POST /api/standards-audits, PATCH /api/sprints/{id}
# Data In: Factory-created project/epic + direct sprint/audit API calls
# Data Out: Assertions on gate-status payload + sprint-close behavior
# Last Modified: 2026-08-11 (DWB-017)

# A start_date safely in the past -> "now" audits fall inside the sprint window.
PAST = "2020-01-01"
# A start_date in the future -> "now" audits fall BEFORE the sprint window.
FUTURE = "2099-01-01"


def _active_sprint(client, project_id, make_epic, start_date):
    epic = make_epic(project_id=project_id)
    r = client.post("/api/sprints", json={
        "project_id": project_id, "epic_id": epic["id"], "goal": "gate sprint",
        "sprint_number": 1, "status": "active", "start_date": start_date,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _audit(client, project_id, verdict, sprint_id=None):
    r = client.post("/api/standards-audits", json={
        "project_id": project_id, "pr_ref": "PR#1", "verdict": verdict,
        "sprint_id": sprint_id,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _audit_gate(client, project_id):
    r = client.get(f"/api/projects/{project_id}/gate-status")
    assert r.status_code == 200, r.text
    payload = r.json()
    gate = next(g for g in payload["gates"] if g["toggle"] == "force_standards_audit")
    return payload, gate


class TestGateStatusStates:
    def test_enabled_pass_since_start_passing(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        _active_sprint(client, p["id"], make_epic, PAST)
        _audit(client, p["id"], "pass")
        _, gate = _audit_gate(client, p["id"])
        assert gate["enabled"] is True
        assert gate["passing"] is True
        assert gate["latest_audit_verdict"] == "pass"

    def test_enabled_no_audit_not_passing(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        _active_sprint(client, p["id"], make_epic, PAST)
        _, gate = _audit_gate(client, p["id"])
        assert gate["enabled"] is True
        assert gate["passing"] is False
        assert gate["latest_audit_verdict"] is None

    def test_enabled_reject_only_not_passing(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        _active_sprint(client, p["id"], make_epic, PAST)
        _audit(client, p["id"], "reject")
        _, gate = _audit_gate(client, p["id"])
        assert gate["passing"] is False
        assert gate["latest_audit_verdict"] == "reject"

    def test_enabled_pass_before_start_not_passing(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        _active_sprint(client, p["id"], make_epic, FUTURE)
        _audit(client, p["id"], "pass")
        _, gate = _audit_gate(client, p["id"])
        # A PASS exists but predates the (future) sprint start -> outside window.
        assert gate["passing"] is False
        assert gate["latest_audit_verdict"] == "pass"

    def test_disabled_passing_regardless(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=False)
        _active_sprint(client, p["id"], make_epic, PAST)
        _audit(client, p["id"], "reject")  # even a reject present
        _, gate = _audit_gate(client, p["id"])
        assert gate["enabled"] is False
        assert gate["passing"] is True
        # No scan when disabled.
        assert gate["latest_audit_verdict"] is None


class TestGatePayloadAndToggle:
    def test_payload_shape(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        _active_sprint(client, p["id"], make_epic, PAST)
        payload, gate = _audit_gate(client, p["id"])
        assert "all_passing" in payload
        assert set(gate.keys()) >= {
            "kind", "toggle", "enabled", "passing", "latest_audit_verdict"
        }
        assert gate["kind"] == "audit"

    def test_patch_toggle_round_trips(self, client, make_project):
        p = make_project(force_standards_audit=False)
        assert p["force_standards_audit"] is False
        r = client.patch(f"/api/projects/{p['id']}", json={"force_standards_audit": True})
        assert r.status_code == 200, r.text
        assert r.json()["force_standards_audit"] is True
        # Read-back confirms persistence.
        got = client.get(f"/api/projects/{p['id']}").json()
        assert got["force_standards_audit"] is True


class TestSprintCloseEnforcement:
    def test_close_blocked_without_passing_audit(self, client, make_project, make_epic):
        # repo_path is None -> doc gates are skipped; only the audit gate applies.
        p = make_project(force_standards_audit=True)
        sprint = _active_sprint(client, p["id"], make_epic, PAST)
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400
        assert "force_standards_audit" in r.json()["detail"]

    def test_close_allowed_with_passing_audit(self, client, make_project, make_epic):
        p = make_project(force_standards_audit=True)
        sprint = _active_sprint(client, p["id"], make_epic, PAST)
        _audit(client, p["id"], "pass")
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
