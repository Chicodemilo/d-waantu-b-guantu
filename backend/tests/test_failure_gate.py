# Path:          tests/test_failure_gate.py
# File:          test_failure_gate.py
# Created:       2026-03-28
# Purpose:       Tests for sprint close gate — unreviewed failure records block completion
# Caller:        pytest
# Callees:       POST/PATCH /api/failure-records, PATCH /api/sprints, PATCH /api/tickets
# Data In:       Factory-created projects, sprints, tickets, agents via conftest fixtures
# Data Out:      Assertions on gate-blocked 400s and successful 200 completions
# Last Modified: 2026-03-29

"""Tests for sprint close gate: unreviewed failure records block completion."""

import pytest


@pytest.fixture
def gated_setup(client, make_project, make_epic, make_agent):
    """Project with sprint, ticket, and agents for failure gate tests."""
    project = make_project()
    epic = make_epic(project_id=project["id"])
    sprint = client.post("/api/sprints", json={
        "project_id": project["id"],
        "epic_id": epic["id"],
        "sprint_number": 1,
        "status": "active",
    }).json()
    agent = make_agent()
    logger = make_agent(role="pm")
    # Assign PM to project (needed for rework detection)
    client.post("/api/project-agents", json={
        "project_id": project["id"],
        "agent_id": logger["id"],
    })
    ticket = client.post("/api/tickets", json={
        "project_id": project["id"],
        "sprint_id": sprint["id"],
        "ticket_number": 1,
        "ticket_key": f"{project['prefix']}-001",
        "title": "Test ticket",
        "assigned_agent_id": agent["id"],
    }).json()
    return {
        "project": project,
        "sprint": sprint,
        "ticket": ticket,
        "agent": agent,
        "logger": logger,
    }


class TestFailureRecordGate:
    def test_tbd_failure_record_blocks_close(self, client, gated_setup):
        s = gated_setup
        # Create a TBD failure record
        client.post("/api/failure-records", json={
            "project_id": s["project"]["id"],
            "sprint_id": s["sprint"]["id"],
            "ticket_id": s["ticket"]["id"],
            "agent_id": s["agent"]["id"],
            "logged_by_agent_id": s["logger"]["id"],
            "failure_type": "TBD",
        })

        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400
        assert "unreviewed" in r.json()["detail"].lower()
        assert s["ticket"]["ticket_key"] in r.json()["detail"]

    def test_update_tbd_to_real_type_allows_close(self, client, gated_setup):
        s = gated_setup
        fr = client.post("/api/failure-records", json={
            "project_id": s["project"]["id"],
            "sprint_id": s["sprint"]["id"],
            "ticket_id": s["ticket"]["id"],
            "agent_id": s["agent"]["id"],
            "logged_by_agent_id": s["logger"]["id"],
            "failure_type": "TBD",
        }).json()

        # Should block
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400

        # PM reviews and updates the failure type
        client.patch(f"/api/failure-records/{fr['id']}", json={
            "failure_type": "test_failure",
            "notes": "Reviewed — flaky test",
        })

        # Should now succeed
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_auto_rework_stub_blocks_close(self, client, gated_setup):
        s = gated_setup
        # Simulate rework: move ticket done → in_progress to trigger auto-detection
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})

        # The auto-detected rework stub should block sprint close
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400
        assert "unreviewed" in r.json()["detail"].lower()

    def test_reviewed_rework_allows_close(self, client, gated_setup):
        s = gated_setup
        # Trigger rework
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})

        # Find and review the auto-created failure record
        records = client.get("/api/failure-records", params={
            "project_id": s["project"]["id"],
            "failure_type": "rework",
        }).json()
        for fr in records:
            if fr.get("ticket_id") == s["ticket"]["id"]:
                client.patch(f"/api/failure-records/{fr['id']}", json={
                    "notes": "Reviewed by PM — requirements changed",
                })
                break

        # Move ticket back to done so it's not blocking
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})

        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200

    def test_reviewed_rework_with_boilerplate_notes_intact_does_not_block(
        self, client, gated_setup
    ):
        """DWB-510 regression: a rework record the PM has reviewed must clear the
        gate even when its notes STILL contain the 'Auto-detected' boilerplate.
        The old heuristic matched that literal string in notes and wrongly kept
        the sprint blocked; the structured `reviewed` flag fixes it."""
        s = gated_setup
        # Trigger auto rework detection (done -> in_progress).
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})

        records = client.get("/api/failure-records", params={
            "project_id": s["project"]["id"],
            "failure_type": "rework",
        }).json()
        fr = next(r for r in records if r.get("ticket_id") == s["ticket"]["id"])
        # Preconditions that the OLD heuristic keyed on: the boilerplate string
        # is present in notes, and the record starts unreviewed.
        assert "Auto-detected" in (fr["notes"] or "")
        assert fr["reviewed"] is False

        # PM reviews by adding analysis but does NOT rewrite the notes, so the
        # 'Auto-detected' boilerplate the old heuristic matched is still there.
        updated = client.patch(f"/api/failure-records/{fr['id']}", json={
            "root_cause": "Requirements changed after sign-off",
        }).json()
        assert updated["reviewed"] is True
        assert "Auto-detected" in (updated["notes"] or "")

        # Ticket back to done so it isn't itself blocking; then close must pass.
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200, r.text

    def test_explicit_reviewed_flag_clears_rework_gate(self, client, gated_setup):
        """DWB-510: a PM can clear the gate by setting reviewed=True explicitly,
        with no other edit and the boilerplate notes untouched."""
        s = gated_setup
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "in_progress"})

        records = client.get("/api/failure-records", params={
            "project_id": s["project"]["id"],
            "failure_type": "rework",
        }).json()
        fr = next(r for r in records if r.get("ticket_id") == s["ticket"]["id"])

        # Still blocks while unreviewed.
        client.patch(f"/api/tickets/{s['ticket']['id']}", json={"status": "done"})
        blocked = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert blocked.status_code == 400

        client.patch(f"/api/failure-records/{fr['id']}", json={"reviewed": True})
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200, r.text

    def test_no_failure_records_allows_close(self, client, gated_setup):
        s = gated_setup
        # No failure records — should close fine
        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200

    def test_non_tbd_failure_record_does_not_block(self, client, gated_setup):
        s = gated_setup
        # Create a reviewed failure record (not TBD, not auto-rework)
        client.post("/api/failure-records", json={
            "project_id": s["project"]["id"],
            "sprint_id": s["sprint"]["id"],
            "ticket_id": s["ticket"]["id"],
            "agent_id": s["agent"]["id"],
            "logged_by_agent_id": s["logger"]["id"],
            "failure_type": "test_failure",
            "notes": "Already reviewed",
        })

        r = client.patch(f"/api/sprints/{s['sprint']['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
