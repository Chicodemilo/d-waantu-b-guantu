# Path: tests/test_hook_user_prompt.py
# File: test_hook_user_prompt.py
# Created: 2026-06-09
# Purpose: Tests for the DWB-344 UserPromptSubmit fast-path open detection endpoint
# Caller: pytest
# Callees: POST /api/hooks/user-prompt, app.services.hook_tracking.handle_user_prompt,
#          app.services.dwb_session.get_active_session, app.models.dwb_session.DwbSession
# Data In: factory fixtures (make_project), in-memory hook payloads
# Data Out: Assertions on response bodies and DwbSession rows
# Last Modified: 2026-06-09

"""DWB-344: UserPromptSubmit fast-path open detection.

Background: SessionStart fires before the user's first message lands in the
transcript, so the Layer-1 regex scan in handle_session_start misses on the
first hook. DWB-343 retries on SessionEnd; DWB-344 is the instant sibling.

Claude Code's UserPromptSubmit hook ships the raw user prompt in the payload,
so we can match against the open-phrase regex catalogue synchronously and
open the DWB session the moment the user submits.

These tests pin the endpoint contract:

  1. POST with a matching open phrase + no active session opens a session via
     regex, open_method=regex, response body advertises status="opened".
  2. POST with a non-matching prompt is a silent noop; no row created.
  3. POST while a session is already open is a noop; single-active invariant
     holds, the seeded ai_confident session is preserved untouched.
  4. POST with a missing/unresolvable cwd is a noop with HTTP 200; the
     endpoint never 5xx's and never creates a row.

The endpoint MUST always return HTTP 200 (the hook contract). All tests drive
the public POST /api/hooks/user-prompt route end-to-end.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.dwb_session import DwbOpenMethod, DwbSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hook_project(make_project, tmp_path):
    """Project with a deterministic repo_path used for cwd resolution."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return make_project(repo_path=str(repo))


def _active_dwb_session_for(db_session, project_id) -> DwbSession | None:
    """Return the single open DwbSession for project_id, or None."""
    return db_session.execute(
        select(DwbSession)
        .where(DwbSession.project_id == project_id)
        .where(DwbSession.closed_at.is_(None))
    ).scalar_one_or_none()


def _all_dwb_sessions_for(db_session, project_id) -> list[DwbSession]:
    return list(db_session.execute(
        select(DwbSession).where(DwbSession.project_id == project_id)
    ).scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUserPromptOpensViaRegexFastPath:
    """DWB-344: handle_user_prompt opens immediately on a matching prompt."""

    def test_opens_dwb_session_when_prompt_matches_open_phrase(
        self, client, hook_project, db_session,
    ):
        """Case 1: matching prompt + no active session opens via regex."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        assert _active_dwb_session_for(db_session, pid) is None

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "you are archie, read the playbook",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["status"] == "opened", body
        assert "open_phrase" in body
        assert "playbook" in body["open_phrase"].lower()

        active = _active_dwb_session_for(db_session, pid)
        assert active is not None, "expected a DWB session to be opened"
        assert active.open_method == DwbOpenMethod.regex
        assert active.open_phrase is not None
        assert "playbook" in active.open_phrase.lower()

    def test_noop_when_prompt_has_no_open_phrase(
        self, client, hook_project, db_session,
    ):
        """Case 2: prompt that does not match OPEN_PATTERNS is a noop."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "what's the status of the deploy",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_phrase_match"

        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_noop_when_dwb_session_already_open(
        self, client, hook_project, db_session,
    ):
        """Case 3: matching prompt while a session is already open is a noop.

        Seed an ai_confident session, then fire the hook. The endpoint must
        observe the active session and noop. The seeded row stays untouched,
        single-active invariant holds (one open row, open_method unchanged).
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        r0 = client.post("/api/sessions/open", json={
            "project_id": pid,
            "opened_at": opened_at,
            "open_method": "ai_confident",
            "open_phrase": "seeded by ai_confident",
        })
        assert r0.status_code == 201, r0.text
        seeded_id = r0.json()["id"]

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "you are archie, read the playbook",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "already_open"

        db_session.expire_all()
        rows = db_session.execute(
            select(DwbSession)
            .where(DwbSession.project_id == pid)
            .where(DwbSession.closed_at.is_(None))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == seeded_id
        assert rows[0].open_method == DwbOpenMethod.ai_confident

    def test_noop_when_cwd_does_not_resolve_to_project(
        self, client, hook_project, db_session,
    ):
        """Case 4: bad/missing cwd is a clean noop, no crash, no row.

        Archie's brief described this as "status=error", but the actual
        contract in handle_user_prompt is that an unresolvable cwd returns
        ``{"status": "noop", "reason": "no_project_for_cwd"}`` because
        ``_resolve_project`` returns None cleanly without raising. The spirit
        of the test is that the endpoint NEVER 5xx's on bad input and never
        creates a row; we pin both halves.
        """
        pid = hook_project["id"]

        # Bad cwd: a path that no project's repo_path matches.
        r1 = client.post("/api/hooks/user-prompt", json={
            "prompt": "you are archie, read the playbook",
            "cwd": "/this/path/belongs/to/no/project",
            "hook_event_name": "UserPromptSubmit",
        })
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["status"] == "noop", body1
        assert body1.get("reason") == "no_project_for_cwd"

        # Missing cwd: payload omits the field entirely.
        r2 = client.post("/api/hooks/user-prompt", json={
            "prompt": "you are archie, read the playbook",
            "hook_event_name": "UserPromptSubmit",
        })
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["status"] == "noop", body2
        assert body2.get("reason") == "no_project_for_cwd"

        # Neither path created a DwbSession for the seeded project.
        assert _all_dwb_sessions_for(db_session, pid) == []
