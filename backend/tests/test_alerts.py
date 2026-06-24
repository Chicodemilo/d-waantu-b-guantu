# Path:          tests/test_alerts.py
# File:          test_alerts.py
# Created:       2026-03-28
# Purpose:       CRUD + filtering tests for /api/alerts
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/alerts, GET /api/alerts/:id
# Data In:       Factory-created projects, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes and JSON response shapes
# Last Modified: 2026-06-04

"""Tests for /api/alerts CRUD, filtering, and run-tests endpoint."""


class TestListAlerts:
    def test_list_returns_200(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_alert(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test",
            "body": "Body",
        }).json()
        alerts = client.get("/api/alerts").json()
        ids = [a["id"] for a in alerts]
        assert created["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_agent):
        p1 = make_project()
        p2 = make_project()
        agent = make_agent()
        a1 = client.post("/api/alerts", json={
            "project_id": p1["id"], "raised_by_agent_id": agent["id"],
            "title": "A1", "body": "B1",
        }).json()
        a2 = client.post("/api/alerts", json={
            "project_id": p2["id"], "raised_by_agent_id": agent["id"],
            "title": "A2", "body": "B2",
        }).json()
        filtered = client.get("/api/alerts", params={"project_id": p1["id"]}).json()
        ids = [a["id"] for a in filtered]
        assert a1["id"] in ids
        assert a2["id"] not in ids

    def test_filter_by_severity(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "Info", "body": "B", "severity": "info",
        })
        client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "Warn", "body": "B", "severity": "warning",
        })
        filtered = client.get("/api/alerts", params={"severity": "info"}).json()
        assert all(a["severity"] == "info" for a in filtered)

    def test_filter_by_status(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        a = client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "T", "body": "B",
        }).json()
        client.patch(f"/api/alerts/{a['id']}", json={"status": "resolved"})
        open_alerts = client.get("/api/alerts", params={"status": "open"}).json()
        assert a["id"] not in [al["id"] for al in open_alerts]


class TestGetAlert:
    def test_get_returns_200(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test", "body": "Body",
        }).json()
        r = client.get(f"/api/alerts/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_response_shape(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test", "body": "Body",
        }).json()
        data = client.get(f"/api/alerts/{created['id']}").json()
        expected_keys = {
            "id", "project_id", "raised_by_agent_id", "recipient_agent_id",
            "ticket_id", "title", "body", "severity", "status", "category",
            "created_at", "resolved_at", "user_sent_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/alerts/999999")
        assert r.status_code == 404


class TestCreateAlert:
    def test_create_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "New Alert",
            "body": "Alert body",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "New Alert"
        assert data["severity"] == "info"
        assert data["status"] == "open"

    def test_create_with_severity(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Warning", "body": "Body",
            "severity": "warning",
        })
        assert r.status_code == 201
        assert r.json()["severity"] == "warning"


class TestUpdateAlert:
    def test_patch_status(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "T", "body": "B",
        }).json()
        r = client.patch(f"/api/alerts/{created['id']}", json={"status": "resolved"})
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/alerts/999999", json={"status": "resolved"})
        assert r.status_code == 404


class TestRunTests:
    """DWB-463: a test-run request is recorded to the activity feed, not as an
    alert. The endpoint returns a RunTestsResponse and creates NO alert row."""

    def test_run_tests_returns_201_and_records_feed_event(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        alerts_before = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        r = client.post("/api/alerts/run-tests", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "recorded"
        assert data["project_id"] == project["id"]
        assert data["action"] == "test_run_requested"
        # No alert row was created.
        alerts_after = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        assert len(alerts_after) == len(alerts_before)
        # The activity feed carries the test_run_requested action.
        feed = client.get(f"/api/projects/{project['id']}/activity-feed").json()
        actions = [e.get("action") for e in feed]
        assert "test_run_requested" in actions

    def test_run_tests_nonexistent_project_returns_404(self, client):
        r = client.post("/api/alerts/run-tests", json={"project_id": 999999})
        assert r.status_code == 404


class TestAutoUnlinkAlertsFile:
    """DWB-303: global Dismiss All (no project_id) must still unlink
    ALERTS_PENDING.md on disk. Repro: PM/frontend POSTs `{}` to dismiss-all,
    the on-disk file stays orphaned because the auto-unlink path used to
    gate on a project_id the caller never sent."""

    def test_dismiss_all_without_project_id_unlinks_file(
        self, client, make_agent, tmp_path
    ):
        from pathlib import Path

        # Project with a real repo_path so send_to_team can write the file
        project = client.post("/api/projects", json={
            "prefix": "ALK1", "name": "AutoUnlink One",
            "repo_path": str(tmp_path),
        }).json()
        agent = make_agent(project_id=project["id"])
        client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "T", "body": "B",
        })
        # Write ALERTS_PENDING.md via send-to-team
        send = client.post(
            "/api/alerts/send-to-team", params={"project_id": project["id"]}
        )
        assert send.status_code == 200
        alerts_file = Path(tmp_path) / ".claude" / "ALERTS_PENDING.md"
        assert alerts_file.is_file(), "send-to-team must write the file"

        # The bug: dismiss_all with no project_id used to skip the unlink path.
        r = client.post("/api/alerts/dismiss-all", json={})
        assert r.status_code == 200
        assert r.json()["dismissed"] >= 1

        # Acceptance: file is gone.
        assert not alerts_file.exists(), (
            "ALERTS_PENDING.md must be unlinked after global dismiss-all"
        )

    def test_dismiss_all_unlinks_files_across_projects(
        self, client, make_agent, tmp_path
    ):
        """A single global Dismiss All should clear ALERTS_PENDING.md on
        every project that has no remaining open alerts."""
        from pathlib import Path

        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        proj_a = client.post("/api/projects", json={
            "prefix": "ALKA", "name": "A", "repo_path": str(repo_a),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "ALKB", "name": "B", "repo_path": str(repo_b),
        }).json()
        agent_a = make_agent(project_id=proj_a["id"])
        agent_b = make_agent(project_id=proj_b["id"])

        for pid, aid in ((proj_a["id"], agent_a["id"]), (proj_b["id"], agent_b["id"])):
            client.post("/api/alerts", json={
                "project_id": pid, "raised_by_agent_id": aid,
                "title": "T", "body": "B",
            })
            r = client.post(
                "/api/alerts/send-to-team", params={"project_id": pid}
            )
            assert r.status_code == 200

        file_a = repo_a / ".claude" / "ALERTS_PENDING.md"
        file_b = repo_b / ".claude" / "ALERTS_PENDING.md"
        assert file_a.is_file()
        assert file_b.is_file()

        r = client.post("/api/alerts/dismiss-all", json={})
        assert r.status_code == 200

        assert not file_a.exists()
        assert not file_b.exists()

    def test_dismiss_all_keeps_file_when_open_alerts_remain(
        self, client, make_agent, tmp_path
    ):
        """If a project still has open alerts after dismiss-all (e.g.
        because project_id was scoped to a different project), its
        ALERTS_PENDING.md must NOT be deleted."""
        from pathlib import Path

        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        proj_a = client.post("/api/projects", json={
            "prefix": "ALKC", "name": "A", "repo_path": str(repo_a),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "ALKD", "name": "B", "repo_path": str(repo_b),
        }).json()
        agent_a = make_agent(project_id=proj_a["id"])
        agent_b = make_agent(project_id=proj_b["id"])

        for pid, aid in ((proj_a["id"], agent_a["id"]), (proj_b["id"], agent_b["id"])):
            client.post("/api/alerts", json={
                "project_id": pid, "raised_by_agent_id": aid,
                "title": "T", "body": "B",
            })
            client.post(
                "/api/alerts/send-to-team", params={"project_id": pid}
            )

        file_a = repo_a / ".claude" / "ALERTS_PENDING.md"
        file_b = repo_b / ".claude" / "ALERTS_PENDING.md"

        # Dismiss only project A's alerts. B still has open alerts.
        r = client.post(
            "/api/alerts/dismiss-all", json={"project_id": proj_a["id"]}
        )
        assert r.status_code == 200
        assert not file_a.exists()
        assert file_b.exists()
