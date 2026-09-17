# Path: tests/test_session_complete_dwb582.py
# File: test_session_complete_dwb582.py
# Created: 2026-09-17
# Purpose: DWB-582 - the wrap-up endpoint must not refuse callers who are filing
#          correctly. Two independent causes, one test class each: a subagent
#          cannot know its own session id, and `lessons` as a bare string.
# Caller: pytest
# Callees: POST /api/agents/{id}/session-complete
# Data In: pytest fixtures + a temp repo_path for the memory dir
# Data Out: assertions
# Last Modified: 2026-09-17

"""A failure whose workaround always works is a failure nobody reports.

Every worker who wrapped up on 2026-09-16 fell back to the append path because
session-complete rejected them. The lessons still landed, so nothing the next
session needs was lost, and that is exactly why it went unnoticed: the summary
and token figures a wrap-up writes never arrived, and no one could see it.

TWO SEPARATE CAUSES, deliberately in separate classes. They were conflated
because the same fallback rescued both, and a single test would only ever have
covered one of them.
"""

import pytest

from app.models.hook_session import HookSession, HookSessionStatus


@pytest.fixture
def wrap_agent(client, make_project, make_agent, tmp_path):
    repo = tmp_path / "repo582"
    repo.mkdir()
    project = make_project(repo_path=str(repo))
    agent = make_agent(project_id=project["id"], role="backend-worker")
    return {"project": project, "agent": agent, "repo": repo}


class TestCauseOneSessionId:
    """A subagent cannot see its own Claude Code session id."""

    def test_wrap_up_without_a_session_id_is_accepted(self, client, wrap_agent):
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "did the thing",
                              "lessons": ["a durable lesson"]},
                        headers={"X-Agent-ID": str(aid)})
        assert r.status_code == 200, r.text
        assert r.json()["bytes_written"] > 0

    def test_the_server_resolves_the_id_from_the_agents_own_session(
        self, client, db_session, wrap_agent
    ):
        """Same linkage token attribution runs on, so it cannot drift from it."""
        aid = wrap_agent["agent"]["id"]
        db_session.add(HookSession(
            session_id="aWrapper-582", agent_id=aid,
            project_id=wrap_agent["project"]["id"], total_tokens=0,
            status=HookSessionStatus.completed,
        ))
        db_session.flush()

        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "s", "lessons": ["l"]},
                        headers={"X-Agent-ID": str(aid)})

        assert r.status_code == 200
        assert r.json()["session_id"] == "aWrapper-582"

    def test_an_unresolvable_session_still_lands_the_wrap_up(
        self, client, wrap_agent
    ):
        """Never guess. A wrap-up attributed to the WRONG session is worse than
        one attributed to none, and the lessons are the part that matters."""
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "s", "lessons": ["l"]},
                        headers={"X-Agent-ID": str(aid)})

        assert r.status_code == 200
        assert r.json()["session_id"] is None
        memory = (wrap_agent["repo"] / ".dwb" / "memory").rglob("memory.md")
        text = next(memory).read_text()
        assert "session None" not in text, (
            "an unresolved session wrote a heading that reads like a real id"
        )

    def test_an_explicit_session_id_is_still_honoured(self, client, wrap_agent):
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"session_id": "explicit-582", "summary": "s",
                              "lessons": ["l"]},
                        headers={"X-Agent-ID": str(aid)})
        assert r.json()["session_id"] == "explicit-582"


class TestCauseTwoLessonsShape:
    """Unrelated to session ids entirely."""

    def test_lessons_as_a_bare_string_is_accepted(self, client, wrap_agent):
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "s", "lessons": "one lesson, as a string"},
                        headers={"X-Agent-ID": str(aid)})

        assert r.status_code == 200, r.text
        memory = (wrap_agent["repo"] / ".dwb" / "memory").rglob("memory.md")
        assert "one lesson, as a string" in next(memory).read_text()

    def test_lessons_as_a_list_still_works(self, client, wrap_agent):
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "s", "lessons": ["first", "second"]},
                        headers={"X-Agent-ID": str(aid)})
        assert r.status_code == 200
        text = next((wrap_agent["repo"] / ".dwb" / "memory").rglob("memory.md")).read_text()
        assert "first" in text and "second" in text

    def test_a_wrong_shape_says_what_it_wants(self, client, wrap_agent):
        """AC 2's real point. A 422 naming a pydantic type is not something a
        worker can act on; the message has to name the shape."""
        aid = wrap_agent["agent"]["id"]
        r = client.post(f"/api/agents/{aid}/session-complete",
                        json={"summary": "s", "lessons": {"not": "a list"}},
                        headers={"X-Agent-ID": str(aid)})

        assert r.status_code == 422
        detail = str(r.json())
        assert "list of strings" in detail and "single string" in detail, detail
        assert "list_type" not in detail, (
            "still reporting the pydantic internal instead of the shape wanted"
        )
