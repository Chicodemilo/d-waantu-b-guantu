# Path: tests/test_memory_consolidate_hook_dwb609.py
# File: test_memory_consolidate_hook_dwb609.py
# Created: 2026-09-30 (DWB-609)
# Purpose: Guard the wiring, not the orchestration logic - that
#          POST /api/hooks/session-start actually calls
#          memory_consolidate.consolidate_agent for a resolved agent on a
#          human_memory project, that it does nothing on a stock project or
#          with no resolved agent, and that a consolidation failure never
#          turns the hook into a 500.
# Caller: pytest
# Callees: POST /api/hooks/session-start, app.services.hook_tracking,
#          app.services.memory_consolidate
# Data In: factory fixtures, tmp_path repo dirs, agent_memories rows
# Data Out: Assertions on agent_memories/journal_entries state after a real
#           HTTP call, and on the hook's own response/status code
# Last Modified: 2026-09-30 (DWB-609)

"""Deliberately thin. `test_memory_consolidate_dwb609.py` already proves the
ORCHESTRATION (all four movements, the promotion-before-eviction order, that
nothing is fired) by calling `consolidate_agent` directly - re-proving that
here through the HTTP layer would be the second-implementation drift this
lane's own lessons warn about. What direct unit tests on
`memory_consolidate.py` cannot prove is that the real hook endpoint actually
reaches it, under the real gating conditions (human_memory mode, a resolved
agent) and never breaks the endpoint's own hard contract (never 5xx). That is
the whole job of this file.
"""

import uuid
from datetime import datetime, timedelta

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project


def _closed_session(db, project_id, *, hours_ago=1):
    from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession

    s = DwbSession(
        project_id=project_id,
        opened_at=datetime.utcnow() - timedelta(hours=hours_ago),
        closed_at=datetime.utcnow() - timedelta(hours=hours_ago) + timedelta(minutes=5),
        open_method=DwbOpenMethod.regex,
        close_method=DwbCloseMethod.regex,
    )
    db.add(s)
    db.flush()
    return s


def _hook_session(db, *, agent_id, project_id, dwb_session_id, tag):
    from app.models.hook_session import HookSession

    h = HookSession(
        session_id=f"dwb609-hookwire-{tag}", agent_id=agent_id, project_id=project_id,
        dwb_session_id=dwb_session_id, total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _elapse(db, *, project_id, agent_id, n):
    for i in range(n):
        s = _closed_session(db, project_id, hours_ago=n - i)
        _hook_session(db, agent_id=agent_id, project_id=project_id, dwb_session_id=s.id, tag=f"e{i}")


class TestConsolidationFiresFromTheRealHook:
    def test_a_floor_memory_is_evicted_by_a_real_session_start_call(
        self, client, make_project, make_agent, db_session, tmp_path
    ):
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="worker")

        # Human_memory mode, set directly on the model - the state-machine
        # PATCH route is a separate contract (DWB-593) this test has no need
        # to drive; what matters here is the GATE this hook checks, not how a
        # project gets into the mode.
        proj_row = db_session.get(Project, project["id"])
        proj_row.memory_mode = MemoryMode.human_memory
        db_session.commit()

        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        memory = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.working,
            created_session_id=origin.id, body="a box fact at the floor",
        )
        db_session.add(memory)
        db_session.commit()
        memory_id = memory.id
        _elapse(db_session, project_id=project["id"], agent_id=agent["id"], n=91)

        sid = str(uuid.uuid4())
        resp = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": project["repo_path"],
            "hook_event_name": "SessionStart",
            "agent_name": agent["name"],
        })
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is None, (
            "the real session-start hook must have run consolidation and "
            "evicted the floor memory"
        )

    def test_stock_mode_project_is_untouched(
        self, client, make_project, make_agent, db_session, tmp_path
    ):
        """The gate: a stock-mode project's agent_memories (if any existed,
        which they should not under stock mode, but the gate is what is
        under test) must never be touched by this hook."""
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        project = make_project(repo_path=str(repo))  # memory_mode defaults to stock
        agent = make_agent(project_id=project["id"], role="worker")

        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        memory = AgentMemory(
            agent_id=agent["id"], tier=MemoryTier.working,
            created_session_id=origin.id, body="a box fact at the floor",
        )
        db_session.add(memory)
        db_session.commit()
        memory_id = memory.id
        _elapse(db_session, project_id=project["id"], agent_id=agent["id"], n=91)

        sid = str(uuid.uuid4())
        resp = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": project["repo_path"],
            "hook_event_name": "SessionStart",
            "agent_name": agent["name"],
        })
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is not None, (
            "a stock-mode project must never have consolidation run against it"
        )

    def test_no_resolved_agent_does_not_500(self, client, make_project, tmp_path):
        """No agent_name in the payload and no marker file - handle_session_
        start falls back to TL-overhead attribution or None. Either way this
        must return 200, never 500, same contract as every other hook path."""
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        project = make_project(repo_path=str(repo))

        sid = str(uuid.uuid4())
        resp = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": project["repo_path"],
            "hook_event_name": "SessionStart",
        })
        assert resp.status_code == 200, resp.text

    def test_a_consolidation_failure_never_returns_500(
        self, client, make_project, make_agent, db_session, tmp_path, monkeypatch
    ):
        """The hook's own hard contract (module docstring, hooks.py: "These
        endpoints must NEVER return 5xx") must survive a bug in
        consolidate_agent, not just a bug in the rest of the handler."""
        from app.services import memory_consolidate

        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        project = make_project(repo_path=str(repo))
        agent = make_agent(project_id=project["id"], role="worker")
        proj_row = db_session.get(Project, project["id"])
        proj_row.memory_mode = MemoryMode.human_memory
        db_session.commit()

        def _boom(db, *, agent_id):
            raise RuntimeError("consolidation exploded")

        monkeypatch.setattr(memory_consolidate, "consolidate_agent", _boom)

        sid = str(uuid.uuid4())
        resp = client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": project["repo_path"],
            "hook_event_name": "SessionStart",
            "agent_name": agent["name"],
        })
        assert resp.status_code == 200, resp.text
