# Path: tests/test_agent_memory_scaffold.py
# File: test_agent_memory_scaffold.py
# Created: 2026-06-03
# Purpose: Tests for the agent_memory scaffolder service + auto-triggers (DWB-293)
# Caller: pytest
# Callees: app.services.agent_memory, POST /api/agents, POST /api/project-agents, POST /api/agents/{id}/scaffold-memory
# Data In: tmp_path filesystem, factory projects + agents
# Data Out: Assertions on directory layout, identity.md content, idempotency
# Last Modified: 2026-06-19

from pathlib import Path


def _memory_dir(repo_path, prefix, name):
    return Path(repo_path) / ".dwb" / "memory" / prefix / name


class TestScaffoldOnCreate:
    def test_create_agent_auto_scaffolds(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF1", "name": "Scaffold One", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "scf1-pixel",
        })

        d = _memory_dir(tmp_path, "SCF1", "Pixel")
        assert d.is_dir()
        # DWB-401: 2-file model.
        assert (d / "identity.md").is_file()
        assert (d / "memory.md").is_file()
        assert not (d / "scratchpad.md").exists()
        assert not (d / "lessons.md").exists()
        assert not (d / "recent_sessions.md").exists()

    def test_identity_md_carries_agent_facts(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF2", "name": "Scaffold Two", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Devin",
            "role": "backend-worker", "api_key": "scf2-devin",
            "description": "test agent",
        }).json()

        identity = (_memory_dir(tmp_path, "SCF2", "Devin") / "identity.md").read_text()
        assert f"**agent_id:** {agent['id']}" in identity
        assert "**name:** Devin" in identity
        assert "**role:** backend-worker" in identity
        assert "SCF2 (Scaffold Two)" in identity
        # Self-orientation block
        assert "## On Spawn - Read These First" in identity
        # ISO 8601 entry rule
        assert "## ISO 8601 entry rule" in identity


class TestScaffoldIdempotency:
    def test_memory_preserved_on_re_scaffold(self, client, tmp_path):
        # DWB-401: the single agent-owned memory.md is preserved on re-scaffold;
        # only identity.md is regenerated.
        project = client.post("/api/projects", json={
            "prefix": "SCF3", "name": "Scaffold Three", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Sage",
            "role": "tester", "api_key": "scf3-sage",
        }).json()

        d = _memory_dir(tmp_path, "SCF3", "Sage")
        # Agent-written content
        (d / "memory.md").write_text("## 2026-06-03 - session foo\n- did stuff\n- learned X\n")

        # Manual re-scaffold via the endpoint
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        body = r.json()
        # identity.md regenerated (refreshed)
        assert any(p.endswith("/identity.md") for p in body["refreshed"])
        # memory.md preserved
        assert any(p.endswith("/memory.md") for p in body["preserved"])

        # Content verified untouched
        assert "did stuff" in (d / "memory.md").read_text()
        assert "learned X" in (d / "memory.md").read_text()

    def test_identity_md_regenerated_on_re_scaffold(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF4", "name": "Scaffold Four", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Bolt",
            "role": "system-ops", "api_key": "scf4-bolt",
        }).json()

        d = _memory_dir(tmp_path, "SCF4", "Bolt")
        (d / "identity.md").write_text("OLD CONTENT")

        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        # OLD CONTENT must be gone (regenerated)
        assert "OLD CONTENT" not in (d / "identity.md").read_text()
        assert "**agent_id:**" in (d / "identity.md").read_text()


class TestScaffoldOnAssign:
    def test_project_agent_assign_triggers_scaffold(self, client, tmp_path):
        proj_a = client.post("/api/projects", json={
            "prefix": "SCF5A", "name": "A", "repo_path": str(tmp_path / "a"),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "SCF5B", "name": "B", "repo_path": str(tmp_path / "b"),
        }).json()
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)

        # Agent created on A → scaffold under A
        agent = client.post("/api/agents", json={
            "project_id": proj_a["id"], "name": "Pam",
            "role": "pm", "api_key": "scf5-pam",
        }).json()
        assert _memory_dir(tmp_path / "a", "SCF5A", "Pam").is_dir()

        # Assign to B → expected behavior: scaffold helper runs, but agents.project_id
        # is still A, so the scaffold under B does NOT happen (the function reads
        # agent.project_id, not the assignment's project_id). Documented behavior.
        client.post("/api/project-agents", json={
            "project_id": proj_b["id"], "agent_id": agent["id"],
        })
        # The A directory still exists (idempotent)
        assert _memory_dir(tmp_path / "a", "SCF5A", "Pam").is_dir()


class TestScaffoldErrors:
    def test_404_when_agent_missing(self, client):
        r = client.post("/api/agents/999999/scaffold-memory")
        assert r.status_code == 404

    def test_skipped_when_no_repo_path(self, client):
        # Project with no repo_path → scaffold returns skipped, not an error
        project = client.post("/api/projects", json={
            "prefix": "SCFNR", "name": "NoRepo",
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "NoRepoAgent",
            "role": "tester", "api_key": "scf-nr",
        }).json()
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        body = r.json()
        assert body["skipped"] is True
        assert "repo_path" in body["skip_reason"]


class TestIdentityStandingBlock:
    """DWB-431: identity.md opens with the agent's live scoring standing."""

    def _setup(self, client, tmp_path, prefix):
        project = client.post("/api/projects", json={
            "prefix": prefix, "name": f"Stand {prefix}", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": f"Bot{prefix}",
            "role": "backend-worker", "api_key": f"{prefix}-bot",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })
        return project, agent

    def test_identity_opens_with_best_standing(self, client, db_session, tmp_path):
        from app.models.score_event import ScoreSource, ScoreTriggerType
        from app.services import scoring as scoring_svc

        project, agent = self._setup(client, tmp_path, "STB1")
        scoring_svc.apply_score_event(
            db_session, project_id=project["id"], subject_agent_id=agent["id"],
            trigger_type=ScoreTriggerType.ticket_closed, delta=9,
            source=ScoreSource.auto, reason="x",
        )
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path, "STB1", "BotSTB1") / "identity.md").read_text()
        # The block is at the very TOP, before the Identity header.
        assert identity.startswith(">> YOUR STANDING: #1 of 1 on STB1  |  reputation 9")
        assert "The best agent on this team" in identity
        assert "# Identity - BotSTB1" in identity  # existing content intact

    def test_identity_unscored_line(self, client, tmp_path):
        project, agent = self._setup(client, tmp_path, "STB2")
        # no score events -> unscored
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path, "STB2", "BotSTB2") / "identity.md").read_text()
        assert identity.startswith(">> YOUR STANDING: #1 of 1 on STB2  |  reputation 0")
        assert "No score yet. Your first clean closes set your reputation." in identity

    def test_identity_still_generates_when_scoring_raises(self, client, tmp_path, monkeypatch):
        project, agent = self._setup(client, tmp_path, "STB3")

        def _boom(*a, **k):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr("app.services.scoring.get_standing", _boom)
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path, "STB3", "BotSTB3") / "identity.md").read_text()
        # Block omitted, but identity.md still fully generated.
        assert ">> YOUR STANDING" not in identity
        assert "# Identity - BotSTB3" in identity
        assert "## On Spawn - Read These First" in identity


class TestIdentityTlChannelBlock:
    """DWB-438: a team-lead's identity.md surfaces unread Archie-channel
    messages near the standing block; non-TL agents get no block; surfaced
    messages are marked read so they don't re-surface."""

    def _tl(self, client, prefix, repo_path, name):
        project = client.post("/api/projects", json={
            "prefix": prefix, "name": f"Chan {prefix}", "repo_path": str(repo_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": name,
            "role": "team-lead", "api_key": f"{prefix}-key",
        }).json()
        return project, agent

    def test_tl_identity_shows_unread_block(self, client, tmp_path):
        _, recv = self._tl(client, "TCA", tmp_path / "a", "ArchieTCA")
        _, send = self._tl(client, "TCB", tmp_path / "b", "ArchieTCB")
        # A direct message to recv + a broadcast from send.
        client.post("/api/tl-channel", json={
            "from_agent_id": send["id"], "to_agent_id": recv["id"],
            "body": "can you take the shared migration?"})
        client.post("/api/tl-channel", json={
            "from_agent_id": send["id"], "body": "anyone free to review auth?"})

        r = client.post(f"/api/agents/{recv['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path / "a", "TCA", "ArchieTCA") / "identity.md").read_text()
        assert ">> ARCHIE CHANNEL: 2 unread messages" in identity
        assert "[direct] ArchieTCB (TCB): can you take the shared migration?" in identity
        assert "[broadcast] ArchieTCB (TCB): anyone free to review auth?" in identity
        assert "/tl command" in identity
        assert "# Identity - ArchieTCA" in identity  # body intact

    def test_surfaced_messages_marked_read_not_resurfaced(self, client, tmp_path):
        _, recv = self._tl(client, "TCC", tmp_path / "c", "ArchieTCC")
        _, send = self._tl(client, "TCD", tmp_path / "d", "ArchieTCD")
        client.post("/api/tl-channel", json={
            "from_agent_id": send["id"], "to_agent_id": recv["id"], "body": "ping one"})

        # First scaffold surfaces + marks read.
        client.post(f"/api/agents/{recv['id']}/scaffold-memory")
        assert client.get(f"/api/tl-channel/unread?agent_id={recv['id']}").json() == []
        # Second scaffold: nothing unread -> block omitted.
        client.post(f"/api/agents/{recv['id']}/scaffold-memory")
        identity = (_memory_dir(tmp_path / "c", "TCC", "ArchieTCC") / "identity.md").read_text()
        assert ">> ARCHIE CHANNEL" not in identity

    def test_singular_count_phrasing(self, client, tmp_path):
        _, recv = self._tl(client, "TCE", tmp_path / "e", "ArchieTCE")
        _, send = self._tl(client, "TCF", tmp_path / "f", "ArchieTCF")
        client.post("/api/tl-channel", json={
            "from_agent_id": send["id"], "to_agent_id": recv["id"], "body": "solo"})
        client.post(f"/api/agents/{recv['id']}/scaffold-memory")
        identity = (_memory_dir(tmp_path / "e", "TCE", "ArchieTCE") / "identity.md").read_text()
        assert ">> ARCHIE CHANNEL: 1 unread message" in identity
        assert "1 unread messages" not in identity  # singular, no trailing s

    def test_non_team_lead_gets_no_block(self, client, tmp_path):
        # A broadcast is visible to every agent via the unread query, but the
        # identity block is role-gated: a worker must get NO block even when it
        # has channel-visible unread.
        project = client.post("/api/projects", json={
            "prefix": "TCG", "name": "Chan TCG", "repo_path": str(tmp_path / "g"),
        }).json()
        worker = client.post("/api/agents", json={
            "project_id": project["id"], "name": "WkrTCG",
            "role": "backend-worker", "api_key": "tcg-key",
        }).json()
        _, send = self._tl(client, "TCH", tmp_path / "h", "ArchieTCH")
        client.post("/api/tl-channel", json={
            "from_agent_id": send["id"], "body": "broadcast everyone sees"})
        # The broadcast IS in the worker's unread set...
        assert len(client.get(f"/api/tl-channel/unread?agent_id={worker['id']}").json()) == 1
        # ...but the identity block is role-gated, so the worker gets nothing.
        r = client.post(f"/api/agents/{worker['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path / "g", "TCG", "WkrTCG") / "identity.md").read_text()
        assert ">> ARCHIE CHANNEL" not in identity

    def test_identity_still_generates_when_channel_raises(self, client, tmp_path, monkeypatch):
        _, recv = self._tl(client, "TCI", tmp_path / "i", "ArchieTCI")

        def _boom(*a, **k):
            raise RuntimeError("channel exploded")

        monkeypatch.setattr("app.services.tl_channel.unread_for_agent", _boom)
        r = client.post(f"/api/agents/{recv['id']}/scaffold-memory")
        assert r.status_code == 200
        identity = (_memory_dir(tmp_path / "i", "TCI", "ArchieTCI") / "identity.md").read_text()
        assert ">> ARCHIE CHANNEL" not in identity
        assert "# Identity - ArchieTCI" in identity
        assert "## On Spawn - Read These First" in identity
