# Path:          tests/test_agent_identity.py
# File:          test_agent_identity.py
# Created:       2026-06-03
# Purpose:       Tests for identify, spawn-prepare, and session-complete endpoints (DWB-289/290/291)
# Caller:        pytest
# Callees:       POST /api/agents/identify, POST /api/agents/spawn-prepare,
#                POST /api/agents/{id}/session-complete
# Data In:       Factory-created projects/agents/instructions, tmp_path-backed repos
# Data Out:      Assertions on HTTP status, response shape, on-disk side effects
# Last Modified: 2026-06-03

"""Tests for the agent identity surface — identify, spawn-prepare, session-complete.

These three endpoints back the new identity foundation (Sprint 59):
- POST /api/agents/identify        → resolves (role, name, prefix) → agent identity payload
- POST /api/agents/spawn-prepare   → wraps identify and adds markdown sections for spawn
- POST /api/agents/{id}/session-complete → appends ISO-stamped scratchpad/lessons entries

Tests use tmp_path-backed projects so the on-disk writes in session-complete are
contained to pytest's per-test temp dir.
"""

import re
from pathlib import Path

from app.services import agent as svc


# ISO 8601 with timezone (the service uses isoformat(timespec="seconds"))
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$"
)


def _make_scoped_project(client, tmp_path, prefix="ID1"):
    """POST a project rooted at tmp_path so memory_dir writes are isolated."""
    r = client.post("/api/projects", json={
        "prefix": prefix,
        "name": f"Identity Project {prefix}",
        "repo_path": str(tmp_path),
    })
    assert r.status_code == 201, r.text
    return r.json()


def _make_scoped_agent(client, project_id, name="Pixel", role="tester", api_key=None):
    r = client.post("/api/agents", json={
        "project_id": project_id,
        "name": name,
        "role": role,
        "api_key": api_key or f"key-{project_id}-{name}",
    })
    assert r.status_code == 201, r.text
    return r.json()


# =============================================================================
# /api/agents/identify
# =============================================================================


class TestIdentifyHappyPath:
    """Happy path resolution + payload shape."""

    def test_returns_200_with_expected_keys(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="IDA")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")

        r = client.post("/api/agents/identify", json={
            "role": "tester",
            "name": "Pixel",
            "project_prefix": "IDA",
        })
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {
            "agent_id", "name", "role", "project_id", "project_prefix",
            "jira_enabled",  # DWB-332
            "memory_dir", "scratchpad_excerpt", "instructions",
        }
        assert data["agent_id"] == agent["id"]
        assert data["project_id"] == project["id"]
        assert data["project_prefix"] == "IDA"
        assert data["name"] == "Pixel"

    def test_memory_dir_includes_prefix_and_name(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="IDB")
        _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "IDB",
        })
        memory_dir = r.json()["memory_dir"]
        assert "/.claude/agents/memory/IDB/Pixel/" in memory_dir
        assert memory_dir.startswith(str(tmp_path))

    def test_role_mismatch_is_non_fatal(self, client, tmp_path):
        """The service comment says role mismatch is non-fatal — agent still returns."""
        project = _make_scoped_project(client, tmp_path, prefix="IDC")
        _make_scoped_agent(client, project["id"], name="Pixel", role="tester")
        r = client.post("/api/agents/identify", json={
            "role": "definitely-not-tester",
            "name": "Pixel",
            "project_prefix": "IDC",
        })
        assert r.status_code == 200
        assert r.json()["role"] == "tester"  # actual role wins


class TestIdentifyNotFound:
    """404 paths."""

    def test_unknown_project_prefix_returns_404(self, client):
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "NOPROJ",
        })
        assert r.status_code == 404
        assert "project prefix" in r.json()["detail"].lower()

    def test_unknown_agent_name_returns_404(self, client, tmp_path):
        _make_scoped_project(client, tmp_path, prefix="IDD")
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Ghost", "project_prefix": "IDD",
        })
        assert r.status_code == 404
        assert "no agent named" in r.json()["detail"].lower()


class TestIdentifyAmbiguous:
    """409 path — unreachable post-DWB-287 UNIQUE(project_id, name) but the
    router still has to map IdentifyError('ambiguous') to 409. We exercise that
    mapping by monkeypatching the service so the constraint can't get in the
    way."""

    def test_ambiguous_returns_409(self, client, monkeypatch):
        def _raise(*args, **kwargs):
            raise svc.IdentifyError("ambiguous", "ambiguous, multiple matches")

        monkeypatch.setattr(svc, "identify_agent", _raise)
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "X",
        })
        assert r.status_code == 409
        assert "ambiguous" in r.json()["detail"].lower()


class TestIdentifyInstructionsScope:
    """Three-scope filter: global + project (this one) + agent (this one)."""

    def test_includes_global_project_and_agent_scopes(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="IDE")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        other_project = _make_scoped_project(client, tmp_path, prefix="IDE2")
        other_agent = _make_scoped_agent(
            client, other_project["id"], name="Other", api_key="k-other"
        )

        # Should be visible
        client.post("/api/instructions", json={
            "scope": "global", "title": "G", "body": "global rule",
        })
        client.post("/api/instructions", json={
            "scope": "project", "title": "P", "body": "project rule",
            "project_id": project["id"],
        })
        client.post("/api/instructions", json={
            "scope": "agent", "title": "A", "body": "agent rule",
            "agent_id": agent["id"],
        })
        # Should NOT be visible
        client.post("/api/instructions", json={
            "scope": "project", "title": "P2", "body": "other project rule",
            "project_id": other_project["id"],
        })
        client.post("/api/instructions", json={
            "scope": "agent", "title": "A2", "body": "other agent rule",
            "agent_id": other_agent["id"],
        })

        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "IDE",
        })
        titles = {i["title"] for i in r.json()["instructions"]}
        assert titles == {"G", "P", "A"}


class TestIdentifyScratchpad:
    """Scratchpad excerpt reads on-disk content tail."""

    def test_returns_empty_when_no_scratchpad(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="IDF")
        _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "IDF",
        })
        assert r.json()["scratchpad_excerpt"] == ""

    def test_reads_existing_scratchpad(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="IDG")
        _make_scoped_agent(client, project["id"], name="Pixel")
        # DWB-293 scaffolder pre-creates the dir + empty scratchpad on agent
        # create, so just overwrite the file with marker content.
        mem = tmp_path / ".claude" / "agents" / "memory" / "IDG" / "Pixel"
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "scratchpad.md").write_text("scratchpad content marker\n")

        r = client.post("/api/agents/identify", json={
            "role": "tester", "name": "Pixel", "project_prefix": "IDG",
        })
        assert "scratchpad content marker" in r.json()["scratchpad_excerpt"]


# =============================================================================
# /api/agents/spawn-prepare
# =============================================================================


class TestSpawnPrepareHappyPath:

    def test_returns_three_markdown_sections(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SPA")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "SPA",
        })
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {
            "agent_id", "identity_prompt", "scratchpad_excerpt", "boundary_rules",
        }
        assert data["agent_id"] == agent["id"]
        assert data["identity_prompt"].startswith("## Identity")
        assert data["scratchpad_excerpt"].startswith("## Recent Scratchpad")
        assert data["boundary_rules"].startswith("## Boundary Rules")

    def test_identity_prompt_carries_core_fields(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SPB")
        agent = _make_scoped_agent(client, project["id"], name="Pixel", role="tester")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "SPB",
        })
        prompt = r.json()["identity_prompt"]
        assert f"agent_id: {agent['id']}" in prompt
        assert "name: Pixel" in prompt
        assert "role: tester" in prompt
        assert "project: SPB" in prompt
        assert "memory_dir:" in prompt

    def test_empty_scratchpad_renders_placeholder(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SPC")
        _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "SPC",
        })
        assert "(no entries yet)" in r.json()["scratchpad_excerpt"]


class TestSpawnPrepareBoundaryRules:
    """boundary_rules uses the same 3-scope filter as identify (global + this
    project + this agent). Out-of-scope rules from other projects/agents must
    not leak in."""

    def test_three_scope_filter_applied(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SPD")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        other_project = _make_scoped_project(client, tmp_path, prefix="SPD2")
        other_agent = _make_scoped_agent(
            client, other_project["id"], name="Other", api_key="k-other-spd"
        )

        client.post("/api/instructions", json={
            "scope": "global", "title": "GLOBAL_RULE", "body": "g",
        })
        client.post("/api/instructions", json={
            "scope": "project", "title": "PROJECT_RULE", "body": "p",
            "project_id": project["id"],
        })
        client.post("/api/instructions", json={
            "scope": "agent", "title": "AGENT_RULE", "body": "a",
            "agent_id": agent["id"],
        })
        client.post("/api/instructions", json={
            "scope": "project", "title": "OTHER_PROJECT_RULE", "body": "x",
            "project_id": other_project["id"],
        })
        client.post("/api/instructions", json={
            "scope": "agent", "title": "OTHER_AGENT_RULE", "body": "y",
            "agent_id": other_agent["id"],
        })

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "SPD",
        })
        rules = r.json()["boundary_rules"]
        assert "GLOBAL_RULE" in rules
        assert "PROJECT_RULE" in rules
        assert "AGENT_RULE" in rules
        assert "OTHER_PROJECT_RULE" not in rules
        assert "OTHER_AGENT_RULE" not in rules

    def test_no_rules_renders_placeholder(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SPE")
        _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "SPE",
        })
        assert "(no boundary rules)" in r.json()["boundary_rules"]


class TestSpawnPrepareErrors:

    def test_unknown_project_returns_404(self, client):
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "NOPROJ",
        })
        assert r.status_code == 404

    def test_unknown_agent_returns_404(self, client, tmp_path):
        _make_scoped_project(client, tmp_path, prefix="SPF")
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Ghost", "project_prefix": "SPF",
        })
        assert r.status_code == 404

    def test_ambiguous_returns_409(self, client, monkeypatch):
        def _raise(*args, **kwargs):
            raise svc.IdentifyError("ambiguous", "ambiguous, multiple matches")

        monkeypatch.setattr(svc, "spawn_prepare_payload", _raise)
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "tester", "name": "Pixel", "project_prefix": "X",
        })
        assert r.status_code == 409


# =============================================================================
# /api/agents/{id}/session-complete
# =============================================================================


class TestSessionCompleteHappyPath:

    def test_returns_200_and_expected_keys(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCA")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-1",
            "summary": "did a thing",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) == {
            "agent_id", "session_id", "timestamp", "paths_written", "bytes_written",
        }
        assert data["agent_id"] == agent["id"]
        assert data["session_id"] == "sess-1"
        assert data["bytes_written"] > 0

    def test_writes_scratchpad_and_recent_sessions(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCB")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-2",
            "summary": "investigation done",
            "tokens_used": 1234,
        })
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCB" / "Pixel"
        assert mem.is_dir()
        scratchpad = (mem / "scratchpad.md").read_text()
        assert "sess-2" in scratchpad
        assert "investigation done" in scratchpad
        assert "tokens_used: 1234" in scratchpad
        recent = (mem / "recent_sessions.md").read_text()
        assert "sess-2" in recent
        assert "(1234 tok)" in recent
        # lessons.md is pre-touched empty by the DWB-293 scaffolder, but the
        # session-complete endpoint must NOT report it in paths_written when
        # no lessons were supplied (i.e. it didn't append to it).
        paths = r.json()["paths_written"]
        assert not any(p.endswith("lessons.md") for p in paths)
        assert (mem / "lessons.md").stat().st_size == 0


class TestSessionCompleteLessons:

    def test_lessons_present_writes_lessons_md(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCC")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-3",
            "summary": "ran tests",
            "lessons": ["always check the fixtures", "tmp_path is your friend"],
        })
        assert r.status_code == 200
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCC" / "Pixel"
        lessons = (mem / "lessons.md").read_text()
        assert "always check the fixtures" in lessons
        assert "tmp_path is your friend" in lessons
        assert "sess-3" in lessons
        paths = r.json()["paths_written"]
        assert any(p.endswith("lessons.md") for p in paths)

    def test_empty_lessons_list_skips_lessons_md(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCD")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-4",
            "summary": "no lessons",
            "lessons": [],
        })
        assert r.status_code == 200
        # lessons.md exists as a 0-byte scaffolded placeholder; the endpoint
        # must not have appended to it.
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCD" / "Pixel"
        paths = r.json()["paths_written"]
        assert not any(p.endswith("lessons.md") for p in paths)
        assert (mem / "lessons.md").stat().st_size == 0


class TestSessionCompleteMemoryDirIdempotency:

    def test_memory_dir_recreated_if_missing(self, client, tmp_path):
        """Even though the DWB-293 scaffolder normally pre-creates the dir on
        agent create, session-complete must self-heal if the dir is missing
        (e.g. user wiped it). Removing the dir before the call exercises that
        precursor mkdir branch."""
        import shutil

        project = _make_scoped_project(client, tmp_path, prefix="SCE")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCE" / "Pixel"
        if mem.exists():
            shutil.rmtree(mem)
        assert not mem.exists()
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-5",
            "summary": "first call",
        })
        assert r.status_code == 200
        assert mem.is_dir()

    def test_second_call_appends_not_clobbers(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCF")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-6a",
            "summary": "first",
        })
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-6b",
            "summary": "second",
        })
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCF" / "Pixel"
        content = (mem / "scratchpad.md").read_text()
        assert "sess-6a" in content
        assert "sess-6b" in content
        assert content.count("## ") >= 2  # two timestamped blocks

    def test_preexisting_memory_dir_not_clobbered(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCG")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCG" / "Pixel"
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "scratchpad.md").write_text("preexisting content\n")
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-7",
            "summary": "after preexisting",
        })
        content = (mem / "scratchpad.md").read_text()
        assert content.startswith("preexisting content")
        assert "sess-7" in content


class TestSessionCompleteTimestamp:

    def test_timestamp_is_iso8601(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCH")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-8",
            "summary": "iso check",
        })
        timestamp = r.json()["timestamp"]
        assert _ISO8601_RE.match(timestamp), f"not ISO 8601: {timestamp}"

    def test_timestamp_appears_in_scratchpad(self, client, tmp_path):
        project = _make_scoped_project(client, tmp_path, prefix="SCI")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-9",
            "summary": "timestamp in file",
        })
        timestamp = r.json()["timestamp"]
        mem = tmp_path / ".claude" / "agents" / "memory" / "SCI" / "Pixel"
        assert timestamp in (mem / "scratchpad.md").read_text()
        assert timestamp in (mem / "recent_sessions.md").read_text()


class TestSessionCompleteErrors:

    def test_missing_agent_returns_404(self, client):
        r = client.post("/api/agents/999999/session-complete", json={
            "session_id": "sess-x",
            "summary": "nope",
        })
        assert r.status_code == 404

    def test_unscoped_agent_returns_404(self, client, tmp_path, db_session):
        """An Agent row with project_id=NULL exists historically but cannot
        resolve a memory_dir. The service maps that to 404 (agent_unscoped)."""
        project = _make_scoped_project(client, tmp_path, prefix="SCJ")
        agent = _make_scoped_agent(client, project["id"], name="Pixel")

        # Null out project_id at the ORM level — bypasses the create-time
        # required field, simulating legacy rows.
        from app.models.agent import Agent as AgentModel
        row = db_session.get(AgentModel, agent["id"])
        row.project_id = None
        db_session.flush()

        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-y",
            "summary": "unscoped",
        })
        assert r.status_code == 404
        assert "project_id" in r.json()["detail"].lower() or \
               "memory_dir" in r.json()["detail"].lower()
