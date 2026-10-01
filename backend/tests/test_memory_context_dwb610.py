# Path: tests/test_memory_context_dwb610.py
# File: test_memory_context_dwb610.py
# Created: 2026-09-30 (DWB-610)
# Purpose: Guard the wiring DWB-610 exists to close - an agent in human_memory
#          mode must receive assembled scored memory (band 8-10 full text,
#          5-7 compressed) at BOTH spawn and SessionStart, not the sealed
#          pointer, whenever there is anything scored to serve. The pointer
#          fallback (nothing scored yet) must still work, because the seal
#          itself (DWB-589) is not what this ticket touches.
# Caller: pytest
# Callees: app/services/memory_context, POST /api/agents/spawn-prepare,
#          POST /api/hooks/session-start
# Data In: factory projects/agents, agent_memories rows, dwb/hook sessions
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-610)

"""DWB-610, the biggest gap the 2026-09-30 human_memory audit found.

The two classes at the bottom are the acceptance test: a real HTTP call to the
real endpoint an agent's spawn or SessionStart actually goes through, not a
direct call into the renderer (`memory_format.render` already had its own
tests and was never the gap - nothing called it here was). `TestAssemble*`
above them is the unit-level companion, kept because a transcript-level
failure is harder to localize without it.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.services import memory_context
from app.services.memory_mode import STOCK_MEMORY_SEALED_POINTER


def _closed_session(db, project_id, *, hours_ago=1):
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


def _elapse(db, *, project_id, agent_id, n):
    """`n` closed DWB sessions this agent lived through, each with a linked
    HookSession row - the shape sessions_since_reinforced's join requires.
    Mirrors tests/test_memory_score_dwb585.py::_elapse."""
    base = datetime.utcnow() - timedelta(days=400)
    sessions = [
        DwbSession(
            project_id=project_id,
            opened_at=base + timedelta(hours=i),
            closed_at=base + timedelta(hours=i, minutes=30),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
        )
        for i in range(n)
    ]
    db.add_all(sessions)
    db.flush()
    db.add_all(
        [
            HookSession(
                session_id=f"dwb610-bulk-{agent_id}-{i}",
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=s.id,
                total_tokens=0,
            )
            for i, s in enumerate(sessions)
        ]
    )
    db.flush()
    return sessions


def _memory(db, *, agent_id, tier, body, created_session_id):
    row = AgentMemory(
        agent_id=agent_id, tier=tier, body=body, created_session_id=created_session_id
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Unit level: the module's own band logic, in isolation.
# ---------------------------------------------------------------------------


class TestAssembleSessionContext:
    def test_nothing_scored_returns_none(self, db_session, make_project, make_agent):
        """An agent with zero agent_memories rows has nothing to assemble.
        None (not an empty string) is the caller's cue to fall back to the
        sealed pointer rather than inject a blank block."""
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        assert memory_context.assemble_session_context(db_session, agent) is None

    def test_full_band_rendered_as_full_text(
        self, db_session, make_project, make_agent
    ):
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])
        origin = _closed_session(db_session, project["id"], hours_ago=1)
        marker = "MARKER-FULL-TEXT-9f3a"
        _memory(
            db_session,
            agent_id=agent.id,
            tier=MemoryTier.core,
            body=f"- {marker}: never guess a peer's contract",
            created_session_id=origin.id,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert marker in context
        assert "full text (score 8-10)" in context

    def test_compressed_band_gets_one_line_not_the_full_body(
        self, db_session, make_project, make_agent
    ):
        """WORKING at 8 sessions elapsed scores 6 (bucket 6-14), band
        compressed. Only the first line should survive into the injected
        text - the whole point of the band."""
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])
        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        first_line_marker = "MARKER-COMPRESSED-HEAD-7b2c"
        second_line_marker = "MARKER-COMPRESSED-TAIL-MUST-NOT-SURVIVE"
        _memory(
            db_session,
            agent_id=agent.id,
            tier=MemoryTier.working,
            body=f"- {first_line_marker}\n  {second_line_marker}",
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project["id"], agent_id=agent.id, n=8)

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert first_line_marker in context
        assert second_line_marker not in context
        assert "compressed (score 5-7)" in context

    def test_demotion_band_is_counted_not_quoted(
        self, db_session, make_project, make_agent
    ):
        """WORKING at 20 sessions elapsed scores 4 (bucket 15-30), band
        demotion_candidate. Spec section 3's boundary: this is consolidation's
        business, not the agent's reading material. The context may say HOW
        MANY are flagged; it must not quote the body."""
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])
        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        demote_marker = "MARKER-DEMOTE-MUST-NOT-APPEAR"
        _memory(
            db_session,
            agent_id=agent.id,
            tier=MemoryTier.working,
            body=demote_marker,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project["id"], agent_id=agent.id, n=20)

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert demote_marker not in context
        assert "flagged for consolidation" in context
        assert "/memory/scored" in context

    def test_eviction_band_is_counted_not_quoted(
        self, db_session, make_project, make_agent
    ):
        """WORKING at 91+ sessions elapsed scores 1 (the open bucket), band
        last_consolidation. Same boundary as demotion: counted, not quoted."""
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])
        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        evict_marker = "MARKER-EVICT-MUST-NOT-APPEAR"
        _memory(
            db_session,
            agent_id=agent.id,
            tier=MemoryTier.working,
            body=evict_marker,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project["id"], agent_id=agent.id, n=91)

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert evict_marker not in context
        assert "flagged for consolidation" in context
        assert "/memory/scored" in context

    def test_no_full_or_compressed_but_flagged_still_produces_context(
        self, db_session, make_project, make_agent
    ):
        """A project with only demote/evict candidates and nothing in the top
        two bands still gets a context block (the flagged-count section),
        rather than falling back to the pointer as if nothing were scored."""
        from app.models.agent import Agent

        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])
        origin = _closed_session(db_session, project["id"], hours_ago=1000)
        _memory(
            db_session,
            agent_id=agent.id,
            tier=MemoryTier.working,
            body="stale lesson",
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project["id"], agent_id=agent.id, n=91)

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "flagged for consolidation" in context


# ---------------------------------------------------------------------------
# Transcript level: the real endpoints an agent's spawn / SessionStart go
# through. This is the acceptance bar DWB-610 was filed against - a unit test
# of the renderer proves nothing, because the renderer was never the gap.
# ---------------------------------------------------------------------------


class TestSpawnPrepareServesAssembledMemory:
    def test_full_text_reaches_the_spawn_prepare_response(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        agent = make_agent(project_id=project["id"], name="Wanda", role="backend-worker")
        origin = _closed_session(db_session, project["id"], hours_ago=1)
        marker = "MARKER-SPAWN-FULL-TEXT-4c1d"
        _memory(
            db_session,
            agent_id=agent["id"],
            tier=MemoryTier.core,
            body=f"- {marker}",
            created_session_id=origin.id,
        )
        db_session.commit()

        r = client.post(
            "/api/agents/spawn-prepare",
            json={"role": "backend-worker", "name": "Wanda", "project_prefix": project["prefix"]},
        )

        assert r.status_code == 200
        body = r.json()
        assert marker in body["memory_full"]
        # Proves this is assembled content, not the sealed pointer that would
        # otherwise satisfy a naive "memory_full is non-empty" check.
        assert "hard rule 1" not in body["memory_full"]
        assert body["memory_full"] != STOCK_MEMORY_SEALED_POINTER

    def test_no_scored_memory_still_falls_back_to_the_pointer(
        self, client, make_project, make_agent, tmp_path
    ):
        """The seal DWB-589 built is untouched: an agent with nothing scored
        yet still gets told where its memory lives, not an empty block."""
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        make_agent(project_id=project["id"], name="Newbie", role="backend-worker")

        r = client.post(
            "/api/agents/spawn-prepare",
            json={"role": "backend-worker", "name": "Newbie", "project_prefix": project["prefix"]},
        )

        assert r.status_code == 200
        assert r.json()["memory_full"] == STOCK_MEMORY_SEALED_POINTER

    def test_stock_project_is_unaffected(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        """A stock-mode project's spawn keeps serving raw memory.md verbatim -
        DWB-610 only changes what happens under human_memory."""
        project = make_project(repo_path=str(tmp_path))
        agent = make_agent(project_id=project["id"], name="Stocky", role="backend-worker")
        mem_dir = tmp_path / ".dwb" / "memory" / project["prefix"] / "Stocky"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "memory.md").write_text("# Memory - Stocky\n- an old lesson\n")

        r = client.post(
            "/api/agents/spawn-prepare",
            json={"role": "backend-worker", "name": "Stocky", "project_prefix": project["prefix"]},
        )

        assert r.status_code == 200
        assert "an old lesson" in r.json()["memory_full"]


class TestSessionStartServesAssembledMemory:
    def test_full_text_reaches_session_start_additional_context(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        tl = make_agent(project_id=project["id"], name="ArchieTen", role="team-lead")
        origin = _closed_session(db_session, project["id"], hours_ago=1)
        marker = "MARKER-SESSIONSTART-FULL-TEXT-8e2f"
        _memory(
            db_session,
            agent_id=tl["id"],
            tier=MemoryTier.core,
            body=f"- {marker}",
            created_session_id=origin.id,
        )
        db_session.commit()

        r = client.post(
            "/api/hooks/session-start",
            json={"session_id": "dwb610-ss-1", "cwd": str(project["repo_path"])},
        )

        assert r.status_code == 200
        injected = r.json()["hookSpecificOutput"]["additionalContext"]
        assert marker in injected
        assert "hard rule 1" not in injected

    def test_no_scored_memory_still_falls_back_to_the_pointer(
        self, client, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        make_agent(project_id=project["id"], name="ArchieEleven", role="team-lead")

        r = client.post(
            "/api/hooks/session-start",
            json={"session_id": "dwb610-ss-2", "cwd": str(project["repo_path"])},
        )

        assert r.status_code == 200
        injected = r.json()["hookSpecificOutput"]["additionalContext"]
        assert injected == STOCK_MEMORY_SEALED_POINTER
