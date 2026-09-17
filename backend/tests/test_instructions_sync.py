# Path:          tests/test_instructions_sync.py
# File:          test_instructions_sync.py
# Created:       2026-03-28
# Purpose:       Tests for instruction sync-check and sync endpoints
# Caller:        pytest
# Callees:       GET /api/instructions/sync-check, POST /api/instructions/sync
# Data In:       Factory-created instructions via conftest fixtures
# Data Out:      Assertions on sync status and instruction state
# Last Modified: 2026-09-17 (DWB-575: source_readable/source_error response
#   fields; a missing memory source must not read as a clean green)

"""Tests for /api/instructions sync-check and sync endpoints."""

from app.services import sync_check


class TestSyncCheck:
    def test_sync_check_returns_200(self, client):
        r = client.get("/api/instructions/sync-check")
        assert r.status_code == 200

    def test_sync_check_response_shape(self, client):
        data = client.get("/api/instructions/sync-check").json()
        assert "matched" in data
        assert "memory_only" in data
        assert "db_only" in data
        assert "in_sync" in data
        assert "source_readable" in data
        assert "source_error" in data
        assert isinstance(data["matched"], list)
        assert isinstance(data["memory_only"], list)
        assert isinstance(data["db_only"], list)
        assert isinstance(data["in_sync"], bool)
        assert isinstance(data["source_readable"], bool)

    def test_sync_check_db_only_includes_instructions(self, client, make_instruction):
        inst = make_instruction(scope="global", title="DB Only Instruction")
        data = client.get("/api/instructions/sync-check").json()
        db_only_ids = [d["id"] for d in data["db_only"]]
        assert inst["id"] in db_only_ids

    def test_missing_memory_source_is_not_a_clean_green(self, client, monkeypatch, tmp_path):
        """DWB-575 AC 2/3: with the source directory absent, the response
        must not be a clean green. Before the fix this returned
        {in_sync: True, memory_only: [], ...} having read nothing."""
        monkeypatch.setattr(sync_check, "MEMORY_DIR", tmp_path / "does-not-exist")
        r = client.get("/api/instructions/sync-check")
        assert r.status_code == 200
        data = r.json()
        assert data["source_readable"] is False
        assert data["source_error"] is not None
        assert data["in_sync"] is False
        assert data["memory_only"] == []

    def test_readable_empty_source_is_a_genuine_green(self, client, monkeypatch, tmp_path):
        """The legitimate counterpart: a source that exists, was read, and
        really has nothing pending IS in_sync (source_readable True)."""
        empty_dir = tmp_path / "memory"
        empty_dir.mkdir()
        monkeypatch.setattr(sync_check, "MEMORY_DIR", empty_dir)
        data = client.get("/api/instructions/sync-check").json()
        assert data["source_readable"] is True
        assert data["source_error"] is None
        assert data["in_sync"] is True


class TestSync:
    def test_sync_returns_201(self, client):
        r = client.post("/api/instructions/sync")
        assert r.status_code == 201
        assert isinstance(r.json(), list)

    def test_missing_memory_source_returns_400_not_empty_list(
        self, client, monkeypatch, tmp_path
    ):
        """DWB-575 AC 4: the write path must not treat an unreadable source
        as "nothing to sync" (a 201 with an empty body looks identical to a
        real successful no-op sync)."""
        monkeypatch.setattr(sync_check, "MEMORY_DIR", tmp_path / "does-not-exist")
        r = client.post("/api/instructions/sync")
        assert r.status_code == 400
        assert "sync" in r.json()["detail"].lower()


class TestInstructionsCRUD:
    def test_list_returns_200(self, client):
        r = client.get("/api/instructions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_returns_201(self, client):
        r = client.post("/api/instructions", json={
            "scope": "global",
            "title": "Test Global Instruction",
            "body": "Do the thing.",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["scope"] == "global"
        assert data["title"] == "Test Global Instruction"
        assert data["body"] == "Do the thing."

    def test_create_project_scoped(self, client, make_project):
        project = make_project()
        r = client.post("/api/instructions", json={
            "scope": "project",
            "project_id": project["id"],
            "title": "Project Instruction",
            "body": "Project specific.",
        })
        assert r.status_code == 201
        assert r.json()["project_id"] == project["id"]
        assert r.json()["scope"] == "project"

    def test_get_returns_200(self, client, make_instruction):
        inst = make_instruction()
        r = client.get(f"/api/instructions/{inst['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == inst["id"]

    def test_get_response_shape(self, client, make_instruction):
        inst = make_instruction()
        data = client.get(f"/api/instructions/{inst['id']}").json()
        expected_keys = {
            "id", "scope", "project_id", "agent_id",
            "title", "body", "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/instructions/999999")
        assert r.status_code == 404

    def test_patch_updates_fields(self, client, make_instruction):
        inst = make_instruction()
        r = client.patch(f"/api/instructions/{inst['id']}", json={
            "title": "Updated Title",
            "body": "Updated body.",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"
        assert r.json()["body"] == "Updated body."

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/instructions/999999", json={"title": "Nope"})
        assert r.status_code == 404

    def test_delete_returns_204(self, client, make_instruction):
        inst = make_instruction()
        r = client.delete(f"/api/instructions/{inst['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_instruction):
        inst = make_instruction()
        client.delete(f"/api/instructions/{inst['id']}")
        r = client.get(f"/api/instructions/{inst['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/instructions/999999")
        assert r.status_code == 404

    def test_filter_by_scope(self, client, make_instruction):
        make_instruction(scope="global")
        make_instruction(scope="global")

        filtered = client.get("/api/instructions", params={"scope": "global"}).json()
        assert all(i["scope"] == "global" for i in filtered)

    def test_filter_by_project_id(self, client, make_project, make_instruction):
        p1 = make_project()
        p2 = make_project()
        make_instruction(scope="project", project_id=p1["id"])
        make_instruction(scope="project", project_id=p2["id"])

        filtered = client.get("/api/instructions", params={"project_id": p1["id"]}).json()
        assert all(i["project_id"] == p1["id"] for i in filtered)
