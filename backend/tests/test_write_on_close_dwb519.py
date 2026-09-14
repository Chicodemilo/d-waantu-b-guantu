# Path: tests/test_write_on_close_dwb519.py
# File: test_write_on_close_dwb519.py
# Created: 2026-09-14
# Purpose: Tests for the write-on-close gates (DWB-519) - sprint close requires every active participant to have a memory write in the window; explicit DWB-session close requires the TL to have written in the session window; idle/regex closes stay exempt.
# Caller: pytest
# Callees: memory_trace helper, sprint-close + session-close endpoints
# Data In: lat_test DB rows + on-disk memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-14

from datetime import date, datetime, timedelta, timezone

from app.models.agent import Agent
from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.services import memory_trace


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _write_mem(repo_path, prefix, name, when: datetime):
    d = repo_path / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "memory.md").write_text(f"\n## {_iso(when)}\nwrote a note\n", encoding="utf-8")


# ── memory_trace helper ─────────────────────────────────────────────


class TestMemoryTraceHelper:
    def test_missing_file_is_non_writer(self, client, db_session, make_agent, tmp_path):
        project_agent = make_agent(role="backend-worker")
        agent = db_session.get(Agent, project_agent["id"])
        # No memory.md written anywhere.
        assert memory_trace.agent_wrote_since(db_session, agent, None) is False

    def test_in_window_write_detected(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        a = make_agent(project_id=project["id"], name="Nora")
        agent = db_session.get(Agent, a["id"])
        now = datetime.now(timezone.utc)
        _write_mem(tmp_path, project["prefix"], "Nora", now)
        since = now - timedelta(days=2)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is True

    def test_pre_window_write_not_counted(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        a = make_agent(project_id=project["id"], name="Ida")
        agent = db_session.get(Agent, a["id"])
        old = datetime.now(timezone.utc) - timedelta(days=5)
        _write_mem(tmp_path, project["prefix"], "Ida", old)
        since = datetime.now(timezone.utc) - timedelta(days=1)
        assert memory_trace.agent_wrote_since(db_session, agent, since) is False


# ── Sprint close gate ───────────────────────────────────────────────


class TestSprintWriteGate:
    def _setup(self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path, repo=True):
        project = make_project(
            repo_path=str(tmp_path) if repo else None,
            force_handoff_md=False,
        )
        pid = project["id"]
        agent = make_agent(project_id=pid, name="Wanda", role="backend-worker")
        sprint = make_sprint(
            project_id=pid,
            status="active",
            start_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        make_ticket(project_id=pid, sprint_id=sprint["id"], assigned_agent_id=agent["id"])
        return project, sprint

    def test_blocks_and_names_non_writer(self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path):
        project, sprint = self._setup(client, make_project, make_agent, make_sprint, make_ticket, tmp_path)
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "write-on-close gate failed" in detail
        assert "Wanda" in detail

    def test_passes_when_participant_wrote(self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path):
        project, sprint = self._setup(client, make_project, make_agent, make_sprint, make_ticket, tmp_path)
        _write_mem(tmp_path, project["prefix"], "Wanda", datetime.now(timezone.utc))
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_pre_window_write_still_blocks(self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path):
        project, sprint = self._setup(client, make_project, make_agent, make_sprint, make_ticket, tmp_path)
        # Write is older than the sprint start window.
        _write_mem(tmp_path, project["prefix"], "Wanda", datetime.now(timezone.utc) - timedelta(days=4))
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 400
        assert "Wanda" in r.json()["detail"]

    def test_no_repo_path_exempts_gate(self, client, make_project, make_agent, make_sprint, make_ticket, tmp_path):
        # With no repo_path there is nowhere to write; the gate must skip rather
        # than block every close.
        project, sprint = self._setup(
            client, make_project, make_agent, make_sprint, make_ticket, tmp_path, repo=False
        )
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"


# ── DWB session close gate ──────────────────────────────────────────


class TestSessionWriteGate:
    def _open(self, db_session, pid, hours_ago=1):
        s = DwbSession(
            project_id=pid,
            opened_at=datetime.utcnow() - timedelta(hours=hours_ago),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(s)
        db_session.flush()
        return s

    def _close(self, client, sid, method, reason="explicit", headline="did the thing"):
        body = {"close_method": method, "close_reason": reason}
        if headline is not None:
            body["headline"] = headline
        return client.post(f"/api/sessions/{sid}/close", json=body)

    def test_explicit_close_blocks_when_tl_has_no_write(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="ArchieT", role="team-lead")
        s = self._open(db_session, project["id"])
        r = self._close(client, s.id, "ai_confident")
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "Write-on-close" in detail
        assert "ArchieT" in detail

    def test_explicit_close_passes_when_tl_wrote(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="ArchieT", role="team-lead")
        s = self._open(db_session, project["id"])
        _write_mem(tmp_path, project["prefix"], "ArchieT", datetime.now(timezone.utc))
        r = self._close(client, s.id, "ai_confident")
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None

    def test_slash_close_blocks_when_tl_has_no_write(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="ArchieT", role="team-lead")
        s = self._open(db_session, project["id"])
        # slash does not require a headline; the 422 must be the write gate.
        r = self._close(client, s.id, "slash", headline=None)
        assert r.status_code == 422
        assert "Write-on-close" in r.json()["detail"]

    def test_idle_timeout_is_exempt(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="ArchieT", role="team-lead")
        s = self._open(db_session, project["id"])
        # No TL write, but idle close fires on a dead session and stays exempt.
        r = self._close(client, s.id, "idle_timeout", reason="idle", headline=None)
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None

    def test_regex_sweeper_is_exempt(self, client, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="ArchieT", role="team-lead")
        s = self._open(db_session, project["id"])
        r = self._close(client, s.id, "regex", reason="explicit", headline=None)
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None
