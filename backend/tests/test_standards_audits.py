# Path: tests/test_standards_audits.py
# File: test_standards_audits.py
# Created: 2026-08-11 (DWB-014)
# Purpose: API tests for standards-audit create / list / detail, a large-payload
#          case (MEDIUMTEXT must not 500), and 4xx paths.
# Caller: pytest
# Callees: app (via TestClient), conftest factory fixtures
# Data In: HTTP requests
# Data Out: assertions
# Last Modified: 2026-08-11 (DWB-014)


def _audit_payload(project_id, **overrides):
    data = {
        "project_id": project_id,
        "pr_ref": "PR#42",
        "diff_range": "main...HEAD",
        "verdict": "pass",
        "violations": [
            {
                "rule": "headers",
                "file": "app/foo.py",
                "line": 1,
                "note": "missing header",
                "severity": "low",
            }
        ],
        "scorecard": [
            {"agent": "Barry", "delta": 2, "reason": "clean headers"}
        ],
        "summary": "1 minor violation, verdict pass.",
    }
    data.update(overrides)
    return data


class TestCreateStandardsAudit:
    def test_create_happy_path(self, client, make_project):
        project = make_project()
        r = client.post(
            "/api/standards-audits", json=_audit_payload(project["id"])
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["project_id"] == project["id"]
        assert body["pr_ref"] == "PR#42"
        assert body["verdict"] == "pass"
        assert body["violations"][0]["rule"] == "headers"
        assert body["scorecard"][0]["agent"] == "Barry"
        assert body["scorecard"][0]["delta"] == 2
        assert body["summary"].startswith("1 minor violation")
        assert body["triggered_by"] == "manual"
        assert "id" in body and body["id"] > 0

    def test_create_with_sprint_and_ticket(
        self, client, make_project, make_sprint, make_ticket
    ):
        project = make_project()
        sprint = make_sprint(project_id=project["id"])
        ticket = make_ticket(project_id=project["id"], sprint_id=sprint["id"])
        r = client.post(
            "/api/standards-audits",
            json=_audit_payload(
                project["id"],
                sprint_id=sprint["id"],
                ticket_id=ticket["id"],
                verdict="reject",
            ),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["sprint_id"] == sprint["id"]
        assert body["ticket_id"] == ticket["id"]
        assert body["verdict"] == "reject"

    def test_create_minimal_defaults(self, client, make_project):
        """violations/scorecard default to [] and are optional."""
        project = make_project()
        r = client.post(
            "/api/standards-audits",
            json={
                "project_id": project["id"],
                "pr_ref": "branch/x",
                "verdict": "pass",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["violations"] == []
        assert body["scorecard"] == []
        assert body["diff_range"] is None
        assert body["summary"] is None


class TestCreateStandardsAudit4xx:
    def test_missing_project(self, client):
        r = client.post(
            "/api/standards-audits", json=_audit_payload(999999)
        )
        assert r.status_code == 404

    def test_missing_sprint(self, client, make_project):
        project = make_project()
        r = client.post(
            "/api/standards-audits",
            json=_audit_payload(project["id"], sprint_id=999999),
        )
        assert r.status_code == 404

    def test_invalid_verdict(self, client, make_project):
        project = make_project()
        r = client.post(
            "/api/standards-audits",
            json=_audit_payload(project["id"], verdict="maybe"),
        )
        assert r.status_code == 422

    def test_missing_required_field(self, client, make_project):
        project = make_project()
        # pr_ref omitted.
        r = client.post(
            "/api/standards-audits",
            json={"project_id": project["id"], "verdict": "pass"},
        )
        assert r.status_code == 422


class TestListStandardsAudits:
    def test_list_filters_by_project(self, client, make_project):
        p1 = make_project()
        p2 = make_project()
        client.post("/api/standards-audits", json=_audit_payload(p1["id"]))
        client.post("/api/standards-audits", json=_audit_payload(p1["id"]))
        client.post("/api/standards-audits", json=_audit_payload(p2["id"]))

        r = client.get("/api/standards-audits", params={"project_id": p1["id"]})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        assert all(row["project_id"] == p1["id"] for row in rows)
        # List schema is slim - details excluded.
        assert "details" not in rows[0]

    def test_list_filters_by_sprint(self, client, make_project, make_sprint):
        project = make_project()
        sprint = make_sprint(project_id=project["id"])
        client.post(
            "/api/standards-audits",
            json=_audit_payload(project["id"], sprint_id=sprint["id"]),
        )
        client.post("/api/standards-audits", json=_audit_payload(project["id"]))

        r = client.get(
            "/api/standards-audits", params={"sprint_id": sprint["id"]}
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["sprint_id"] == sprint["id"]


class TestGetStandardsAudit:
    def test_get_detail(self, client, make_project):
        project = make_project()
        created = client.post(
            "/api/standards-audits", json=_audit_payload(project["id"])
        ).json()
        r = client.get(f"/api/standards-audits/{created['id']}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == created["id"]
        # Detail schema includes details.
        assert "details" in body

    def test_get_missing_404(self, client):
        r = client.get("/api/standards-audits/999999")
        assert r.status_code == 404


class TestLargePayload:
    def test_large_details_does_not_500(self, client, make_project):
        """A large raw diff in `details` must be stored, not 500 (MEDIUMTEXT,
        mirroring the test_result.details DWB-308 fix)."""
        project = make_project()
        big_diff = "diff line\n" * 20000  # ~200KB, well over TEXT's 64KB cap
        r = client.post(
            "/api/standards-audits",
            json=_audit_payload(project["id"], details=big_diff),
        )
        assert r.status_code == 201, r.text
        audit_id = r.json()["id"]
        detail = client.get(f"/api/standards-audits/{audit_id}").json()
        assert detail["details"] == big_diff
