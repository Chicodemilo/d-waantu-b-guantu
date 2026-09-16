# Path: tests/test_condense_write_gate_coupling_dwb564.py
# File: test_condense_write_gate_coupling_dwb564.py
# Created: 2026-09-16
# Purpose: DWB-564 — pin the coupling between the DWB-519 write-on-close gate (memory_trace.agent_wrote_since, reads dated ISO headings in memory.md) and the condense endpoint's server-stamped heading. Condensing legitimately replaces every dated heading with topic headings the gate's regex does not match (DWB-560's whole point); a condensing agent survives the gate today ONLY because condense stamps its own "## <ISO> - condensed" heading. If that stamp's shape ever changes, this coupling breaks silently and blames an innocent agent.
# Caller: pytest
# Callees: /api/agents/{id}/memory/condense, app.services.memory_trace
# Data In: lat_test DB rows + on-disk memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-16 (DWB-564)

"""Decision recorded here, per the ticket's AC: the coupling is KEPT for this
pass, not removed. Removing it (a write-path signal the memory service does
not own) is a bigger change that DWB-519 deliberately avoided once already;
see the module comment in memory_trace.py and the team-lead thread on
DWB-564 for the read on whether it should still be decoupled later. This
file is the "make the dependency explicit and provable" half of the AC."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import memory_trace


def _mem_path(repo_path, prefix, name) -> Path:
    return Path(repo_path) / ".dwb" / "memory" / prefix / name / "memory.md"


class TestCondenseKeepsTheAgentEligible:
    """The live scenario Pam found (agent Pam_IND: nine headings, eight
    topic-shaped, one condensed-at). Reproduced end-to-end through the real
    condense endpoint, not a hand-written fixture, so this pins the actual
    code path rather than a guess at its shape."""

    def test_condense_to_topic_headings_still_satisfies_the_gate(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), prefix="COND1")
        agent = make_agent(project_id=project["id"], name="Condy1", role="backend-worker")
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        # A condense that keeps ONLY topic headings — exactly the DWB-560
        # shape ("drop session narration") that started this ticket. No
        # dated heading of the agent's own making anywhere in the body.
        topic_only_rewrite = (
            "## Epic routing\nRoute by prefix, not by title match.\n\n"
            "## Story format (LAW)\nOne story per acceptance criterion.\n\n"
            "## Memory mechanics\nCondense before the ceiling refuses a write.\n"
        )
        r = client.post(
            f"/api/agents/{agent['id']}/memory/condense",
            json={"file": "memory", "content": topic_only_rewrite},
        )
        assert r.status_code == 200, r.text

        path = _mem_path(tmp_path, project["prefix"], agent["name"])
        text = path.read_text(encoding="utf-8")
        assert "## Epic routing" in text  # the rewrite landed
        assert "condensed" in text  # and the stamped heading is what's left that's dated

        # agent_wrote_since only needs the ORM row (for project_id + name) to
        # find the file — same session the client fixture writes through
        # (DWB-314's per-test transaction), so this exercises the exact code
        # path sprint-close/session-close call.
        from app.models.agent import Agent as AgentModel

        row = db_session.query(AgentModel).filter(AgentModel.id == agent["id"]).first()
        assert memory_trace.agent_wrote_since(db_session, row, since) is True, (
            "a condense that leaves only topic headings should still pass "
            "the gate, because condense_memory stamps its own dated "
            "heading — if this assertion goes False, the stamp shape "
            "changed and every condensing agent will fail sprint/session "
            "close as a silent non-writer"
        )


class TestWithoutTheStampTheGateFails:
    """The fragility made concrete: the SAME topic-only content, written by
    hand with no condensed-at stamp, fails the gate. This is what happens
    to every condensing agent the moment condense_memory stops adding one —
    proving the pass above is load-bearing on that stamp, not incidental."""

    def test_topic_headings_with_no_dated_stamp_read_as_non_writer(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel

        project = make_project(repo_path=str(tmp_path), prefix="COND2")
        a = make_agent(project_id=project["id"], name="Condy2", role="backend-worker")
        agent = db_session.query(AgentModel).filter(AgentModel.id == a["id"]).first()

        path = _mem_path(tmp_path, project["prefix"], "Condy2")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same shape as the passing test above, minus the stamped heading —
        # i.e. what a condense would produce if it stopped stamping one.
        path.write_text(
            "## Epic routing\nRoute by prefix, not by title match.\n\n"
            "## Story format (LAW)\nOne story per acceptance criterion.\n\n"
            "## Memory mechanics\nCondense before the ceiling refuses a write.\n",
            encoding="utf-8",
        )
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is False, (
            "topic-only headings with no ISO stamp must NOT satisfy the gate "
            "in this test — if they do, something changed in _HEADING_RE and "
            "the passing test above is no longer testing what it claims to"
        )


class TestSprintCloseEndToEnd:
    """Same pin, at the sprint-close boundary rather than the helper
    function, so a future change to how sprint.py calls memory_trace is
    also covered."""

    def test_sprint_closes_after_condense_to_topic_headings(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        project = make_project(
            repo_path=str(tmp_path), prefix="COND3", force_handoff_md=False,
        )
        pid = project["id"]
        agent = make_agent(project_id=pid, name="Condy3", role="backend-worker")
        sprint = make_sprint(
            project_id=pid,
            status="active",
            start_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        make_ticket(project_id=pid, sprint_id=sprint["id"], assigned_agent_id=agent["id"])

        r = client.post(
            f"/api/agents/{agent['id']}/memory/condense",
            json={
                "file": "memory",
                "content": "## Epic routing\nRoute by prefix.\n",
            },
        )
        assert r.status_code == 200, r.text

        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, (
            f"sprint close should pass for an agent who condensed to topic "
            f"headings this window: {r.text}"
        )
