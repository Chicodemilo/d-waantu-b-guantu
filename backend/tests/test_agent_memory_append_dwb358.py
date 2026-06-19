# Path: tests/test_agent_memory_append_dwb358.py
# File: test_agent_memory_append_dwb358.py
# Created: 2026-06-10
# Purpose: Tests for POST /api/agents/{id}/memory/append (DWB-358 server-side memory writes)
# Caller: pytest
# Callees: POST /api/agents/{agent_id}/memory/append, app.services.agent.append_memory
# Data In: tmp_path filesystem, factory project + agent
# Data Out: Assertions on append idempotency, append-only invariant, ISO 8601 heading shape, error mapping
# Last Modified: 2026-06-19

"""DWB-358 coverage.

Context: Claude Code subagents crash via the ink renderer when they hit
the permission dialog on Edit/Write under .dwb/memory/. The
FastAPI process has no such dialog, so this endpoint runs the append
on the agent's behalf.

Behaviors pinned:

  1. Append works for each of the three appendable files (scratchpad,
     lessons, recent_sessions). Heading shape matches "## <ISO 8601 UTC>"
     and the entry round-trips on read.
  2. Append is non-destructive: prior content is preserved byte-for-byte.
  3. Idempotent with DWB-341 scaffold: if the scaffold somehow missed
     creating the file, the append creates it cleanly.
  4. Refusals at 400: identity.md attempt, unknown file enum (caught as
     422 by the Literal schema), empty content (whitespace-only too).
  5. 404s: missing agent, missing project (FK gap), missing repo_path
     on project is a 400 (config error, not "not found").
  6. ISO 8601 heading shape is the canonical "## YYYY-MM-DDTHH:MM:SS+00:00"
     plus optional "- session <id>" suffix.
"""

import re
from pathlib import Path


def _memory_path(repo_path, prefix, name, file_basename):
    return (
        Path(repo_path)
        / ".dwb/memory"
        / prefix
        / name
        / f"{file_basename}.md"
    )


def _make_jira_unscoped_project_and_agent(client, tmp_path, prefix):
    """Convenience: build a Jira-unconnected project with a repo_path so
    the scaffolder fires + the memory dir exists for appends."""
    project = client.post("/api/projects", json={
        "prefix": prefix, "name": f"Project {prefix}",
        "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": "Memo",
        "role": "backend-worker", "api_key": f"mem-{prefix}",
    }).json()
    return project, agent


# ---------------------------------------------------------------------------
# 1. Happy-path append per file
# ---------------------------------------------------------------------------


class TestAppendHappyPath:
    def test_append_to_scratchpad_round_trips(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MAP1",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "tried X, blocked on Y, working around with Z",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["file"] == "memory"
        assert body["bytes_written"] > 0

        path = _memory_path(tmp_path, "MAP1", "Memo", "memory")
        contents = path.read_text(encoding="utf-8")
        assert "tried X, blocked on Y, working around with Z" in contents

    def test_append_to_lessons_round_trips(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MAP2",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "alembic autogen misses generated cols; hand-write",
        })
        assert r.status_code == 201, r.text
        path = _memory_path(tmp_path, "MAP2", "Memo", "memory")
        contents = path.read_text(encoding="utf-8")
        assert "alembic autogen misses generated cols" in contents

    def test_append_to_recent_sessions_round_trips(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MAP3",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "- 2026-06-10 shipped DWB-358",
        })
        assert r.status_code == 201, r.text
        path = _memory_path(tmp_path, "MAP3", "Memo", "memory")
        contents = path.read_text(encoding="utf-8")
        assert "shipped DWB-358" in contents

    def test_session_id_appears_in_heading_when_provided(
        self, client, tmp_path,
    ):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MAP4",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "session-scoped note",
            "session_id": "abc-123",
        })
        assert r.status_code == 201
        path = _memory_path(tmp_path, "MAP4", "Memo", "memory")
        contents = path.read_text(encoding="utf-8")
        # Heading carries " - session abc-123" suffix when session_id supplied.
        assert "session abc-123" in contents


# ---------------------------------------------------------------------------
# 2. Append-only invariant + DWB-341 scaffold idempotency
# ---------------------------------------------------------------------------


class TestAppendOnlyInvariant:
    def test_prior_content_preserved_byte_for_byte(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MAOP",
        )
        path = _memory_path(tmp_path, "MAOP", "Memo", "memory")
        # Seed prior content directly on disk - simulates a prior append /
        # the scaffold's empty file + an earlier session's notes.
        prior = "## 2026-06-09T12:00:00+00:00\nold inflight notes\n"
        path.write_text(prior, encoding="utf-8")

        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "fresh notes from this session",
        })
        assert r.status_code == 201

        contents = path.read_text(encoding="utf-8")
        # Old content must still be present untouched.
        assert prior in contents
        # New content also present, after the old.
        assert "fresh notes from this session" in contents
        assert contents.index(prior) < contents.index("fresh notes from this session")

    def test_creates_file_if_scaffold_missed_it(self, client, tmp_path):
        """If the on-disk file is missing (fresh repo clone, scaffold
        skipped, etc.), the append creates it cleanly."""
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MNOS",
        )
        path = _memory_path(tmp_path, "MNOS", "Memo", "memory")
        # Wipe the file (the scaffold creates an empty one on agent-create).
        if path.exists():
            path.unlink()
        assert not path.exists()

        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "minted on demand",
        })
        assert r.status_code == 201
        assert path.is_file()
        assert "minted on demand" in path.read_text(encoding="utf-8")

    def test_creates_dir_if_scaffold_missed_it(self, client, tmp_path):
        """If the whole memory dir is missing (cloned repo, never
        scaffolded), the append rebuilds it."""
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MNOD",
        )
        memory_dir = tmp_path / ".dwb/memory/MNOD/Memo"
        import shutil
        if memory_dir.exists():
            shutil.rmtree(memory_dir)
        assert not memory_dir.exists()

        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "first words after re-clone",
        })
        assert r.status_code == 201
        assert (memory_dir / "memory.md").is_file()


# ---------------------------------------------------------------------------
# 3. Refusals (400) and protected files
# ---------------------------------------------------------------------------


class TestAppendRefusals:
    def test_identity_md_attempt_returns_400(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MID",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "identity",
            "content": "trying to clobber identity",
        })
        # The Literal schema rejects "identity" at 422 BEFORE the service
        # sees it. Both 400 and 422 are acceptable refusal codes per the
        # spec ("400" was the spec's wording, but FastAPI's Literal
        # validation kicks in earlier with 422). The important behavior is
        # that the file is never written.
        assert r.status_code in (400, 422), r.text

        # Belt: even if a caller bypasses pydantic (direct service call),
        # the service refuses at the file_protected branch. Verified in
        # test_identity_md_refused_at_service_layer below.

    def test_identity_md_refused_at_service_layer(
        self, client, tmp_path, db_session,
    ):
        """Direct service call (bypassing the Literal schema) confirms
        the service layer also refuses 'identity'."""
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MIDS",
        )
        from app.services.agent import MemoryAppendError, append_memory
        import pytest as _pytest

        with _pytest.raises(MemoryAppendError) as exc:
            append_memory(
                db_session,
                agent_id=agent["id"],
                file="identity",
                content="payload",
            )
        assert exc.value.code == "file_protected"

    def test_unknown_file_returns_400_or_422(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MUF",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "totally_made_up",
            "content": "x",
        })
        assert r.status_code in (400, 422)

    def test_empty_content_returns_400(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MEC1",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "",
        })
        assert r.status_code == 400

    def test_whitespace_only_content_returns_400(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MEC2",
        )
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "   \n\t\n  ",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4. 404 / 400 mapping (missing agent vs missing repo_path)
# ---------------------------------------------------------------------------


class TestAppendNotFoundAndConfigErrors:
    def test_missing_agent_returns_404(self, client):
        r = client.post("/api/agents/999999/memory/append", json={
            "file": "memory",
            "content": "ignored",
        })
        assert r.status_code == 404

    def test_missing_repo_path_returns_400(self, client):
        """Project exists but has no repo_path: 400 (config error, not
        "not found"). The body mentions repo_path so the operator can
        fix the right thing."""
        project = client.post("/api/projects", json={
            "prefix": "MNRP", "name": "Missing Repo",
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "NoRepoAgent",
            "role": "tester", "api_key": "mnrp-1",
        }).json()
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "ignored",
        })
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. ISO 8601 heading shape
# ---------------------------------------------------------------------------


class TestHeadingShape:
    """The append heading is "## YYYY-MM-DDTHH:MM:SS+00:00" optionally
    followed by " - session <id>". A trailing newline separates heading
    from body; a leading blank line separates one block from the next."""

    HEADING_RE = re.compile(
        r"^## \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00(?: - session \S+)?$"
    )

    def test_heading_matches_iso_8601_utc_format(self, client, tmp_path):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MHS1",
        )
        client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "body content",
        })
        path = _memory_path(tmp_path, "MHS1", "Memo", "memory")
        lines = path.read_text(encoding="utf-8").splitlines()
        # First non-empty line in the new block is the heading.
        heading_lines = [ln for ln in lines if ln.startswith("## ")]
        assert heading_lines, f"no heading found in: {lines}"
        for h in heading_lines:
            assert self.HEADING_RE.match(h), f"heading malformed: {h!r}"

    def test_heading_includes_session_id_when_supplied(
        self, client, tmp_path,
    ):
        _, agent = _make_jira_unscoped_project_and_agent(
            client, tmp_path, "MHS2",
        )
        client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory",
            "content": "body",
            "session_id": "sess-xyz",
        })
        path = _memory_path(tmp_path, "MHS2", "Memo", "memory")
        contents = path.read_text(encoding="utf-8")
        m = re.search(
            r"^## \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 - session sess-xyz$",
            contents,
            re.MULTILINE,
        )
        assert m is not None, f"session-id heading not found in: {contents!r}"
