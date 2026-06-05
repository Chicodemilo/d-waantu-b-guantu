# Path:          tests/test_test_results.py
# File:          test_test_results.py
# Created:       2026-03-28
# Purpose:       CRUD + filtering tests for /api/test-results
# Caller:        pytest
# Callees:       GET/POST /api/test-results, GET /api/test-results/:id
# Data In:       Factory-created projects via conftest fixtures
# Data Out:      Assertions on HTTP status codes and JSON response shapes
# Last Modified: 2026-03-29

"""Tests for /api/test-results CRUD and filtering."""


class TestListTestResults:
    def test_list_returns_200(self, client):
        r = client.get("/api/test-results")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_result(self, client, make_test_result):
        result = make_test_result()
        results = client.get("/api/test-results").json()
        ids = [tr["id"] for tr in results]
        assert result["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_test_result):
        p1 = make_project()
        p2 = make_project()
        tr1 = make_test_result(project_id=p1["id"])
        tr2 = make_test_result(project_id=p2["id"])

        filtered = client.get("/api/test-results", params={"project_id": p1["id"]}).json()
        ids = [tr["id"] for tr in filtered]
        assert tr1["id"] in ids
        assert tr2["id"] not in ids

    def test_filter_by_suite(self, client, make_test_result):
        make_test_result(suite="backend")
        make_test_result(suite="frontend")

        filtered = client.get("/api/test-results", params={"suite": "backend"}).json()
        assert all(tr["suite"] == "backend" for tr in filtered)

    def test_filter_by_status(self, client, make_test_result):
        make_test_result(status="passed")
        make_test_result(status="failed")

        filtered = client.get("/api/test-results", params={"status": "passed"}).json()
        assert all(tr["status"] == "passed" for tr in filtered)

    def test_limit_param(self, client, make_project, make_test_result):
        proj = make_project()
        for _ in range(5):
            make_test_result(project_id=proj["id"])

        limited = client.get("/api/test-results", params={"project_id": proj["id"], "limit": 2}).json()
        assert len(limited) <= 2


class TestGetTestResult:
    def test_get_returns_200(self, client, make_test_result):
        result = make_test_result()
        r = client.get(f"/api/test-results/{result['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == result["id"]

    def test_get_response_shape(self, client, make_test_result):
        result = make_test_result()
        data = client.get(f"/api/test-results/{result['id']}").json()
        expected_keys = {
            "id", "project_id", "sprint_id", "ticket_id",
            "run_at", "suite", "total_tests",
            "passed", "failed", "skipped", "duration_seconds",
            "status", "details", "triggered_by", "triggered_context",
            "created_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/test-results/999999")
        assert r.status_code == 404


class TestCreateTestResult:
    def test_create_returns_201(self, client, make_project):
        project = make_project()
        r = client.post("/api/test-results", json={
            "project_id": project["id"],
            "suite": "backend",
            "total_tests": 20,
            "passed": 18,
            "failed": 2,
            "status": "failed",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["suite"] == "backend"
        assert data["passed"] == 18
        assert data["failed"] == 2
        assert data["status"] == "failed"

    def test_create_defaults(self, client, make_project):
        project = make_project()
        r = client.post("/api/test-results", json={
            "project_id": project["id"],
            "suite": "integration",
            "total_tests": 5,
            "passed": 5,
            "failed": 0,
            "status": "passed",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["skipped"] == 0
        assert data["duration_seconds"] == 0.0
        assert data["triggered_by"] == "manual"

    def test_create_with_details(self, client, make_project):
        project = make_project()
        r = client.post("/api/test-results", json={
            "project_id": project["id"],
            "suite": "backend",
            "total_tests": 1,
            "passed": 1,
            "failed": 0,
            "status": "passed",
            "details": '{"tests": [{"nodeid": "test_foo", "outcome": "passed"}]}',
            "triggered_by": "agent:tester",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["details"] is not None
        assert data["triggered_by"] == "agent:tester"


class TestLargePayload:
    """DWB-308 — gate-sized payload (per-test list + ~4KB tail) must POST cleanly.

    The TEXT column was 64KB; a 577-test run with full per-test data and the
    standard 4000-char raw_output_tail produced an ~85KB JSON blob and the
    POST returned HTTP 500 (Data too long for column 'details'). Column
    widened to MEDIUMTEXT in dwb308a4f2e91b.
    """

    def _build_large_details(self, n_tests: int, tail_chars: int) -> str:
        import json
        tests = [
            {
                "nodeid": (
                    f"tests/test_module_{i}.py::TestClass::"
                    f"test_function_with_a_long_descriptive_name_{i}"
                ),
                "outcome": "passed",
                "duration": 0.0234,
            }
            for i in range(n_tests)
        ]
        return json.dumps({"tests": tests, "raw_output_tail": "x" * tail_chars})

    def test_gate_sized_payload_posts_successfully(self, client, make_project):
        """Reproduce the DWB-308 failure mode: 600 per-test entries + 4000-char
        tail builds an ~85KB details blob that exceeds the old TEXT limit."""
        project = make_project()
        details = self._build_large_details(n_tests=600, tail_chars=4000)
        # Sanity: the payload IS over the old 64KB TEXT cap
        assert len(details) > 65_535, (
            f"test scenario should exceed TEXT cap; got {len(details)} bytes"
        )

        r = client.post("/api/test-results", json={
            "project_id": project["id"],
            "suite": "backend",
            "total_tests": 600,
            "passed": 600,
            "failed": 0,
            "status": "passed",
            "details": details,
            "triggered_by": "agent:tester",
        })
        assert r.status_code == 201, (
            f"POST should succeed after MEDIUMTEXT widening: "
            f"got {r.status_code} body={r.text[:300]}"
        )

    def test_large_details_round_trip(self, client, make_project):
        """Persisted details survive round-trip without truncation."""
        project = make_project()
        details = self._build_large_details(n_tests=600, tail_chars=4000)
        original_len = len(details)

        post = client.post("/api/test-results", json={
            "project_id": project["id"],
            "suite": "backend",
            "total_tests": 600,
            "passed": 600,
            "failed": 0,
            "status": "passed",
            "details": details,
        })
        assert post.status_code == 201
        row_id = post.json()["id"]

        fetched = client.get(f"/api/test-results/{row_id}").json()
        assert fetched["details"] is not None
        assert len(fetched["details"]) == original_len, (
            f"details truncated on round-trip: "
            f"sent {original_len} bytes, got back {len(fetched['details'])}"
        )


class TestDeleteTestResult:
    """DWB-310 — DELETE /api/test-results/{id} for orphan-row cleanup."""

    def test_delete_returns_204(self, client, make_test_result):
        result = make_test_result()
        r = client.delete(f"/api/test-results/{result['id']}")
        assert r.status_code == 204
        # Body MUST be empty on 204 per RFC 7230 — FastAPI's Response(204) handles this
        assert r.content == b""

    def test_delete_removes_the_row(self, client, make_test_result):
        result = make_test_result()
        client.delete(f"/api/test-results/{result['id']}")
        # Subsequent GET should be 404
        get_r = client.get(f"/api/test-results/{result['id']}")
        assert get_r.status_code == 404

    def test_delete_missing_returns_404(self, client):
        r = client.delete("/api/test-results/999999")
        assert r.status_code == 404

    def test_delete_does_not_remove_other_rows(self, client, make_test_result):
        keep = make_test_result()
        kill = make_test_result()
        client.delete(f"/api/test-results/{kill['id']}")
        # The other row survives
        r = client.get(f"/api/test-results/{keep['id']}")
        assert r.status_code == 200
