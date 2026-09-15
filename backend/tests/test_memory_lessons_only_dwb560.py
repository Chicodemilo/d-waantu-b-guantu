# Path: tests/test_memory_lessons_only_dwb560.py
# File: test_memory_lessons_only_dwb560.py
# Created: 2026-09-15
# Purpose: DWB-560: memory.md holds durable lessons only. Proves session-complete writes no narration into the file (no summary, no token count, nothing at all without lessons) and that the inline memory_usage_rules served by identify and spawn-prepare state the lessons-only rule with its exclusion examples.
# Caller: pytest
# Callees: POST /api/agents/{id}/session-complete, POST /api/agents/identify, POST /api/agents/spawn-prepare, app.config.memory_rules
# Data In: tmp_path repo, factory project + agent
# Data Out: Assertions on memory.md contents after a wrap-up and on the rules string
# Last Modified: 2026-09-15 (DWB-560)

"""DWB-560 (Miles ruling): ONLY DURABLE LESSONS.

Boring "I did 50 tickets, their names were, their ids are, the time completed
was" is noise. The dwb_sessions row already IS the session record, so memory
carrying it too just burns the 4500-token ceiling and forces condense rewrites
that can summarise a real lesson away.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config.memory_rules import MEMORY_USAGE_RULES


def _memory_path(repo_path, prefix, name):
    return Path(repo_path) / ".dwb/memory" / prefix / name / "memory.md"


@pytest.fixture
def wrap_world(client, tmp_path):
    project = client.post("/api/projects", json={
        "prefix": "LO1", "name": "Lessons Only", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": "Lessoner",
        "role": "backend-worker", "api_key": "lo-1",
    }).json()
    return {"tmp": tmp_path, "agent": agent}


def _wrap(client, w, **body):
    return client.post(
        f"/api/agents/{w['agent']['id']}/session-complete",
        json={"session_id": "sess-lo", **body},
    )


def _memory(w):
    return _memory_path(w["tmp"], "LO1", "Lessoner").read_text()


class TestNarrationNeverReachesMemory:
    def test_summary_is_not_written(self, client, wrap_world):
        w = wrap_world
        r = _wrap(client, w, summary="closed DWB-101, DWB-102 and DWB-103",
                  lessons=["MySQL autogenerate misses enum widenings"])
        assert r.status_code == 200, r.text
        memory = _memory(w)
        assert "MySQL autogenerate misses enum widenings" in memory
        assert "closed DWB-101" not in memory
        assert "summary" not in memory

    def test_token_count_is_not_written(self, client, wrap_world):
        w = wrap_world
        _wrap(client, w, summary="s", tokens_used=1803694, lessons=["a lesson"])
        memory = _memory(w)
        assert "1803694" not in memory
        assert "tokens_used" not in memory

    def test_no_lessons_writes_the_heading_but_no_narration(self, client, wrap_world):
        """DWB-560 + DWB-519: with no lessons the block is the ISO heading and
        nothing else. The heading stays because the write-on-close gate reads it
        as the participation trace, so an agent who simply had no durable lesson
        this sprint is not failed for it. The narration still never lands."""
        w = wrap_world
        r = _wrap(client, w, summary="shipped five tickets today",
                  tokens_used=432100)
        assert r.status_code == 200, r.text
        assert r.json()["bytes_written"] > 0
        memory = _memory(w)
        assert memory.lstrip().startswith("## ")
        assert "shipped five tickets today" not in memory
        assert "432100" not in memory
        assert "- lessons" not in memory

    def test_lessons_keep_their_iso_heading_and_session_id(self, client, wrap_world):
        """The heading survives: it is what the DWB-519 write-on-close gate
        detects, and what makes a lesson locatable in time."""
        w = wrap_world
        r = _wrap(client, w, summary="s", lessons=["one durable thing"])
        memory = _memory(w)
        assert memory.lstrip().startswith("## ")
        assert r.json()["timestamp"] in memory
        assert "sess-lo" in memory

    def test_every_lesson_is_kept(self, client, wrap_world):
        w = wrap_world
        _wrap(client, w, summary="s",
              lessons=["first lesson", "second lesson", "third lesson"])
        memory = _memory(w)
        for lesson in ("first lesson", "second lesson", "third lesson"):
            assert lesson in memory

    def test_repeated_wrapups_append(self, client, wrap_world):
        w = wrap_world
        _wrap(client, w, summary="a", lessons=["lesson A"])
        _wrap(client, w, summary="b", lessons=["lesson B"])
        memory = _memory(w)
        assert "lesson A" in memory and "lesson B" in memory
        assert memory.count("## ") == 2

    def test_lessons_free_wrapup_still_satisfies_the_write_gate(
        self, client, db_session, wrap_world,
    ):
        """The AC that matters: the write-on-close gate must not start failing
        an agent who did everything right. An agent whose ONLY memory activity
        in the window is a session-complete, with no lessons at all, still
        registers a write."""
        from app.models.agent import Agent
        from app.models.project import Project
        from app.services import memory_trace

        w = wrap_world
        before = datetime.now(timezone.utc) - timedelta(minutes=5)
        _wrap(client, w, summary="plenty of narration, nothing learned")

        agent = db_session.get(Agent, w["agent"]["id"])
        project = db_session.get(Project, agent.project_id)
        assert memory_trace.latest_memory_write_at(project, agent) is not None
        assert memory_trace.agent_wrote_since(db_session, agent, before) is True


class TestMemoryUsageRules:
    def test_states_lessons_only(self):
        assert "DURABLE LESSONS ONLY" in MEMORY_USAGE_RULES

    @pytest.mark.parametrize("excluded", [
        "ticket ids", "dates", "counts", "what you shipped", "status narration",
    ])
    def test_names_each_exclusion(self, excluded):
        assert excluded in MEMORY_USAGE_RULES

    def test_says_session_complete_writes_only_lessons(self):
        assert "ONLY your lessons" in MEMORY_USAGE_RULES

    def test_no_longer_promises_an_auto_trim(self):
        """DWB-518 removed the silent trim; the rules used to still promise it."""
        lowered = MEMORY_USAGE_RULES.lower()
        assert "auto-trims" not in lowered
        assert "passive" not in lowered
        assert "REFUSED" in MEMORY_USAGE_RULES

    def test_still_under_the_600_char_cap(self):
        assert len(MEMORY_USAGE_RULES) <= 600

    def test_served_by_identify_and_spawn_prepare(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "LO2", "name": "Rules", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "RuleReader",
            "role": "backend-worker", "api_key": "lo-2",
        })
        ident = client.post("/api/agents/identify", json={
            "role": "backend-worker", "name": "RuleReader",
            "project_prefix": "LO2",
        })
        assert ident.status_code == 200, ident.text
        assert "DURABLE LESSONS ONLY" in ident.json()["memory_usage_rules"]

        spawn = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "RuleReader",
            "project_prefix": "LO2",
        })
        assert spawn.status_code == 200, spawn.text
        assert spawn.json()["memory_usage_rules"] == ident.json()["memory_usage_rules"]
