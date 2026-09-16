# Path: tests/test_condense_write_gate_coupling_dwb564.py
# File: test_condense_write_gate_coupling_dwb564.py
# Created: 2026-09-16
# Purpose: DWB-564 — the DWB-519 write-on-close gate used to read ONLY dated ISO headings in memory.md, and a condense/compact legitimately rewrites that file and drops them (a condensing agent survived only because condense's own stamped heading happened to match; compact, which stamps none, never survived at all). The fix has two independent sources, taking whichever is LATER: agents.last_memory_write_at (set directly by the four write endpoints) and memory.md's own mtime (catches a write that went around them). This file proves both sources matter on their own, that the merge (max) is what neither alone gets right, and that the one real gap the mtime side introduces (scaffold's empty-file touch) is guarded.
# Caller: pytest
# Callees: /api/agents/{id}/memory/{append,condense,compact}, app.services.memory_trace, app.services.agent_memory.scaffold_agent_dir, backend/scripts/backfill_last_memory_write_at.py
# Data In: lat_test DB rows + on-disk memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-16 (DWB-564: final design — column + mtime, take the later of the two)

"""Decision recorded here, per the ticket's AC: the coupling to memory.md's
CONTENT-AS-THE-ONLY-EVIDENCE is removed. memory_trace.effective_last_write_at
= max(agents.last_memory_write_at, memory.md's own mtime). Two prior designs
were built and reverted within this same ticket before landing here - a
column-only design (missed a write that went around the API) and an
mtime-only design (missed nothing about THAT case, but see
TestColumnCatchesWhatMtimeAloneWouldMiss below for why mtime alone isn't
enough either). See the ticket comment for the fuller history; this file
tests the design that shipped.
"""

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import memory_trace


def _mem_path(repo_path, prefix, name) -> Path:
    return Path(repo_path) / ".dwb" / "memory" / prefix / name / "memory.md"


class TestColumnSurvivesContentRewrites:
    """The live scenario Pam found (agent Pam_IND: nine headings, eight
    topic-shaped, one condensed-at), reproduced end-to-end through the real
    condense endpoint, plus its sharper sibling: compact, which stamps no
    heading at all, ever. Under the old design compact was an unconditional
    non-writer read; under the column it just works, with no special-casing
    of what heading (if any) the content carries."""

    def test_condense_to_topic_headings_sets_the_column(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), prefix="COND1")
        agent = make_agent(project_id=project["id"], name="Condy1", role="backend-worker")
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        # DWB-560 shape: a condense that keeps ONLY topic headings, no dated
        # heading of the agent's own making anywhere in the body.
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

        from app.models.agent import Agent as AgentModel

        row = db_session.query(AgentModel).filter(AgentModel.id == agent["id"]).first()
        assert row.last_memory_write_at is not None
        assert memory_trace.agent_wrote_since(db_session, row, since) is True

    def test_compact_which_stamps_no_heading_still_passes_the_gate(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), prefix="COND1C")
        agent = make_agent(project_id=project["id"], name="Condy1c", role="backend-worker")
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        r = client.post(
            f"/api/agents/{agent['id']}/memory/compact",
            json={"file": "memory", "content": "no heading at all, just prose"},
        )
        assert r.status_code == 200, r.text

        path = _mem_path(tmp_path, project["prefix"], agent["name"])
        assert not path.read_text(encoding="utf-8").lstrip().startswith("##")

        from app.models.agent import Agent as AgentModel

        row = db_session.query(AgentModel).filter(AgentModel.id == agent["id"]).first()
        assert memory_trace.agent_wrote_since(db_session, row, since) is True

    def test_gate_survives_the_file_being_gone_entirely(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        """Proof the column is real evidence on its own, not just a mirror
        of mtime: write once through the real API, delete memory.md
        outright, and the gate still passes off the column alone."""
        project = make_project(repo_path=str(tmp_path), prefix="COND1B")
        agent = make_agent(project_id=project["id"], name="Condy1b", role="backend-worker")
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        r = client.post(
            f"/api/agents/{agent['id']}/memory/condense",
            json={"file": "memory", "content": "## Epic routing\nRoute by prefix.\n"},
        )
        assert r.status_code == 200, r.text

        path = _mem_path(tmp_path, project["prefix"], agent["name"])
        path.unlink()
        assert not path.exists()

        from app.models.agent import Agent as AgentModel

        row = db_session.query(AgentModel).filter(AgentModel.id == agent["id"]).first()
        assert memory_trace.agent_wrote_since(db_session, row, since) is True


class TestMtimeCatchesWhatTheColumnAloneWouldMiss:
    """The reason the column can't stand alone: nothing prevents an agent
    from writing memory.md directly with its own Edit/Write tool, bypassing
    every one of our endpoints (and every control they enforce - the
    ceiling, the heading, the redemption check; that's a known, accepted
    gap, tracked separately, not this ticket). The gate asks "did this agent
    write", not "did this agent call our endpoint", so that write must still
    count."""

    def test_direct_disk_write_with_no_api_call_still_passes(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel

        project = make_project(repo_path=str(tmp_path), prefix="OFFAPI1")
        a = make_agent(project_id=project["id"], name="WentAroundIt", role="backend-worker")
        agent = db_session.query(AgentModel).filter(AgentModel.id == a["id"]).first()
        assert agent.last_memory_write_at is None  # never called a write endpoint

        path = _mem_path(tmp_path, project["prefix"], "WentAroundIt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("no heading, no API call, just a direct edit\n", encoding="utf-8")

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is True, (
            "a real write that went around the API is still a write - the "
            "column alone (NULL here) would miss it; mtime must catch it"
        )

    def test_stale_column_and_fresh_offapi_write_takes_the_later_mtime(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        """The specific gap max() closes that a NULL-only fallback would
        not: an agent whose column was set by an API write days ago, who
        then writes directly to disk more recently. A fallback that only
        engages on NULL would read the stale column and miss the newer
        off-API write entirely."""
        from app.models.agent import Agent as AgentModel

        project = make_project(repo_path=str(tmp_path), prefix="OFFAPI2")
        agent_resp = make_agent(project_id=project["id"], name="MondayThenFriday", role="backend-worker")

        # "Monday": a real API write, sets the column to a stale timestamp.
        stale = datetime.now(timezone.utc) - timedelta(days=5)
        r = client.post(
            f"/api/agents/{agent_resp['id']}/memory/append",
            json={"file": "memory", "content": "monday's note"},
        )
        assert r.status_code == 201, r.text
        row = db_session.query(AgentModel).filter(AgentModel.id == agent_resp["id"]).first()
        row.last_memory_write_at = stale
        db_session.commit()

        # "Friday": a direct disk write, bypassing the API, sets only mtime.
        path = _mem_path(tmp_path, project["prefix"], "MondayThenFriday")
        path.write_text("friday's note, written directly\n", encoding="utf-8")

        db_session.refresh(row)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert memory_trace.agent_wrote_since(db_session, row, since) is True, (
            "the fresher off-API write must win over the stale column - a "
            "NULL-only fallback would read the (non-NULL, stale) column and "
            "miss it"
        )


class TestScaffoldTouchGuard:
    """The one real gap the mtime side introduces, found while designing
    the fix: scaffold_agent_dir's first-run `.touch()` creates an EMPTY
    memory.md. Without a guard, an agent scaffolded inside the window would
    read as "wrote just now" purely from being created."""

    def test_freshly_scaffolded_agent_is_not_a_writer(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel
        from app.services.agent_memory import scaffold_agent_dir

        project = make_project(repo_path=str(tmp_path), prefix="SCAF1")
        a = make_agent(project_id=project["id"], name="FreshScaffold", role="backend-worker")

        scaffold_agent_dir(db_session, a["id"])

        path = _mem_path(tmp_path, project["prefix"], "FreshScaffold")
        assert path.is_file()
        assert path.stat().st_size == 0  # confirms the premise: touch(), not write

        agent = db_session.query(AgentModel).filter(AgentModel.id == a["id"]).first()
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is False, (
            "a freshly scaffolded, never-written-to memory.md must not read "
            "as a write just because it was created inside the window"
        )

    def test_after_a_real_write_the_same_agent_passes(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel
        from app.services.agent_memory import scaffold_agent_dir

        project = make_project(repo_path=str(tmp_path), prefix="SCAF2")
        a = make_agent(project_id=project["id"], name="ScaffoldThenWrite", role="backend-worker")
        scaffold_agent_dir(db_session, a["id"])

        r = client.post(
            f"/api/agents/{a['id']}/memory/append",
            json={"file": "memory", "content": "first real note"},
        )
        assert r.status_code == 201, r.text

        agent = db_session.query(AgentModel).filter(AgentModel.id == a["id"]).first()
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is True


class TestPreExistingHistoryNeedsNoMigration:
    """Even before the backfill script runs (or for a row it misses), an
    agent's real history is not lost: the column is NULL, but mtime still
    carries it, so effective_last_write_at falls through correctly with no
    transition step."""

    def test_pre_existing_write_recognized_with_column_still_null(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        project = make_project(
            repo_path=str(tmp_path), prefix="PRE1", force_handoff_md=False,
        )
        pid = project["id"]
        agent = make_agent(project_id=pid, name="PreExisting", role="backend-worker")
        sprint = make_sprint(
            project_id=pid,
            status="active",
            start_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        make_ticket(project_id=pid, sprint_id=sprint["id"], assigned_agent_id=agent["id"])

        when = datetime.now(timezone.utc) - timedelta(hours=2)
        path = _mem_path(tmp_path, project["prefix"], "PreExisting")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"## {when.isoformat(timespec='seconds')}\nold note\n", encoding="utf-8")
        ts = when.timestamp()
        os.utime(path, (ts, ts))

        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, (
            f"a real write predating this column must still be recognized "
            f"via mtime, column still NULL, nothing backfilled: {r.text}"
        )

    def test_pre_existing_write_outside_the_window_still_blocks(
        self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path
    ):
        project = make_project(
            repo_path=str(tmp_path), prefix="PRE2", force_handoff_md=False,
        )
        pid = project["id"]
        agent = make_agent(project_id=pid, name="TooOld", role="backend-worker")
        sprint = make_sprint(
            project_id=pid,
            status="active",
            start_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        make_ticket(project_id=pid, sprint_id=sprint["id"], assigned_agent_id=agent["id"])

        when = datetime.now(timezone.utc) - timedelta(days=4)
        path = _mem_path(tmp_path, project["prefix"], "TooOld")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"## {when.isoformat(timespec='seconds')}\nstale note\n", encoding="utf-8")
        ts = when.timestamp()
        os.utime(path, (ts, ts))

        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400
        assert "TooOld" in r.json()["detail"]


class TestBackfillScript:
    """The backfill isn't required for correctness (mtime already covers a
    pre-existing agent, per the class above) - it makes the column itself
    carry real history rather than starting sparse."""

    def test_backfill_populates_the_column_from_existing_headings(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel
        from scripts.backfill_last_memory_write_at import backfill

        project = make_project(repo_path=str(tmp_path), prefix="BF1")
        a_written = make_agent(project_id=project["id"], name="HadHistory", role="backend-worker")
        a_blank = make_agent(project_id=project["id"], name="NeverWrote", role="backend-worker")

        when = datetime.now(timezone.utc).replace(microsecond=0)
        path = _mem_path(tmp_path, project["prefix"], "HadHistory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"## {when.isoformat()}\nold note\n", encoding="utf-8")

        written_row = db_session.query(AgentModel).filter(AgentModel.id == a_written["id"]).first()
        blank_row = db_session.query(AgentModel).filter(AgentModel.id == a_blank["id"]).first()
        assert written_row.last_memory_write_at is None
        assert blank_row.last_memory_write_at is None

        report = backfill(db_session, dry_run=False)
        assert report["backfilled"] >= 1
        db_session.refresh(written_row)
        db_session.refresh(blank_row)

        assert written_row.last_memory_write_at is not None
        assert abs((written_row.last_memory_write_at.replace(tzinfo=timezone.utc) - when).total_seconds()) < 2
        assert blank_row.last_memory_write_at is None  # correct: no heading anywhere

    def test_backfill_dry_run_writes_nothing(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from app.models.agent import Agent as AgentModel
        from scripts.backfill_last_memory_write_at import backfill

        project = make_project(repo_path=str(tmp_path), prefix="BF2")
        a = make_agent(project_id=project["id"], name="DryRunAgent", role="backend-worker")
        path = _mem_path(tmp_path, project["prefix"], "DryRunAgent")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"## {datetime.now(timezone.utc).isoformat(timespec='seconds')}\nnote\n",
            encoding="utf-8",
        )

        report = backfill(db_session, dry_run=True)
        assert report["backfilled"] >= 1

        row = db_session.query(AgentModel).filter(AgentModel.id == a["id"]).first()
        assert row.last_memory_write_at is None


class TestSprintCloseEndToEnd:
    """Same proof as TestColumnSurvivesContentRewrites, at the sprint-close
    boundary rather than the helper function, so a future change to how
    sprint.py calls memory_trace is also covered."""

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
