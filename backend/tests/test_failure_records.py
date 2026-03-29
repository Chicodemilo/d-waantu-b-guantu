# Path:          tests/test_failure_records.py
# File:          test_failure_records.py
# Created:       2026-03-28
# Purpose:       CRUD + filtering + summary tests for /api/failure-records
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/failure-records, GET /api/failure-records/summary
# Data In:       Factory-created projects, sprints, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes, JSON shapes, and summary counts
# Last Modified: 2026-03-29

"""Tests for /api/failure-records CRUD, filtering, and summary."""

import pytest


@pytest.fixture
def failure_deps(client, make_project, make_epic, make_sprint, make_agent):
    """Create shared dependencies for failure record tests."""
    project = make_project()
    epic = make_epic(project_id=project["id"])
    sprint = make_sprint(project_id=project["id"])
    agent = make_agent()
    logger = make_agent(role="team-lead")
    return {
        "project": project,
        "epic": epic,
        "sprint": sprint,
        "agent": agent,
        "logger": logger,
    }


def _make_failure(client, deps, **overrides):
    data = {
        "project_id": deps["project"]["id"],
        "sprint_id": deps["sprint"]["id"],
        "agent_id": deps["agent"]["id"],
        "logged_by_agent_id": deps["logger"]["id"],
        "failure_type": "test_failure",
        **overrides,
    }
    r = client.post("/api/failure-records", json=data)
    assert r.status_code == 201
    return r.json()


class TestListFailureRecords:
    def test_list_returns_200(self, client):
        r = client.get("/api/failure-records")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_record(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        records = client.get("/api/failure-records").json()
        ids = [r["id"] for r in records]
        assert record["id"] in ids

    def test_filter_by_project_id(self, client, failure_deps, make_project, make_sprint, make_agent):
        _make_failure(client, failure_deps)
        p2 = make_project()
        s2 = make_sprint(project_id=p2["id"])
        a2 = make_agent()
        _make_failure(client, failure_deps, project_id=p2["id"], sprint_id=s2["id"], agent_id=a2["id"])

        records = client.get("/api/failure-records", params={
            "project_id": failure_deps["project"]["id"],
        }).json()
        assert all(r["project_id"] == failure_deps["project"]["id"] for r in records)

    def test_filter_by_sprint_id(self, client, failure_deps, make_sprint):
        _make_failure(client, failure_deps)
        s2 = make_sprint(project_id=failure_deps["project"]["id"])
        _make_failure(client, failure_deps, sprint_id=s2["id"])

        records = client.get("/api/failure-records", params={
            "sprint_id": failure_deps["sprint"]["id"],
        }).json()
        assert all(r["sprint_id"] == failure_deps["sprint"]["id"] for r in records)

    def test_filter_by_agent_id(self, client, failure_deps, make_agent):
        _make_failure(client, failure_deps)
        a2 = make_agent()
        _make_failure(client, failure_deps, agent_id=a2["id"])

        records = client.get("/api/failure-records", params={
            "agent_id": failure_deps["agent"]["id"],
        }).json()
        assert all(r["agent_id"] == failure_deps["agent"]["id"] for r in records)

    def test_filter_by_failure_type(self, client, failure_deps):
        _make_failure(client, failure_deps, failure_type="test_failure")
        _make_failure(client, failure_deps, failure_type="build_failure")

        records = client.get("/api/failure-records", params={
            "failure_type": "test_failure",
        }).json()
        assert all(r["failure_type"] == "test_failure" for r in records)

    def test_filter_by_resolved(self, client, failure_deps):
        _make_failure(client, failure_deps, resolved=False)
        _make_failure(client, failure_deps, resolved=True)

        open_records = client.get("/api/failure-records", params={"resolved": False}).json()
        assert all(r["resolved"] is False for r in open_records)

        resolved_records = client.get("/api/failure-records", params={"resolved": True}).json()
        assert all(r["resolved"] is True for r in resolved_records)


class TestGetFailureRecord:
    def test_get_returns_200(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        r = client.get(f"/api/failure-records/{record['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == record["id"]

    def test_get_response_shape(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        data = client.get(f"/api/failure-records/{record['id']}").json()
        expected_keys = {
            "id", "project_id", "ticket_id", "sprint_id", "agent_id",
            "logged_by_agent_id", "failure_type", "severity",
            "attempt_number", "notes", "root_cause", "resolution",
            "resolved", "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/failure-records/999999")
        assert r.status_code == 404


class TestCreateFailureRecord:
    def test_create_returns_201(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        assert record["failure_type"] == "test_failure"
        assert record["severity"] == "medium"  # default
        assert record["resolved"] is False  # default

    def test_create_with_all_fields(self, client, failure_deps, make_ticket):
        ticket = make_ticket(project_id=failure_deps["project"]["id"])
        record = _make_failure(client, failure_deps,
            ticket_id=ticket["id"],
            failure_type="build_failure",
            severity="high",
            attempt_number=3,
            notes="Build timed out",
            root_cause="OOM",
            resolution="Increased memory",
            resolved=True,
        )
        assert record["ticket_id"] == ticket["id"]
        assert record["severity"] == "high"
        assert record["attempt_number"] == 3
        assert record["notes"] == "Build timed out"
        assert record["root_cause"] == "OOM"
        assert record["resolution"] == "Increased memory"
        assert record["resolved"] is True


class TestUpdateFailureRecord:
    def test_patch_updates_fields(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        r = client.patch(f"/api/failure-records/{record['id']}", json={
            "resolved": True,
            "resolution": "Fixed the test",
            "root_cause": "Flaky assertion",
        })
        assert r.status_code == 200
        assert r.json()["resolved"] is True
        assert r.json()["resolution"] == "Fixed the test"
        assert r.json()["root_cause"] == "Flaky assertion"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/failure-records/999999", json={"resolved": True})
        assert r.status_code == 404


class TestDeleteFailureRecord:
    def test_delete_returns_204(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        r = client.delete(f"/api/failure-records/{record['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, failure_deps):
        record = _make_failure(client, failure_deps)
        client.delete(f"/api/failure-records/{record['id']}")
        r = client.get(f"/api/failure-records/{record['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/failure-records/999999")
        assert r.status_code == 404


class TestFailureRecordSummary:
    def test_summary_returns_200(self, client):
        r = client.get("/api/failure-records/summary")
        assert r.status_code == 200

    def test_summary_response_shape(self, client):
        data = client.get("/api/failure-records/summary").json()
        expected_keys = {
            "total", "resolved_count", "open_count",
            "by_type", "by_agent", "by_sprint", "trend",
        }
        assert set(data.keys()) == expected_keys

    def test_summary_empty_returns_zeroes(self, client):
        data = client.get("/api/failure-records/summary").json()
        assert data["total"] == 0
        assert data["resolved_count"] == 0
        assert data["open_count"] == 0

    def test_summary_counts_match(self, client, failure_deps):
        _make_failure(client, failure_deps, resolved=False)
        _make_failure(client, failure_deps, resolved=False)
        _make_failure(client, failure_deps, resolved=True)

        data = client.get("/api/failure-records/summary").json()
        assert data["total"] == 3
        assert data["resolved_count"] == 1
        assert data["open_count"] == 2
        assert data["total"] == data["resolved_count"] + data["open_count"]

    def test_summary_by_type(self, client, failure_deps):
        _make_failure(client, failure_deps, failure_type="test_failure")
        _make_failure(client, failure_deps, failure_type="test_failure")
        _make_failure(client, failure_deps, failure_type="build_failure")

        data = client.get("/api/failure-records/summary").json()
        by_type = {entry["failure_type"]: entry["count"] for entry in data["by_type"]}
        assert by_type["test_failure"] == 2
        assert by_type["build_failure"] == 1

    def test_summary_by_agent(self, client, failure_deps, make_agent):
        a2 = make_agent()
        _make_failure(client, failure_deps)
        _make_failure(client, failure_deps)
        _make_failure(client, failure_deps, agent_id=a2["id"])

        data = client.get("/api/failure-records/summary").json()
        by_agent = {entry["agent_id"]: entry["count"] for entry in data["by_agent"]}
        assert by_agent[failure_deps["agent"]["id"]] == 2
        assert by_agent[a2["id"]] == 1

    def test_summary_by_sprint(self, client, failure_deps, make_sprint):
        s2 = make_sprint(project_id=failure_deps["project"]["id"])
        _make_failure(client, failure_deps)
        _make_failure(client, failure_deps, sprint_id=s2["id"])

        data = client.get("/api/failure-records/summary").json()
        by_sprint = {entry["sprint_id"]: entry["count"] for entry in data["by_sprint"]}
        assert by_sprint[failure_deps["sprint"]["id"]] == 1
        assert by_sprint[s2["id"]] == 1

    def test_summary_filter_by_project_id(self, client, failure_deps, make_project, make_sprint, make_agent):
        _make_failure(client, failure_deps)
        p2 = make_project()
        s2 = make_sprint(project_id=p2["id"])
        a2 = make_agent()
        _make_failure(client, failure_deps, project_id=p2["id"], sprint_id=s2["id"], agent_id=a2["id"])

        data = client.get("/api/failure-records/summary", params={
            "project_id": failure_deps["project"]["id"],
        }).json()
        assert data["total"] == 1

    def test_summary_trend(self, client, failure_deps):
        _make_failure(client, failure_deps)
        _make_failure(client, failure_deps)

        data = client.get("/api/failure-records/summary").json()
        assert len(data["trend"]) >= 1
        entry = data["trend"][0]
        assert "date" in entry
        assert "count" in entry
        assert entry["count"] >= 2
