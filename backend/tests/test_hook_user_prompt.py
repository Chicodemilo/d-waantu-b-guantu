# Path: tests/test_hook_user_prompt.py
# File: test_hook_user_prompt.py
# Created: 2026-06-09
# Purpose: Tests for the DWB-344 UserPromptSubmit fast-path open detection endpoint + DWB-377 close mirror
# Caller: pytest
# Callees: POST /api/hooks/user-prompt, app.services.hook_tracking.handle_user_prompt,
#          app.services.dwb_session.get_active_session, app.models.dwb_session.DwbSession
# Data In: factory fixtures (make_project), in-memory hook payloads
# Data Out: Assertions on response bodies and DwbSession rows
# Last Modified: 2026-06-19
#
# DWB-377 (2026-06-11): added TestUserPromptClosesViaRegexFastPath covering
# the close-side mirror of DWB-344. Five cases pin the new contract:
# close-match + active session -> closed; close-match + no active -> noop;
# open path regression; unrelated prompt -> noop; race-condition idempotency.
#
# DWB-402 (2026-06-19): removed TestUserPromptAIClassifierFallback. The Layer-2
# Haiku classifier (DWB-382) was retired; a non-matching prompt is now a plain
# noop with no Anthropic call, so there is nothing to mock or assert beyond the
# existing no_phrase_match noop coverage.

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

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)


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


class TestUserPromptClosesViaRegexFastPath:
    """DWB-377: handle_user_prompt closes the active DWB session on a
    matching close phrase. Mirror of DWB-344 on the close side.
    """

    def _seed_open_session(self, client, project_id) -> int:
        """Seed an ai_confident session and return its id."""
        opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        r = client.post("/api/sessions/open", json={
            "project_id": project_id,
            "opened_at": opened_at,
            "open_method": "ai_confident",
            "open_phrase": "seeded by ai_confident",
        })
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_closes_active_session_when_prompt_matches_close_phrase(
        self, client, hook_project, db_session,
    ):
        """Case 1: catalogued close phrase + active session -> closed via regex."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        seeded_id = self._seed_open_session(client, pid)
        assert _active_dwb_session_for(db_session, pid) is not None

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "have the team write docs and exit",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "closed", body
        assert body["dwb_session_id"] == seeded_id
        assert "close_phrase" in body
        assert "write docs" in body["close_phrase"].lower()

        # Row is closed, close_method=regex, close_reason=explicit.
        db_session.expire_all()
        row = db_session.get(DwbSession, seeded_id)
        assert row is not None
        assert row.closed_at is not None
        assert row.close_method == DwbCloseMethod.regex
        assert row.close_reason == DwbCloseReason.explicit
        assert row.close_phrase is not None
        assert "write docs" in row.close_phrase.lower()
        # And the project has no open session anymore.
        assert _active_dwb_session_for(db_session, pid) is None

    def test_close_phrase_with_no_active_session_is_noop(
        self, client, hook_project, db_session,
    ):
        """Case 2: catalogued close phrase + no active session -> noop."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        assert _all_dwb_sessions_for(db_session, pid) == []

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "have the team write docs and exit",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_active_session"

        # No row was created by the close attempt.
        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_open_path_still_works_regression(
        self, client, hook_project, db_session,
    ):
        """Case 3: open phrase still opens (regression guard).

        Restructure in DWB-377 split handle_user_prompt into two ladders;
        confirm the open branch still fires for a matching open phrase when
        the project has no active session.
        """
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
        assert active is not None
        assert active.open_method == DwbOpenMethod.regex

    def test_unrelated_prompt_with_active_session_is_noop(
        self, client, hook_project, db_session,
    ):
        """Case 4: prompt matches neither open nor close -> noop, reason=no_phrase_match.

        Seed an active session so we don't accidentally hit the no_active_session
        branch — we want to confirm the terminal "no phrase matched at all"
        path returns the right reason code.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        seeded_id = self._seed_open_session(client, pid)

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "whats the status of the deploy",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_phrase_match"

        # The seeded session stayed open and untouched.
        db_session.expire_all()
        row = db_session.get(DwbSession, seeded_id)
        assert row is not None
        assert row.closed_at is None
        assert row.close_method is None

    def test_close_phrase_after_session_closed_by_other_path_is_idempotent(
        self, client, hook_project, db_session,
    ):
        """Case 5: close phrase + session already closed by another path -> no 5xx,
        idempotent noop.

        Simulate the race where the sweeper or the explicit close endpoint
        closes the session between our get_active_session and close_session.
        We model it by pre-closing the seeded session via the explicit endpoint,
        then firing UserPromptSubmit. With no open session present,
        get_active_session returns None and the path returns
        ``noop / no_active_session`` — the endpoint never 5xx's, the closed
        row is preserved untouched (no second close_method overwrite).
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        seeded_id = self._seed_open_session(client, pid)

        # Pre-close via the explicit endpoint (mirrors what the sweeper or a
        # competing UserPromptSubmit would do).
        r_close = client.post(f"/api/sessions/{seeded_id}/close", json={
            "close_method": "ai_confident",
            "close_reason": "explicit",
            "headline": "hook user-prompt test close",
        })
        assert r_close.status_code in (200, 201), r_close.text

        db_session.expire_all()
        row_before = db_session.get(DwbSession, seeded_id)
        assert row_before is not None
        assert row_before.closed_at is not None
        assert row_before.close_method == DwbCloseMethod.ai_confident
        closed_at_before = row_before.closed_at

        # Now fire UserPromptSubmit with a catalogued close phrase. The
        # session is already closed, so get_active_session returns None and
        # the path returns noop. No 5xx, no overwrite of the pre-close fields.
        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "have the team write docs and exit",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_active_session"

        # The pre-existing close fields are untouched.
        db_session.expire_all()
        row_after = db_session.get(DwbSession, seeded_id)
        assert row_after is not None
        assert row_after.close_method == DwbCloseMethod.ai_confident, (
            "second close attempt must not overwrite the first close_method"
        )
        assert row_after.closed_at == closed_at_before
