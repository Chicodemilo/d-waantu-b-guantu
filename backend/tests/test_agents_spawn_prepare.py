# Path: tests/test_agents_spawn_prepare.py
# File: test_agents_spawn_prepare.py
# Created: 2026-06-03
# Purpose: Tests for POST /api/agents/spawn-prepare (DWB-290)
# Caller: pytest
# Callees: POST /api/agents/spawn-prepare
# Data In: Factory projects/agents, instructions, optional scratchpad
# Data Out: Assertions on markdown sections and error semantics
# Last Modified: 2026-06-04


class TestSpawnPrepareHappyPath:
    def test_assembles_three_markdown_sections(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SP1", "name": "SpawnPrep One",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "sp1-pixel",
        })

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "frontend-worker", "name": "Pixel", "project_prefix": "SP1",
        })
        assert r.status_code == 200
        body = r.json()

        assert body["identity_prompt"].startswith("## Identity")
        assert "name: Pixel" in body["identity_prompt"]
        assert "role: frontend-worker" in body["identity_prompt"]
        assert "project: SP1" in body["identity_prompt"]
        assert "/SP1/Pixel/" in body["identity_prompt"]

        assert body["scratchpad_excerpt"].startswith("## Recent Scratchpad")
        assert "(no entries yet)" in body["scratchpad_excerpt"]

        assert body["boundary_rules"].startswith("## Boundary Rules")
        assert "(no boundary rules)" in body["boundary_rules"]

    def test_scratchpad_content_inlined_when_file_exists(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SP2", "name": "Two", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Sage",
            "role": "tester", "api_key": "sp2-sage",
        })
        memory_dir = tmp_path / ".dwb/memory/SP2/Sage"
        memory_dir.mkdir(parents=True, exist_ok=True)  # auto-scaffold may have created it
        # DWB-401: the excerpt reads memory.md.
        (memory_dir / "memory.md").write_text(
            "## 2026-06-03T12:00:00\nrepro confirmed via curl\n"
        )

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Sage", "project_prefix": "SP2",
        })
        body = r.json()
        assert "## Recent Scratchpad" in body["scratchpad_excerpt"]
        assert "repro confirmed" in body["scratchpad_excerpt"]
        # (no entries yet) sentinel must not appear when content is present
        assert "(no entries yet)" not in body["scratchpad_excerpt"]

    def test_boundary_rules_include_global_project_and_agent(self, client, tmp_path):
        """boundary_rules matches identify's scope filter: global + project + agent."""
        project = client.post("/api/projects", json={
            "prefix": "SP3", "name": "Three", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Devin",
            "role": "backend-worker", "api_key": "sp3-devin",
        }).json()
        client.post("/api/instructions", json={
            "scope": "global", "title": "G-RULE", "body": "global body",
        })
        client.post("/api/instructions", json={
            "scope": "project", "project_id": project["id"],
            "title": "P-RULE", "body": "project body",
        })
        client.post("/api/instructions", json={
            "scope": "agent", "agent_id": agent["id"],
            "title": "A-RULE", "body": "agent body",
        })

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Devin", "project_prefix": "SP3",
        })
        body = r.json()
        rules = body["boundary_rules"]
        assert "G-RULE" in rules
        assert "P-RULE" in rules
        assert "A-RULE" in rules

    def test_boundary_rules_exclude_other_projects(self, client, tmp_path):
        """A project-scoped rule on project B must not bleed into project A's spawn-prepare."""
        proj_a = client.post("/api/projects", json={
            "prefix": "SP3A", "name": "A", "repo_path": str(tmp_path / "a"),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "SP3B", "name": "B", "repo_path": str(tmp_path / "b"),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj_a["id"], "name": "Devin",
            "role": "backend-worker", "api_key": "sp3a-devin",
        })
        client.post("/api/instructions", json={
            "scope": "project", "project_id": proj_b["id"],
            "title": "B-ONLY", "body": "should not leak",
        })

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Devin", "project_prefix": "SP3A",
        })
        assert "B-ONLY" not in r.json()["boundary_rules"]


class TestSpawnPrepareErrors:
    def test_404_when_project_prefix_unknown(self, client):
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Anyone", "project_prefix": "ZZZZZ",
        })
        assert r.status_code == 404

    def test_404_when_agent_missing(self, client, tmp_path):
        client.post("/api/projects", json={
            "prefix": "SPE", "name": "Empty", "repo_path": str(tmp_path),
        })
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Phantom", "project_prefix": "SPE",
        })
        assert r.status_code == 404

    def test_spawn_prepare_409_when_multiple_agents_same_name(self, db_session):
        """DWB-301: defensive branch in app/services/agent.py:244-245.

        Mirrors test_identify_409_when_multiple_agents_same_name. UNIQUE
        makes this unreachable via HTTP/inserts; we stub `db.scalars` for
        the Agent matches query to inject two rows and prove the
        ambiguous-match raise still fires.
        """
        import pytest

        from app.models.agent import Agent
        from app.models.project import Project
        from app.services.agent import IdentifyError, spawn_prepare_payload

        project = Project(prefix="S409", name="Spawn 409", repo_path="/tmp")
        db_session.add(project)
        db_session.flush()

        a1 = Agent(
            id=9101, project_id=project.id, name="Twin",
            role="backend-worker", api_key="sx1",
        )
        a2 = Agent(
            id=9102, project_id=project.id, name="Twin",
            role="backend-worker", api_key="sx2",
        )

        class _StubScalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        real_scalars = db_session.scalars

        def fake_scalars(stmt, *args, **kwargs):
            entity = getattr(stmt, "column_descriptions", [{}])[0].get("entity")
            if entity is Agent:
                return _StubScalars([a1, a2])
            return real_scalars(stmt, *args, **kwargs)

        db_session.scalars = fake_scalars
        try:
            with pytest.raises(IdentifyError) as excinfo:
                spawn_prepare_payload(
                    db_session,
                    role="backend-worker",
                    name="Twin",
                    project_prefix="S409",
                )
            assert excinfo.value.code == "ambiguous"
        finally:
            db_session.scalars = real_scalars
