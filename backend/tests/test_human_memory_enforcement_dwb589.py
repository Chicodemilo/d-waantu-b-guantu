# Path: tests/test_human_memory_enforcement_dwb589.py
# File: test_human_memory_enforcement_dwb589.py
# Created: 2026-09-29 (DWB-589)
# Purpose: Guard spec section 7 hard rule 1 end to end - stock memory writes
#          refused under human_memory, both stock READ paths sealed, the
#          DWB-519 gate proving participation from the new store, and the
#          harness PreToolUse hook denying a write to Claude Code's own memory.
# Caller: pytest
# Callees: /api/agents/* memory routes, memory_trace, memory_mode,
#          scripts/hooks/block_harness_memory_writes.py (as a subprocess)
# Data In: lat_test rows, tmp_path memory files, a crafted hook payload
# Data Out: assertions
# Last Modified: 2026-09-29 (DWB-589)

"""DWB-589, the enforcement ticket.

Section 7 states hard rule 1 in prose. Prose gets rubber-stamped, so this file
exists to make the rule a thing the API does rather than a thing the playbook
says. The structural test at the bottom is the important one: every other guard
in this codebase is a list someone has to remember to update, and that one fails
loudly instead.
"""

import json
import os
import pathlib
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from app.services import memory_mode as memory_mode_svc
from app.services import memory_trace

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
HOOK_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "block_harness_memory_writes.py"


def _write_stock_memory(repo_path, prefix, name, when: datetime):
    """Create a stock memory.md whose mtime says it was written at `when`.

    Mirrors tests/test_write_on_close_dwb519.py::_write_mem. The mtime is the
    part that matters: it is what effective_last_write_at actually reads.
    """
    d = pathlib.Path(repo_path) / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "memory.md"
    path.write_text(
        f"\n## {when.astimezone(timezone.utc).isoformat(timespec='seconds')}\n"
        "a stock note from before the switch\n",
        encoding="utf-8",
    )
    ts = when.timestamp()
    os.utime(path, (ts, ts))
    return path


@pytest.fixture
def human_memory_project(make_project, tmp_path):
    return make_project(repo_path=str(tmp_path), memory_mode="human_memory")


@pytest.fixture
def stock_project(make_project, tmp_path):
    return make_project(repo_path=str(tmp_path))


# ---------------------------------------------------------------------------
# AC1 - the write side
# ---------------------------------------------------------------------------

SEALED_ROUTES = {
    "memory/append": {"file": "memory", "content": "a note"},
    "memory/condense": {"file": "memory", "content": "the whole file, shorter"},
    "memory/compact": {"file": "memory", "content": "the whole file, replaced"},
}


class TestStockWritesAreSealed:
    @pytest.mark.parametrize("route", sorted(SEALED_ROUTES))
    def test_stock_write_routes_refuse_409(
        self, client, make_agent, human_memory_project, route
    ):
        agent = make_agent(project_id=human_memory_project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/{route}", json=SEALED_ROUTES[route]
        )
        assert r.status_code == 409, (route, r.text)

    def test_session_complete_refuses_409(
        self, client, make_agent, human_memory_project
    ):
        agent = make_agent(project_id=human_memory_project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/session-complete",
            json={"summary": "did things", "tokens_used": 10},
        )
        assert r.status_code == 409, r.text

    @pytest.mark.parametrize("route", sorted(SEALED_ROUTES))
    def test_the_refusal_names_the_endpoint_to_use_instead(
        self, client, make_agent, human_memory_project, route
    ):
        """A refusal that cannot say what to do instead is a wall.

        The agent hitting it is holding a lesson right now and is about to drop
        it on the floor, so the 409 has to carry the replacement, not just the
        rule.
        """
        agent = make_agent(project_id=human_memory_project["id"])
        detail = client.post(
            f"/api/agents/{agent['id']}/{route}", json=SEALED_ROUTES[route]
        ).json()["detail"]
        assert f"/api/agents/{agent['id']}/memories" in detail, detail
        assert "hard rule 1" in detail

    @pytest.mark.parametrize("route", sorted(SEALED_ROUTES))
    def test_a_sealed_write_lands_nothing_on_disk(
        self, client, make_agent, human_memory_project, tmp_path, route
    ):
        """The guard runs BEFORE the write, proved rather than assumed."""
        agent = make_agent(project_id=human_memory_project["id"], name="Sealed")
        client.post(f"/api/agents/{agent['id']}/{route}", json=SEALED_ROUTES[route])
        path = (
            tmp_path
            / ".dwb"
            / "memory"
            / human_memory_project["prefix"]
            / "Sealed"
            / "memory.md"
        )
        assert not path.exists() or path.read_text(encoding="utf-8").strip() == ""

    @pytest.mark.parametrize("route", sorted(SEALED_ROUTES))
    def test_stock_projects_are_untouched(self, client, make_agent, stock_project, route):
        """The seal must not become a general-purpose failure.

        A guard that breaks the default mode while enforcing the opt-in one
        would be caught by the wider suite, but only after someone bisected it.
        """
        agent = make_agent(project_id=stock_project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/{route}", json=SEALED_ROUTES[route]
        )
        assert r.status_code in (200, 201), (route, r.text)


class TestReadEndpointsStayOpen:
    """Per-route, not prefix-wide. AC1's companion."""

    def test_scored_memory_still_works_under_human_memory(
        self, client, make_agent, human_memory_project
    ):
        """GET /memory/scored is DWB-585's read of the NEW store and lives under
        the same /memory prefix. A prefix-wide guard would disable the endpoint
        that makes the mode work."""
        agent = make_agent(project_id=human_memory_project["id"])
        r = client.get(f"/api/agents/{agent['id']}/memory/scored")
        assert r.status_code == 200, r.text

    def test_the_new_store_write_still_works_under_human_memory(
        self, client, make_agent, human_memory_project
    ):
        agent = make_agent(project_id=human_memory_project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "the real store"}
        )
        assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# AC2 - the read side. The half that ships the defect if it is skipped.
# ---------------------------------------------------------------------------


class TestStockReadsAreSealed:
    def test_spawn_prepare_does_not_serve_stock_memory(
        self, client, make_agent, human_memory_project, tmp_path
    ):
        agent = make_agent(
            project_id=human_memory_project["id"], name="Spawned", role="backend-worker"
        )
        secret = "STOCK CONTENT THAT MUST NOT BE SERVED"
        path = _write_stock_memory(
            tmp_path,
            human_memory_project["prefix"],
            "Spawned",
            datetime.now(timezone.utc),
        )
        path.write_text(f"## heading\n{secret}\n", encoding="utf-8")

        r = client.post(
            "/api/agents/spawn-prepare",
            json={
                "role": "backend-worker",
                "name": "Spawned",
                "project_prefix": human_memory_project["prefix"],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Prove the field exists before asserting what is NOT in it: an absent
        # key would satisfy a naive "secret not in memory_full" check trivially.
        assert "memory_full" in body
        assert body["memory_full"], "memory_full was empty; the check below is vacuous"
        assert secret not in body["memory_full"]
        assert "/api/agents/" in body["memory_full"], body["memory_full"]

    def test_session_start_does_not_inject_stock_memory(
        self, client, db_session, make_agent, human_memory_project, tmp_path
    ):
        """tl_memory_for_project feeds SessionStart additionalContext.

        On a switched project this would inject the frozen stock file into every
        session while writes go to the new store - two homes that both look
        authoritative, which section 7 opens by naming as THE failure mode.
        """
        from app.services import agent as agent_svc

        make_agent(
            project_id=human_memory_project["id"], name="Archie_T", role="team-lead"
        )
        secret = "TL STOCK MEMORY THAT MUST NOT BE INJECTED"
        path = _write_stock_memory(
            tmp_path,
            human_memory_project["prefix"],
            "Archie_T",
            datetime.now(timezone.utc),
        )
        path.write_text(f"## heading\n{secret}\n", encoding="utf-8")

        served = agent_svc.tl_memory_for_project(db_session, human_memory_project["id"])
        assert served, "nothing was served; the absence check below is vacuous"
        assert secret not in served
        assert "hard rule 1" in served

    def test_stock_projects_still_get_their_memory(
        self, client, db_session, make_agent, stock_project, tmp_path
    ):
        """The seal is mode-scoped, not a deletion of the feature."""
        from app.services import agent as agent_svc

        make_agent(project_id=stock_project["id"], name="Archie_S", role="team-lead")
        marker = "STOCK MODE CONTENT THAT SHOULD STILL BE SERVED"
        path = _write_stock_memory(
            tmp_path, stock_project["prefix"], "Archie_S", datetime.now(timezone.utc)
        )
        path.write_text(f"## heading\n{marker}\n", encoding="utf-8")

        served = agent_svc.tl_memory_for_project(db_session, stock_project["id"])
        assert marker in served


# ---------------------------------------------------------------------------
# AC3 - the write-on-close gate
# ---------------------------------------------------------------------------


class TestWriteOnCloseGateOnASwitchedProject:
    """The positive needed no branch. The negative did, and this proves why.

    DWB-586 stamps agents.last_memory_write_at, so a human_memory agent who
    writes a raw memory satisfies the gate with no mode-aware code at all.

    The NEGATIVE is the one with teeth, and it had a hole: the gate reads
    max(column, memory.md mtime), so an agent with NO row in the new store still
    passed if a stale stock memory.md happened to sit in the window - a
    pre-switch write, or any direct file write, since `.dwb/` is writable and
    only the playbook warns against it.
    """

    def test_a_raw_memory_write_satisfies_the_gate(
        self, client, db_session, make_agent, human_memory_project
    ):
        agent_row = make_agent(project_id=human_memory_project["id"], name="Writer")
        r = client.post(
            f"/api/agents/{agent_row['id']}/memories", json={"body": "a lesson"}
        )
        assert r.status_code == 201, r.text
        agent = db_session.get(Agent, agent_row["id"])
        db_session.expire_all()
        since = datetime.now(timezone.utc) - timedelta(days=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is True

    def test_stale_stock_mtime_does_not_satisfy_the_gate(
        self, client, db_session, make_agent, human_memory_project, tmp_path
    ):
        """THE HOLE. Written before the fix and shown passing against the old
        gate, which is what proved the hole was real rather than argued.

        An agent on a switched project with a recent stock memory.md and NO row
        in the new store must NOT pass. Otherwise AC3's negative has no teeth:
        the close would go green for an agent who never touched human_memory.
        """
        agent_row = make_agent(project_id=human_memory_project["id"], name="Freeloader")
        _write_stock_memory(
            tmp_path,
            human_memory_project["prefix"],
            "Freeloader",
            datetime.now(timezone.utc),
        )
        agent = db_session.get(Agent, agent_row["id"])
        db_session.expire_all()
        since = datetime.now(timezone.utc) - timedelta(days=1)

        rows = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent_row["id"])
            .count()
        )
        assert rows == 0, "fixture wrote a memory row; the point of this test is none"
        assert memory_trace.agent_wrote_since(db_session, agent, since) is False

    def test_a_pre_window_raw_write_does_not_satisfy_the_gate(
        self, client, db_session, make_agent, human_memory_project
    ):
        """The window is still a window. A row from before `since` is not
        participation in THIS sprint."""
        agent_row = make_agent(project_id=human_memory_project["id"], name="Earlier")
        client.post(f"/api/agents/{agent_row['id']}/memories", json={"body": "old"})
        row = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent_row["id"])
            .one()
        )
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=10
        )
        db_session.flush()
        agent = db_session.get(Agent, agent_row["id"])
        since = datetime.now(timezone.utc) - timedelta(days=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is False

    def test_stock_projects_keep_the_old_behaviour(
        self, client, db_session, make_agent, stock_project, tmp_path
    ):
        """A stock agent with a recent memory.md still passes. The branch must
        not change the mode it is not for."""
        agent_row = make_agent(project_id=stock_project["id"], name="StockWriter")
        _write_stock_memory(
            tmp_path, stock_project["prefix"], "StockWriter", datetime.now(timezone.utc)
        )
        agent = db_session.get(Agent, agent_row["id"])
        since = datetime.now(timezone.utc) - timedelta(days=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is True


class TestSprintCloseOnASwitchedProject:
    """AC3 through the CLOSE itself, not only through the helper.

    The helper tests above prove agent_wrote_since answers correctly. These
    prove the sprint-close endpoint actually asks it, which is a different
    claim: a gate wired to the wrong helper, or skipped for a mode, passes
    every helper test there is.
    """

    def _setup(self, make_project, make_agent, make_sprint, make_ticket, tmp_path):
        project = make_project(
            repo_path=str(tmp_path),
            memory_mode="human_memory",
            force_handoff_md=False,
        )
        agent = make_agent(
            project_id=project["id"], name="Switched", role="backend-worker"
        )
        sprint = make_sprint(
            project_id=project["id"],
            status="active",
            start_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        make_ticket(
            project_id=project["id"],
            sprint_id=sprint["id"],
            assigned_agent_id=agent["id"],
        )
        return project, agent, sprint

    def test_close_is_green_with_participation_from_the_new_store(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        project, agent, sprint = self._setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path
        )
        r = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "a lesson worth keeping"}
        )
        assert r.status_code == 201, r.text

        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_close_is_blocked_and_names_the_agent_with_no_row(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        """The negative is where the teeth are."""
        project, agent, sprint = self._setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path
        )
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "write-on-close gate failed" in detail
        assert "Switched" in detail

    def test_a_stock_write_does_not_buy_a_close_on_a_switched_project(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        """THE HOLE, at the level that matters.

        Before the DWB-589 branch this closed GREEN: a stale stock memory.md in
        the window satisfied the gate for an agent with nothing in the new
        store. A sprint closing on participation in a store the project is
        forbidden to write is the gate having no teeth at all.
        """
        project, agent, sprint = self._setup(
            make_project, make_agent, make_sprint, make_ticket, tmp_path
        )
        _write_stock_memory(
            tmp_path, project["prefix"], "Switched", datetime.now(timezone.utc)
        )
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400, (
            "a stale stock memory.md bought a close on a human_memory project; "
            "the gate is reading the sealed store"
        )
        assert "Switched" in r.json()["detail"]


# ---------------------------------------------------------------------------
# AC4 - the harness guard
# ---------------------------------------------------------------------------


def _run_hook(payload: dict, env_extra: dict | None = None):
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc


class TestHarnessMemoryHook:
    def test_the_script_exists_and_is_executable(self):
        assert HOOK_SCRIPT.is_file(), HOOK_SCRIPT
        assert os.access(HOOK_SCRIPT, os.X_OK), f"{HOOK_SCRIPT} is not executable"

    def test_a_write_into_the_harness_memory_dir_is_denied(self, tmp_path):
        config_dir = tmp_path / "claude-config"
        target = config_dir / "projects" / "some-slug" / "memory" / "MEMORY.md"
        proc = _run_hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            },
            {"CLAUDE_CONFIG_DIR": str(config_dir)},
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        decision = out["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny", out
        reason = decision["permissionDecisionReason"]
        # The message must say where memory actually lives, with the API shape.
        assert "/api/agents/" in reason, reason
        assert "memories" in reason, reason

    def test_an_unrelated_write_is_not_denied(self, tmp_path):
        config_dir = tmp_path / "claude-config"
        proc = _run_hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(tmp_path / "src" / "thing.py")},
            },
            {"CLAUDE_CONFIG_DIR": str(config_dir)},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "" or "deny" not in proc.stdout

    @pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
    def test_every_write_tool_is_covered(self, tmp_path, tool):
        """Parametrized over the tools the hook claims to cover, so a tool added
        to the matcher without a branch here surfaces."""
        config_dir = tmp_path / "claude-config"
        target = config_dir / "projects" / "s" / "memory" / "note.md"
        proc = _run_hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": str(target)},
            },
            {"CLAUDE_CONFIG_DIR": str(config_dir)},
        )
        out = json.loads(proc.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", (tool, out)

    def test_falls_back_to_home_when_config_dir_is_unset(self, tmp_path):
        """CLAUDE_CONFIG_DIR is optional; HOME is the documented fallback."""
        fake_home = tmp_path / "home"
        target = fake_home / ".claude" / "projects" / "s" / "memory" / "m.md"
        env = {"HOME": str(fake_home)}
        # Explicitly clear it rather than trusting the ambient environment.
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target)},
                }
            ),
            capture_output=True,
            text=True,
            env={**{k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}, **env},
        )
        out = json.loads(proc.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", out

    def test_malformed_input_never_blocks_the_caller(self):
        """Project rule: hook scripts always exit 0.

        A hook that crashes on unexpected input would block every tool call in
        the session, which is a far worse outcome than failing to guard one
        write.
        """
        for bad in ["", "not json", "{}", '{"tool_input": null}']:
            proc = subprocess.run(
                [sys.executable, str(HOOK_SCRIPT)],
                input=bad,
                capture_output=True,
                text=True,
            )
            assert proc.returncode == 0, (bad, proc.stderr)

    def test_no_hardcoded_home_directory_or_username(self):
        """DWB-574 shipped a hardcoded home directory that leaked a real
        username into the repo. This repo is cloned onto other machines.

        Asserts on SHAPE rather than on the current username: a check for one
        literal name would pass on every other developer's machine while the
        bug was still there.
        """
        source = HOOK_SCRIPT.read_text(encoding="utf-8")
        assert source.strip(), "read an empty script; this check saw nothing"
        for pattern in ("/Users/", "/home/", "C:\\\\Users"):
            assert pattern not in source, f"hardcoded home path {pattern!r} in the hook"
        assert "expanduser" in source or "Path.home" in source, (
            "the harness path must be DERIVED; no derivation call found"
        )


# ---------------------------------------------------------------------------
# The structural guard - the one that fails loudly instead of being remembered
# ---------------------------------------------------------------------------


class TestEveryMemoryRouteIsSealedOrExcused:
    """The structural guard. Fails loudly instead of being remembered.

    Covers EVERY method, not just POST. An earlier version of this test read
    only POST routes while OPEN_UNDER_HUMAN_MEMORY listed two GET routes, so
    those two entries were documented and never checked - a mutation dropping
    one of them passed. That gap is the exact shape this class exists to catch,
    so it is worth having been caught by it.
    """

    @staticmethod
    def _memory_routes() -> dict[str, set[str]]:
        """Every agent-scoped memory route, as {suffix: {methods}}."""
        from app.main import app

        routes: dict[str, set[str]] = {}
        for r in app.routes:
            path = getattr(r, "path", "")
            if "/api/agents/{agent_id}/" not in path:
                continue
            suffix = path.rsplit("{agent_id}/", 1)[-1]
            if "memor" not in suffix and suffix != "session-complete":
                continue
            routes.setdefault(suffix, set()).update(
                m for m in getattr(r, "methods", set()) if m not in ("HEAD", "OPTIONS")
            )
        return routes

    def test_the_scan_sees_the_real_route_table(self):
        """Proves the assertions below are not passing against an empty scan."""
        routes = self._memory_routes()
        assert len(routes) >= 6, sorted(routes)
        # The four sealed writes and the new store must all be visible to it.
        for expected in (
            "memory/append",
            "memory/condense",
            "memory/compact",
            "session-complete",
            "memories",
            "memory/scored",
        ):
            assert expected in routes, (expected, sorted(routes))

    def test_no_memory_route_is_unaccounted_for(self):
        """Every memory route is either sealed or carries a written reason.

        This is the difference between a guard and a convention. Every other
        list in this codebase is one someone has to remember to update; a new
        memory route added later fails HERE rather than shipping unaccounted,
        so staying open is a decision with a reason rather than an oversight.
        """
        routes = self._memory_routes()
        sealed = set(memory_mode_svc._WRITE_REPLACEMENT)
        excused = set(memory_mode_svc.OPEN_UNDER_HUMAN_MEMORY)
        unaccounted = set(routes) - sealed - excused
        assert unaccounted == set(), (
            f"memory route(s) {sorted(unaccounted)} are neither sealed in "
            "memory_mode._WRITE_REPLACEMENT nor excused in "
            "OPEN_UNDER_HUMAN_MEMORY. Add to one or the other - staying open "
            "must be a decision with a reason, not an omission."
        )

    def test_the_allowlist_names_only_routes_that_exist(self):
        """A stale allowlist entry is the other half of the same failure.

        A route renamed or removed leaves an excuse behind that silently
        excuses nothing, and the next route to take that name inherits it.
        """
        routes = self._memory_routes()
        stale = set(memory_mode_svc.OPEN_UNDER_HUMAN_MEMORY) - set(routes)
        assert stale == set(), (
            f"OPEN_UNDER_HUMAN_MEMORY excuses {sorted(stale)}, which no longer "
            "exists as a memory route. Remove the entry."
        )

    def test_no_sealed_route_is_a_read(self):
        """Per-route, not prefix-wide, asserted structurally.

        Hard rule 1 seals stock WRITES through these endpoints; sealing a GET
        under the same prefix would disable the reads the mode depends on,
        which is the mistake Pam caught at filing.
        """
        routes = self._memory_routes()
        for suffix in memory_mode_svc._WRITE_REPLACEMENT:
            methods = routes.get(suffix, set())
            assert methods, f"sealed route {suffix!r} does not exist"
            assert "GET" not in methods, (
                f"sealed route {suffix!r} answers GET; a read was sealed"
            )

    def test_every_excused_route_carries_a_reason(self):
        for route, reason in memory_mode_svc.OPEN_UNDER_HUMAN_MEMORY.items():
            assert reason and len(reason) > 20, (route, reason)

    def test_every_sealed_route_names_a_replacement(self):
        for route, replacement in memory_mode_svc._WRITE_REPLACEMENT.items():
            assert "/api/agents/" in replacement, (route, replacement)
