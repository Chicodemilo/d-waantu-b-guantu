# Path: tests/test_agent_memory_scaffold_dwb341.py
# File: test_agent_memory_scaffold_dwb341.py
# Created: 2026-06-10
# Purpose: Tests for DWB-341 auto-scaffold extensions: spawn-prepare repo_path 400, memory_dir in response, mid-session preservation, no-suffix invariant, cross-project isolation, project-level scaffold-agents endpoint
# Caller: pytest
# Callees: POST /api/agents, POST /api/agents/spawn-prepare, POST /api/projects/{id}/scaffold-agents, app.services.agent_memory.scaffold_agent_dir
# Data In: tmp_path filesystem, factory projects + agents
# Data Out: Assertions on dir layout, preservation invariants, error mapping
# Last Modified: 2026-06-10

"""DWB-341 coverage.

The DWB-293 scaffolder already auto-runs on POST /api/agents and is exposed
as a manual endpoint. DWB-341 adds:

  1. Auto-scaffold on POST /api/agents/spawn-prepare. Existing test file
     (test_agent_memory_scaffold.py) covers the create path; this file
     focuses on spawn-prepare invariants and the new convenience endpoint.

  2. spawn-prepare returns absolute `memory_dir` in the response body so
     callers don't have to rebuild the path.

  3. spawn-prepare returns HTTP 400 (not 404, not 500) when the project
     has no repo_path - the endpoint is precondition-checking that the
     scaffold target is well-defined before claiming success.

  4. **Mid-session respawn invariant.** Re-running spawn-prepare on an
     existing agent must NEVER suffix the dir name (no _1, _v2, etc) and
     must NEVER overwrite the agent-owned files (scratchpad.md,
     lessons.md, recent_sessions.md). identity.md MAY be regenerated.

  5. Cross-project: Archie_DWB on project DWB and Archie_CI on project CI
     get separate dirs (different project_prefix subpath), each preserved
     across spawns.

  6. New endpoint POST /api/projects/{id}/scaffold-agents walks all
     agents whose project_id matches and scaffolds each. Useful when the
     repo was cloned to a fresh checkout.
"""

from pathlib import Path


def _memory_dir(repo_path, prefix, name):
    return Path(repo_path) / ".claude" / "agents" / "memory" / prefix / name


# ---------------------------------------------------------------------------
# 1 + 2 + 3. spawn-prepare auto-scaffold, memory_dir in response, 400 on no repo
# ---------------------------------------------------------------------------


class TestSpawnPrepareScaffold:
    def test_spawn_prepare_returns_absolute_memory_dir(self, client, tmp_path):
        client.post("/api/projects", json={
            "prefix": "SPDA", "name": "Spawn Dir Absolute",
            "repo_path": str(tmp_path),
        })
        client.post("/api/agents", json={
            "project_id": client.get("/api/projects").json()[-1]["id"],
            "name": "Atlas", "role": "backend-worker", "api_key": "spda-1",
        })
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Atlas", "project_prefix": "SPDA",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "memory_dir" in body
        # Absolute path under the project's repo_path.
        assert body["memory_dir"].startswith(str(tmp_path))
        assert body["memory_dir"].endswith("/.claude/agents/memory/SPDA/Atlas/")

    def test_spawn_prepare_scaffolds_when_dir_missing(self, client, tmp_path):
        """Agent exists but dir was wiped (cloned-to-fresh-checkout case).
        spawn-prepare must rebuild the 4 files on demand."""
        proj = client.post("/api/projects", json={
            "prefix": "SPSC", "name": "Spawn Scaffold",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Vega",
            "role": "tester", "api_key": "spsc-1",
        })
        d = _memory_dir(tmp_path, "SPSC", "Vega")
        # Wipe the dir as if the repo was just cloned.
        import shutil
        shutil.rmtree(d)
        assert not d.exists()

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Vega", "project_prefix": "SPSC",
        })
        assert r.status_code == 200, r.text
        # All four files back.
        assert d.is_dir()
        assert (d / "identity.md").is_file()
        assert (d / "scratchpad.md").is_file()
        assert (d / "lessons.md").is_file()
        assert (d / "recent_sessions.md").is_file()

    def test_spawn_prepare_idempotent_on_existing_dir(self, client, tmp_path):
        """Calling spawn-prepare twice on the same agent is a clean no-op
        for agent-owned files. identity.md may be regenerated."""
        proj = client.post("/api/projects", json={
            "prefix": "SPID", "name": "Spawn Idempotent",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Iris",
            "role": "frontend-worker", "api_key": "spid-1",
        })
        d = _memory_dir(tmp_path, "SPID", "Iris")
        # Seed agent-owned content between the two spawn-prepare calls.
        (d / "scratchpad.md").write_text("## 2026-06-10\n- inflight work\n")
        (d / "lessons.md").write_text("## 2026-06-10\n- gotcha\n")
        (d / "recent_sessions.md").write_text("- 2026-06-10 session foo\n")

        # First spawn (post-seed).
        r1 = client.post("/api/agents/spawn-prepare", json={
            "role": "frontend-worker", "name": "Iris", "project_prefix": "SPID",
        })
        assert r1.status_code == 200
        # Second spawn (same agent, immediate respawn).
        r2 = client.post("/api/agents/spawn-prepare", json={
            "role": "frontend-worker", "name": "Iris", "project_prefix": "SPID",
        })
        assert r2.status_code == 200

        # Agent-owned content unchanged byte-for-byte.
        assert (d / "scratchpad.md").read_text() == "## 2026-06-10\n- inflight work\n"
        assert (d / "lessons.md").read_text() == "## 2026-06-10\n- gotcha\n"
        assert (d / "recent_sessions.md").read_text() == "- 2026-06-10 session foo\n"

    def test_spawn_prepare_returns_400_when_repo_path_missing(self, client):
        """No repo_path -> 400 (not 404, not 500). Clear message."""
        proj = client.post("/api/projects", json={
            "prefix": "SPNR", "name": "Spawn No Repo",
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Nomad",
            "role": "backend-worker", "api_key": "spnr-1",
        })
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Nomad", "project_prefix": "SPNR",
        })
        assert r.status_code == 400, r.text
        # Detail mentions repo_path so the operator knows what to fix.
        assert "repo_path" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. No-suffix invariant + mid-session respawn preservation
# ---------------------------------------------------------------------------


class TestNoSuffixInvariant:
    """The dir is keyed strictly on agent_name (system-wide unique).
    Respawning the same agent NEVER produces Pam_CI_1, Pam_CI_v2, etc."""

    def test_respawn_lands_in_same_dir_no_suffix(self, client, tmp_path):
        proj = client.post("/api/projects", json={
            "prefix": "NOSF", "name": "No Suffix",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Pam",
            "role": "pm", "api_key": "nosf-1",
        })

        # First spawn-prepare.
        r1 = client.post("/api/agents/spawn-prepare", json={
            "role": "pm", "name": "Pam", "project_prefix": "NOSF",
        })
        path1 = r1.json()["memory_dir"]

        # Second.
        r2 = client.post("/api/agents/spawn-prepare", json={
            "role": "pm", "name": "Pam", "project_prefix": "NOSF",
        })
        path2 = r2.json()["memory_dir"]

        # Third.
        r3 = client.post("/api/agents/spawn-prepare", json={
            "role": "pm", "name": "Pam", "project_prefix": "NOSF",
        })
        path3 = r3.json()["memory_dir"]

        # Identical path every time, no _1/_v2/_instanceN suffix.
        assert path1 == path2 == path3
        assert path1.endswith("/.claude/agents/memory/NOSF/Pam/")
        # And no sibling Pam_* dirs were created.
        memory_root = Path(tmp_path) / ".claude" / "agents" / "memory" / "NOSF"
        siblings = [p.name for p in memory_root.iterdir() if p.is_dir()]
        assert siblings == ["Pam"], f"unexpected siblings: {siblings}"

    def test_respawn_preserves_content_after_multiple_calls(
        self, client, tmp_path,
    ):
        """The strong form of preservation: write content, then call
        spawn-prepare many times in a row. Content must survive every call
        byte-for-byte."""
        proj = client.post("/api/projects", json={
            "prefix": "PRES", "name": "Preserve",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Memo",
            "role": "tester", "api_key": "pres-1",
        })
        d = _memory_dir(tmp_path, "PRES", "Memo")

        scratch_content = (
            "## 2026-06-10T12:00:00+00:00 - session A\n- bug fix\n"
            "## 2026-06-10T13:00:00+00:00 - session B\n- refactor\n"
        )
        (d / "scratchpad.md").write_text(scratch_content)
        (d / "lessons.md").write_text("## 2026-06-10\n- never trust mtime\n")
        (d / "recent_sessions.md").write_text(
            "- 2026-06-10T12:00:00+00:00 session A\n"
            "- 2026-06-10T13:00:00+00:00 session B\n"
        )

        for _ in range(5):
            r = client.post("/api/agents/spawn-prepare", json={
                "role": "tester", "name": "Memo", "project_prefix": "PRES",
            })
            assert r.status_code == 200

        assert (d / "scratchpad.md").read_text() == scratch_content
        assert (
            (d / "lessons.md").read_text()
            == "## 2026-06-10\n- never trust mtime\n"
        )
        assert (
            (d / "recent_sessions.md").read_text()
            == "- 2026-06-10T12:00:00+00:00 session A\n"
            "- 2026-06-10T13:00:00+00:00 session B\n"
        )


# ---------------------------------------------------------------------------
# 5. Cross-project isolation
# ---------------------------------------------------------------------------


class TestCrossProjectIsolation:
    """Two agents named in the Archie_<prefix> pattern on two projects get
    independent dirs and each survives respawn without bleeding into the other."""

    def test_archie_dwb_and_archie_ci_are_independent(self, client, tmp_path):
        dwb_repo = tmp_path / "dwb_repo"
        ci_repo = tmp_path / "ci_repo"
        dwb_repo.mkdir()
        ci_repo.mkdir()

        proj_dwb = client.post("/api/projects", json={
            "prefix": "XPDWB", "name": "Cross DWB",
            "repo_path": str(dwb_repo),
        }).json()
        proj_ci = client.post("/api/projects", json={
            "prefix": "XPCI", "name": "Cross CI",
            "repo_path": str(ci_repo),
        }).json()

        client.post("/api/agents", json={
            "project_id": proj_dwb["id"], "name": "Archie_XPDWB",
            "role": "team-lead", "api_key": "xp-dwb",
        })
        client.post("/api/agents", json={
            "project_id": proj_ci["id"], "name": "Archie_XPCI",
            "role": "team-lead", "api_key": "xp-ci",
        })

        d_dwb = _memory_dir(dwb_repo, "XPDWB", "Archie_XPDWB")
        d_ci = _memory_dir(ci_repo, "XPCI", "Archie_XPCI")
        # Seed distinct content on each.
        (d_dwb / "scratchpad.md").write_text("DWB session log\n")
        (d_ci / "scratchpad.md").write_text("CI session log\n")

        # Respawn each twice; verify no cross-pollination, no dir confusion.
        for _ in range(2):
            r = client.post("/api/agents/spawn-prepare", json={
                "role": "team-lead", "name": "Archie_XPDWB",
                "project_prefix": "XPDWB",
            })
            assert r.status_code == 200
            assert r.json()["memory_dir"] == str(d_dwb) + "/"

            r = client.post("/api/agents/spawn-prepare", json={
                "role": "team-lead", "name": "Archie_XPCI",
                "project_prefix": "XPCI",
            })
            assert r.status_code == 200
            assert r.json()["memory_dir"] == str(d_ci) + "/"

        # Content unmixed.
        assert (d_dwb / "scratchpad.md").read_text() == "DWB session log\n"
        assert (d_ci / "scratchpad.md").read_text() == "CI session log\n"

        # No cross-pollination: the DWB repo has no XPCI subtree, and vice versa.
        assert not (dwb_repo / ".claude/agents/memory/XPCI").exists()
        assert not (ci_repo / ".claude/agents/memory/XPDWB").exists()


# ---------------------------------------------------------------------------
# 6. POST /api/projects/{id}/scaffold-agents
# ---------------------------------------------------------------------------


class TestProjectScaffoldAgentsEndpoint:
    def test_scaffolds_all_agents_in_project(self, client, tmp_path):
        proj = client.post("/api/projects", json={
            "prefix": "PSCF", "name": "Project Scaffold",
            "repo_path": str(tmp_path),
        }).json()
        for name in ("Alice", "Bob", "Cara"):
            client.post("/api/agents", json={
                "project_id": proj["id"], "name": name,
                "role": "backend-worker", "api_key": f"pscf-{name}",
            })
        # Wipe the on-disk dirs to simulate a fresh repo clone.
        import shutil
        memory_root = tmp_path / ".claude/agents/memory/PSCF"
        if memory_root.exists():
            shutil.rmtree(memory_root)

        r = client.post(f"/api/projects/{proj['id']}/scaffold-agents")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == proj["id"]
        assert body["project_prefix"] == "PSCF"
        assert body["agent_count"] == 3
        scaffolded_names = {row["agent_name"] for row in body["scaffolded"]}
        assert scaffolded_names == {"Alice", "Bob", "Cara"}

        for name in ("Alice", "Bob", "Cara"):
            d = _memory_dir(tmp_path, "PSCF", name)
            assert d.is_dir()
            assert (d / "identity.md").is_file()
            assert (d / "scratchpad.md").is_file()
            assert (d / "lessons.md").is_file()
            assert (d / "recent_sessions.md").is_file()

    def test_scaffold_agents_preserves_existing_content(self, client, tmp_path):
        """Re-running scaffold-agents on a fully-populated project is a
        no-op for agent-owned files."""
        proj = client.post("/api/projects", json={
            "prefix": "PSPR", "name": "Project Preserve",
            "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": proj["id"], "name": "Keep",
            "role": "tester", "api_key": "pspr-1",
        })
        d = _memory_dir(tmp_path, "PSPR", "Keep")
        (d / "scratchpad.md").write_text("important inflight work\n")

        r = client.post(f"/api/projects/{proj['id']}/scaffold-agents")
        assert r.status_code == 200
        assert (d / "scratchpad.md").read_text() == "important inflight work\n"

    def test_404_when_project_missing(self, client):
        r = client.post("/api/projects/999999/scaffold-agents")
        assert r.status_code == 404

    def test_400_when_project_has_no_repo_path(self, client):
        proj = client.post("/api/projects", json={
            "prefix": "PSNR", "name": "Project No Repo",
        }).json()
        r = client.post(f"/api/projects/{proj['id']}/scaffold-agents")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"].lower()

    def test_walks_zero_agents_returns_empty_list(self, client, tmp_path):
        """Project with no agents is not an error - just an empty scaffold."""
        proj = client.post("/api/projects", json={
            "prefix": "PSZA", "name": "Project Zero Agents",
            "repo_path": str(tmp_path),
        }).json()
        r = client.post(f"/api/projects/{proj['id']}/scaffold-agents")
        assert r.status_code == 200
        body = r.json()
        assert body["agent_count"] == 0
        assert body["scaffolded"] == []
