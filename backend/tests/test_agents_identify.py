# Path: tests/test_agents_identify.py
# File: test_agents_identify.py
# Created: 2026-06-03
# Purpose: Tests for POST /api/agents/identify (DWB-289)
# Caller: pytest
# Callees: POST /api/agents/identify
# Data In: Factory projects/agents, optional scratchpad/instruction fixtures
# Data Out: Assertions on response shape and status codes
# Last Modified: 2026-06-04


class TestIdentifyHappyPath:
    def test_returns_agent_and_memory_dir(self, client, tmp_path, make_project):
        project = client.post("/api/projects", json={
            "prefix": "IDP1",
            "name": "Identify Project",
            "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Pixel",
            "role": "frontend-worker",
            "api_key": f"id-key-{project['id']}",
        }).json()

        r = client.post("/api/agents/identify", json={
            "role": "frontend-worker",
            "name": "Pixel",
            "project_prefix": "IDP1",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["agent_id"] == agent["id"]
        assert body["name"] == "Pixel"
        assert body["role"] == "frontend-worker"
        assert body["project_id"] == project["id"]
        assert body["project_prefix"] == "IDP1"
        assert body["memory_dir"].endswith("/.dwb/memory/IDP1/Pixel/")
        assert body["memory_dir"].startswith(str(tmp_path))
        assert body["scratchpad_excerpt"] == ""
        assert body["instructions"] == []

    def test_reads_scratchpad_when_present(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "IDP2",
            "name": "Scratchpad Project",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Sage",
            "role": "tester",
            "api_key": f"id-key-{project['id']}",
        })
        memory_dir = tmp_path / ".dwb/memory/IDP2/Sage"
        memory_dir.mkdir(parents=True, exist_ok=True)  # auto-scaffold may have created it
        # DWB-401: the excerpt reads memory.md.
        (memory_dir / "memory.md").write_text("## 2026-06-03T12:00:00\nfound the bug.\n")

        r = client.post("/api/agents/identify", json={
            "role": "tester",
            "name": "Sage",
            "project_prefix": "IDP2",
        })
        assert r.status_code == 200
        assert "found the bug" in r.json()["scratchpad_excerpt"]

    def test_returns_visible_instructions(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "IDP3",
            "name": "Instructions Project",
            "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Devin",
            "role": "backend-worker",
            "api_key": f"id-key-{project['id']}",
        }).json()

        # Three instructions: global, project, agent
        client.post("/api/instructions", json={
            "scope": "global", "title": "global rule", "body": "apply everywhere",
        })
        client.post("/api/instructions", json={
            "scope": "project", "project_id": project["id"],
            "title": "project rule", "body": "apply on this project",
        })
        client.post("/api/instructions", json={
            "scope": "agent", "agent_id": agent["id"],
            "title": "agent rule", "body": "apply for Devin",
        })

        r = client.post("/api/agents/identify", json={
            "role": "backend-worker",
            "name": "Devin",
            "project_prefix": "IDP3",
        })
        assert r.status_code == 200
        titles = {i["title"] for i in r.json()["instructions"]}
        assert titles == {"global rule", "project rule", "agent rule"}

    def test_excludes_other_projects_and_agents(self, client, tmp_path):
        # DWB-315: agents.name is globally unique. Two agents with the
        # same short name on different projects must now be stored with
        # the suffixed form (Bolt_IDPA, Bolt_IDPB). The identify endpoint
        # still accepts the short name `Bolt` + project_prefix and
        # resolves to the right project's row.
        proj_a = client.post("/api/projects", json={
            "prefix": "IDPA", "name": "A", "repo_path": str(tmp_path / "a"),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "IDPB", "name": "B", "repo_path": str(tmp_path / "b"),
        }).json()
        agent_a = client.post("/api/agents", json={
            "project_id": proj_a["id"], "name": "Bolt_IDPA",
            "role": "system-ops", "api_key": "id-ab",
        }).json()
        client.post("/api/agents", json={
            "project_id": proj_b["id"], "name": "Bolt_IDPB",
            "role": "backend-worker", "api_key": "id-bb",
        })
        # project-scoped instruction on B; agent-scoped on A's Bolt
        client.post("/api/instructions", json={
            "scope": "project", "project_id": proj_b["id"],
            "title": "B-only", "body": "B rule",
        })
        client.post("/api/instructions", json={
            "scope": "agent", "agent_id": agent_a["id"],
            "title": "A-Bolt", "body": "A rule",
        })

        # Short-name identify on project A resolves to Bolt_IDPA.
        r = client.post("/api/agents/identify", json={
            "role": "system-ops", "name": "Bolt", "project_prefix": "IDPA",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] == proj_a["id"]
        assert body["name"] == "Bolt_IDPA"
        titles = {i["title"] for i in body["instructions"]}
        assert "A-Bolt" in titles
        assert "B-only" not in titles


class TestIdentifyLazyScaffold:
    def test_identify_creates_memory_dir_on_first_call(self, client, tmp_path):
        """Pre-DWB-293 agents have no on-disk memory_dir. The first identify
        call must scaffold it, then read scratchpad_excerpt from a real dir."""
        from pathlib import Path
        from shutil import rmtree

        project = client.post("/api/projects", json={
            "prefix": "LZ1", "name": "Lazy One", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "lz1-pixel",
        })
        # Simulate "agent created before DWB-293" by removing the scaffolded dir.
        memory_dir = Path(tmp_path) / ".dwb/memory/LZ1/Pixel"
        assert memory_dir.is_dir()  # auto-scaffold ran on create
        rmtree(memory_dir)
        assert not memory_dir.exists()

        r = client.post("/api/agents/identify", json={
            "role": "frontend-worker", "name": "Pixel", "project_prefix": "LZ1",
        })
        assert r.status_code == 200
        # Lazy scaffold should have re-created the dir + identity.md
        assert memory_dir.is_dir()
        assert (memory_dir / "identity.md").is_file()
        assert "**name:** Pixel" in (memory_dir / "identity.md").read_text()

    def test_identify_does_not_clobber_existing_memory(self, client, tmp_path):
        """If memory.md already has content, lazy scaffold must not overwrite."""
        from pathlib import Path

        project = client.post("/api/projects", json={
            "prefix": "LZ2", "name": "Lazy Two", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Sage",
            "role": "tester", "api_key": "lz2-sage",
        })
        memory_dir = Path(tmp_path) / ".dwb/memory/LZ2/Sage"
        # DWB-401: single memory.md holds both notes and lessons.
        (memory_dir / "memory.md").write_text(
            "## 2026-06-03\n- precious note\n- precious lesson\n"
        )
        # Delete identity.md so identify has to refresh it
        (memory_dir / "identity.md").unlink()

        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Sage", "project_prefix": "LZ2",
        })
        assert r.status_code == 200
        # The critical assertion: precious content survived any side effect.
        assert "precious note" in (memory_dir / "memory.md").read_text()
        assert "precious lesson" in (memory_dir / "memory.md").read_text()


class TestIdentifyErrors:
    def test_404_when_project_prefix_unknown(self, client):
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Anyone", "project_prefix": "NONEXIST",
        })
        assert r.status_code == 404
        assert "project prefix" in r.json()["detail"]

    def test_404_when_agent_name_missing(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "IDPE", "name": "Empty", "repo_path": str(tmp_path),
        }).json()
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Ghost", "project_prefix": "IDPE",
        })
        assert r.status_code == 404
        assert "Ghost" in r.json()["detail"]

    def test_role_mismatch_still_returns_agent(self, client, tmp_path):
        """Role is informational, not a filter — caller may assert their own role."""
        project = client.post("/api/projects", json={
            "prefix": "IDPR", "name": "Role Mismatch", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pam",
            "role": "pm", "api_key": "id-pr",
        })
        r = client.post("/api/agents/identify", json={
            "role": "tester",  # asserted role doesn't match db row
            "name": "Pam", "project_prefix": "IDPR",
        })
        assert r.status_code == 200
        assert r.json()["role"] == "pm"  # DB row's role wins in the response

    def test_identify_409_when_multiple_agents_same_name(self, db_session):
        """DWB-301: defensive branch in app/services/agent.py:111-114.

        UNIQUE(project_id, name) (DWB-287) makes this unreachable via the
        public API, so we exercise the service layer with a stub Session
        that yields two matches — proving the ambiguous-match raise still
        fires if data integrity ever drifts.
        """
        import pytest

        from app.models.agent import Agent
        from app.models.project import Project
        from app.services.agent import IdentifyError, identify_agent

        # Real project written through the test session so we can fetch it
        # with select(Project).where(...) inside the service.
        project = Project(prefix="A409", name="Ambiguous", repo_path="/tmp")
        db_session.add(project)
        db_session.flush()

        # Two in-memory Agent rows with the same (project_id, name) — never
        # actually inserted (the UNIQUE would block them), but enough to
        # populate the matches list once we monkey-patch scalars below.
        a1 = Agent(
            id=9001, project_id=project.id, name="Twin",
            role="backend-worker", api_key="x1",
        )
        a2 = Agent(
            id=9002, project_id=project.id, name="Twin",
            role="backend-worker", api_key="x2",
        )

        class _StubScalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        real_scalars = db_session.scalars

        def fake_scalars(stmt, *args, **kwargs):
            # Intercept the Agent matches query; pass everything else through.
            entity = getattr(stmt, "column_descriptions", [{}])[0].get("entity")
            if entity is Agent:
                return _StubScalars([a1, a2])
            return real_scalars(stmt, *args, **kwargs)

        db_session.scalars = fake_scalars
        try:
            with pytest.raises(IdentifyError) as excinfo:
                identify_agent(
                    db_session,
                    role="backend-worker",
                    name="Twin",
                    project_prefix="A409",
                )
            assert excinfo.value.code == "ambiguous"
        finally:
            db_session.scalars = real_scalars

    def test_identify_scratchpad_excerpt_truncates_to_cap(self, client, tmp_path):
        """DWB-301: `_read_scratchpad` returns `data[-N:]` where N=2000.

        With a scratchpad larger than the cap, the excerpt must equal the
        TAIL bytes of the file, not the head — proving we're slicing from
        the end (most recent content).
        """
        from app.services.agent import _SCRATCHPAD_EXCERPT_BYTES

        cap = _SCRATCHPAD_EXCERPT_BYTES
        assert cap == 2000  # contract pin — bump if cap changes

        project = client.post("/api/projects", json={
            "prefix": "TRUN", "name": "Truncate Project",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Long",
            "role": "tester", "api_key": "trun-long",
        })
        memory_dir = tmp_path / ".dwb/memory/TRUN/Long"
        memory_dir.mkdir(parents=True, exist_ok=True)
        # Layout (each section is intentionally >cap bytes so the tail slice
        # lands inside the second section, not in the head sentinel zone):
        #   head = "HEAD" + h*(cap+500) + "BOUNDARY"   → cap+512 bytes
        #   tail = "TAIL" + t*(cap+100) + "ENDMARKER"  → cap+113 bytes
        # data[-cap:] therefore starts inside the t-run of `tail`; the
        # "TAIL"/"BOUNDARY"/"HEAD" sentinels are guaranteed to be sliced off.
        head = "HEAD" + ("h" * (cap + 500)) + "BOUNDARY"
        tail = "TAIL" + ("t" * (cap + 100)) + "ENDMARKER"
        # DWB-401: the excerpt reads memory.md.
        (memory_dir / "memory.md").write_text(head + tail, encoding="utf-8")
        # Sanity: the combined file is well bigger than the cap.
        assert len(head + tail) > 2 * cap

        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Long", "project_prefix": "TRUN",
        })
        assert r.status_code == 200
        excerpt = r.json()["scratchpad_excerpt"]

        # 1) Length is exactly the cap.
        assert len(excerpt) == cap, (
            f"excerpt should be exactly {cap} bytes, got {len(excerpt)}"
        )
        # 2) Tail content survives (last bytes preserved).
        assert excerpt.endswith("ENDMARKER")
        # 3) Head + boundary sentinels are cut off (proving we slice from
        #    the END, not the head).
        assert "HEAD" not in excerpt
        assert "BOUNDARY" not in excerpt
        assert "TAIL" not in excerpt


class TestIdentifyDWB315SuffixedName:
    """DWB-315: agents.name is globally unique; fixed-role agents are
    stored with `_<PROJECT_PREFIX>` suffix. The identify endpoint must
    still accept either the short name (spawn-brief style) or the full
    suffixed name (post-rename style)."""

    def test_short_name_resolves_to_suffixed_db_row(self, client, tmp_path):
        """Spawn briefs send {name: 'Archie', project_prefix: 'DWB315A'};
        the DB row stores name='Archie_DWB315A'. Identify must match."""
        project = client.post("/api/projects", json={
            "prefix": "S315A", "name": "Short→Suffix",
            "repo_path": str(tmp_path),
        }).json()
        # Create the agent with the suffixed name — mimics the post-migration
        # state where Archie/Pam/Mona were renamed.
        client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Archie_S315A",
            "role": "team-lead",
            "api_key": "s315a-archie",
        })

        # Spawn-brief calls identify with the short name.
        r = client.post("/api/agents/identify", json={
            "role": "team-lead", "name": "Archie", "project_prefix": "S315A",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Archie_S315A"
        assert body["role"] == "team-lead"

    def test_full_suffixed_name_also_works(self, client, tmp_path):
        """Callers that already know the full name (or have migrated their
        own briefs) get the same row back via direct match."""
        project = client.post("/api/projects", json={
            "prefix": "S315B", "name": "Full Match",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Pam_S315B",
            "role": "pm",
            "api_key": "s315b-pam",
        })

        r = client.post("/api/agents/identify", json={
            "role": "pm", "name": "Pam_S315B", "project_prefix": "S315B",
        })
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Pam_S315B"

    def test_short_name_doesnt_leak_across_projects(self, client, tmp_path):
        """A short-name identify must scope to the requested project — even
        with global UNIQUE(name), the project_id filter still wins. Two
        projects, two Archies; identify on project A returns the A row."""
        proj_a = client.post("/api/projects", json={
            "prefix": "S315C", "name": "Project A",
            "repo_path": str(tmp_path / "a"),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "S315D", "name": "Project B",
            "repo_path": str(tmp_path / "b"),
        }).json()
        # Two Archies with distinct suffixed names — both legal post-DWB-315.
        client.post("/api/agents", json={
            "project_id": proj_a["id"], "name": "Archie_S315C",
            "role": "team-lead", "api_key": "s315c-archie",
        })
        client.post("/api/agents", json={
            "project_id": proj_b["id"], "name": "Archie_S315D",
            "role": "team-lead", "api_key": "s315d-archie",
        })

        # Short-name identify on project A → A's Archie only.
        r = client.post("/api/agents/identify", json={
            "role": "team-lead", "name": "Archie", "project_prefix": "S315C",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Archie_S315C"

    def test_unknown_short_name_still_returns_404(self, client, tmp_path):
        """If neither the short name nor the suffixed form match anything,
        the endpoint must still return agent_not_found."""
        client.post("/api/projects", json={
            "prefix": "S315E", "name": "Empty Roster",
            "repo_path": str(tmp_path),
        })
        r = client.post("/api/agents/identify", json={
            "role": "team-lead", "name": "NoSuchAgent",
            "project_prefix": "S315E",
        })
        assert r.status_code == 404
