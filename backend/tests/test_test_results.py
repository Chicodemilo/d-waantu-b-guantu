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
