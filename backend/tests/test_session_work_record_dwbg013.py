# Path: tests/test_session_work_record_dwbg013.py
# File: test_session_work_record_dwbg013.py
# Created: 2026-06-25
# Purpose: Backend tests for the DWBG-013 session work-record evidence gatherer —
#          git commits + bounded diffs over the window (PRIMARY evidence), tool_actions,
#          tickets completed in window, transcript slice (agent/tool turns only, NEVER
#          user prompts), size bounds + truncation flags, and the never-raises contract.
# Caller: pytest
# Callees: app.services.session_work_record (build_work_record, has_evidence),
#          app.models.dwb_session / hook_session / tool_action, a real tmp git repo
# Data In: per-test db_session + make_project/make_ticket fixtures + tmp_path git repo
# Data Out: assertions on the structured work record dict
# Last Modified: 2026-06-25

"""DWBG-013 — session work-record evidence gatherer, backend coverage."""

import json
import subprocess
from datetime import datetime, timedelta

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.models.tool_action import ToolAction
from app.services.session_work_record import build_work_record, has_evidence


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


def _open_session(db_session, project_id, *, opened_at=None):
    row = DwbSession(
        project_id=project_id,
        opened_at=opened_at or (_naive_now() - timedelta(hours=1)),
        open_method=DwbOpenMethod.regex,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _init_repo(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Devin")
    return repo


# ---------------------------------------------------------------------------
# Git evidence — the PRIMARY signal
# ---------------------------------------------------------------------------


class TestGitEvidence:
    def test_commits_and_diff_in_window(self, db_session, make_project, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        proj = make_project(repo_path=str(repo))
        # A commit with a recognizable code symbol + file:line target.
        (repo / "DataManipulation.php").write_text(
            "<?php\nfunction fetchCFCRRawData() {\n  return 1;\n}\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "DWBG-013 add fetchCFCRRawData")

        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())

        git = rec["git"]
        assert git["repo_available"] is True
        assert len(git["commits"]) == 1
        assert "fetchCFCRRawData" in git["commits"][0]["subject"]
        assert "DataManipulation.php" in git["files_changed"]
        # The diff carries the real symbol so the summarizer can ground on it.
        assert "fetchCFCRRawData" in git["diff"]

    def test_no_repo_path_is_graceful(self, db_session, make_project):
        proj = make_project()  # no repo_path
        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())
        assert rec["git"]["repo_available"] is False
        assert rec["git"]["commits"] == []
        assert rec["git"]["note"]  # explains why unavailable

    def test_nonexistent_repo_path_does_not_raise(self, db_session, make_project):
        proj = make_project(repo_path="/no/such/path/here")
        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())
        assert rec["git"]["repo_available"] is False

    def test_diff_is_bounded_and_marks_truncation(
        self, db_session, make_project, tmp_path
    ):
        repo = _init_repo(tmp_path / "repo")
        proj = make_project(repo_path=str(repo))
        # A single very large file blows past the per-file + total line caps.
        big = "\n".join(f"line_{i} = {i}" for i in range(5000))
        (repo / "huge.py").write_text(big + "\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "huge file")

        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())
        git = rec["git"]
        assert git["diff_truncated"] is True
        assert git["note"]
        # The diff is capped well under the raw 5000-line file.
        assert len(git["diff"].splitlines()) <= 1400


# ---------------------------------------------------------------------------
# Other evidence slices
# ---------------------------------------------------------------------------


class TestOtherEvidence:
    def test_tool_actions_linked_to_session(self, db_session, make_project):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        db_session.add(ToolAction(
            dwb_session_id=session.id, tool_name="Edit",
            event_type="file_edit", target="app/foo.py",
        ))
        db_session.add(ToolAction(
            dwb_session_id=session.id, tool_name="Write",
            event_type="file_write", target="app/bar.py",
        ))
        db_session.flush()
        rec = build_work_record(db_session, session, now=_naive_now())
        targets = {a["target"] for a in rec["tool_actions"]}
        assert {"app/foo.py", "app/bar.py"} <= targets

    def test_tickets_completed_in_window(
        self, db_session, make_project, make_ticket
    ):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        t = make_ticket(project_id=proj["id"], title="Widen money columns")
        # Mark completed inside the window via the model row.
        from app.models.ticket import Ticket, TicketStatus
        row = db_session.get(Ticket, t["id"])
        row.status = TicketStatus.done
        row.completed_at = _naive_now()
        db_session.flush()

        rec = build_work_record(db_session, session, now=_naive_now())
        keys = {tc["ticket_key"] for tc in rec["tickets_completed"]}
        assert t["ticket_key"] in keys


# ---------------------------------------------------------------------------
# Transcript privacy — agent/tool turns only, NEVER user prompts
# ---------------------------------------------------------------------------


class TestTranscriptPrivacy:
    def _write_transcript(self, path, lines):
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    def test_user_turns_excluded_agent_turns_kept(
        self, db_session, make_project, tmp_path
    ):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        tpath = tmp_path / "transcript.jsonl"
        self._write_transcript(tpath, [
            {"role": "user", "content": "SECRET USER PROMPT do not leak"},
            {"role": "assistant", "content": "Refactored fetchCFCRRawData()."},
            {"type": "human", "content": "another user line leak"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Widened columns to decimal(17,6)."},
            ]},
        ])
        db_session.add(HookSession(
            session_id="sess-x", project_id=proj["id"],
            dwb_session_id=session.id, transcript_path=str(tpath),
            start_time=_naive_now(),
        ))
        db_session.flush()

        rec = build_work_record(db_session, session, now=_naive_now())
        excerpt = rec["transcript_excerpt"]
        assert "Refactored fetchCFCRRawData()." in excerpt
        assert "decimal(17,6)" in excerpt
        # HARD privacy rule: no user-typed text in the record.
        assert "SECRET USER PROMPT" not in excerpt
        assert "another user line leak" not in excerpt

    def test_missing_transcript_file_is_graceful(
        self, db_session, make_project
    ):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        db_session.add(HookSession(
            session_id="sess-y", project_id=proj["id"],
            dwb_session_id=session.id, transcript_path="/no/such/transcript.jsonl",
            start_time=_naive_now(),
        ))
        db_session.flush()
        rec = build_work_record(db_session, session, now=_naive_now())
        assert rec["transcript_excerpt"] == ""


# ---------------------------------------------------------------------------
# Contract + has_evidence
# ---------------------------------------------------------------------------


class TestContract:
    def test_record_shape(self, db_session, make_project):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())
        for key in (
            "session_id", "project", "window", "totals", "git",
            "tool_actions", "tickets_completed", "transcript_excerpt",
            "transcript_truncated",
        ):
            assert key in rec
        assert rec["session_id"] == session.id

    def test_has_evidence_false_when_empty(self, db_session, make_project):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        rec = build_work_record(db_session, session, now=_naive_now())
        assert has_evidence(rec) is False

    def test_has_evidence_true_with_tool_actions(self, db_session, make_project):
        proj = make_project()
        session = _open_session(db_session, proj["id"])
        db_session.add(ToolAction(
            dwb_session_id=session.id, tool_name="Edit",
            event_type="file_edit", target="x.py",
        ))
        db_session.flush()
        rec = build_work_record(db_session, session, now=_naive_now())
        assert has_evidence(rec) is True
