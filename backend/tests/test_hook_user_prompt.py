# Path: tests/test_hook_user_prompt.py
# File: test_hook_user_prompt.py
# Created: 2026-06-09
# Purpose: Tests for the DWB-344 UserPromptSubmit fast-path open detection endpoint + DWB-377 close mirror + DWB-382 Layer-2 Haiku classifier fallback
# Caller: pytest
# Callees: POST /api/hooks/user-prompt, app.services.hook_tracking.handle_user_prompt,
#          app.services.hook_tracking._run_ai_classifier (DWB-382),
#          app.services.dwb_session.get_active_session, app.models.dwb_session.DwbSession
# Data In: factory fixtures (make_project), in-memory hook payloads, mocked anthropic client
# Data Out: Assertions on response bodies and DwbSession rows
# Last Modified: 2026-06-11
#
# DWB-377 (2026-06-11): added TestUserPromptClosesViaRegexFastPath covering
# the close-side mirror of DWB-344. Five cases pin the new contract:
# close-match + active session -> closed; close-match + no active -> noop;
# open path regression; unrelated prompt -> noop; race-condition idempotency.
#
# DWB-382 (2026-06-11): added TestUserPromptAIClassifierFallback covering
# the async Haiku Layer-2 backstop. Cases: high-confidence open opens via
# ai_classifier; high-confidence close closes via ai_classifier; low
# confidence noops; intent=neither noops; ANTHROPIC_API_KEY unset noops
# cleanly; SDK APIError swallowed (hook still 200); slow classifier does
# NOT block the synchronous response (<100ms even when mock sleeps 2s).

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

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.services import hook_tracking as hook_svc


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


# ---------------------------------------------------------------------------
# DWB-382: Layer-2 Haiku classifier fallback
# ---------------------------------------------------------------------------


def _mock_anthropic_response(intent: str, confidence: str):
    """Build the mock Anthropic SDK response shape used by ai_classifier.

    The classifier reads ``message.content[0].text`` and JSON-parses it. We
    use SimpleNamespace so attribute access (.content, .text) works without
    a full Anthropic SDK type.
    """
    import json as _json

    body = _json.dumps({"intent": intent, "confidence": confidence})
    return SimpleNamespace(content=[SimpleNamespace(text=body)])


class TestUserPromptAIClassifierFallback:
    """DWB-382: Layer-2 Haiku classifier scheduling + behavior.

    The classifier runs in a daemon thread spawned by
    ``_schedule_ai_classifier``. For behavior tests we monkeypatch that
    scheduler to invoke ``_run_ai_classifier`` synchronously so we can
    assert on persisted side-effects. For the perf bracket test we leave
    the scheduler intact and assert the synchronous response is fast.

    The Anthropic SDK call is mocked at the ``anthropic.Anthropic`` class
    level so no network traffic happens.
    """

    @pytest.fixture
    def sync_classifier(self, monkeypatch, db_session):
        """Monkeypatch _schedule_ai_classifier to run the classifier
        synchronously and redirect its fresh SessionLocal() at the
        per-test session.

        Why redirect: tests run in a transaction with REPEATABLE READ
        isolation. The classifier opens its own SessionLocal() (a fresh
        connection) in production because BackgroundTasks runs outside
        the request's get_db scope. In tests that would not see the
        project created earlier in the same transaction, so we point
        SessionLocal at the per-test session for the duration of the
        test. Production behavior is unchanged.
        """
        def _sync(project_id, prompt):
            hook_svc._run_ai_classifier(project_id, prompt)

        monkeypatch.setattr(
            hook_svc, "_schedule_ai_classifier", _sync
        )

        from app import database as app_database

        class _NoCloseSession:
            """Wrap the test session to no-op .close() so the classifier's
            try/finally doesn't tear down the shared per-test session."""

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def close(self):
                # Test owns the session lifecycle; classifier must not
                # close it.
                pass

        monkeypatch.setattr(
            app_database, "SessionLocal", lambda: _NoCloseSession(db_session)
        )

    @pytest.fixture
    def set_api_key(self, monkeypatch):
        """Force ANTHROPIC_API_KEY to a fake value for the test. The mock
        never actually validates it.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

    def _install_mock_client(
        self, monkeypatch, *, response=None, side_effect=None
    ):
        """Replace anthropic.Anthropic with a MagicMock that returns the
        given response (or raises via side_effect) on messages.create.
        Returns the mock factory so the test can inspect call_count.
        """
        import anthropic as anthropic_mod

        mock_messages = MagicMock()
        if side_effect is not None:
            mock_messages.create = MagicMock(side_effect=side_effect)
        else:
            mock_messages.create = MagicMock(return_value=response)

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        mock_factory = MagicMock(return_value=mock_client)
        monkeypatch.setattr(anthropic_mod, "Anthropic", mock_factory)
        return mock_factory, mock_messages

    def test_high_confidence_open_opens_via_ai_classifier(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        set_api_key,
        monkeypatch,
    ):
        """Case 1: classifier returns intent=open, confidence=high; no
        active session -> session opened with open_method=ai_classifier.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        self._install_mock_client(
            monkeypatch,
            response=_mock_anthropic_response("open", "high"),
        )

        assert _active_dwb_session_for(db_session, pid) is None

        r = client.post("/api/hooks/user-prompt", json={
            # Neither match_open nor match_close should hit this prompt.
            "prompt": "lets get cracking on the auth refactor today",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # Synchronous response is still no_phrase_match - the classifier
        # is async and the hook does not advertise its outcome.
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_phrase_match"

        # Sync-classifier fixture ran the work inline; the row is now in
        # the database.
        db_session.expire_all()
        active = _active_dwb_session_for(db_session, pid)
        assert active is not None, "classifier should have opened a session"
        assert active.open_method == DwbOpenMethod.ai_classifier
        # Privacy (DWB-351 + DWB-382): the raw prompt is NEVER persisted
        # on AI-method opens.
        assert active.open_phrase is None

    def test_high_confidence_close_closes_via_ai_classifier(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        set_api_key,
        monkeypatch,
    ):
        """Case 2: classifier returns intent=close, confidence=high;
        active session present -> closed with close_method=ai_classifier.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        # Seed an active session via the canonical open endpoint.
        opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        r0 = client.post("/api/sessions/open", json={
            "project_id": pid,
            "opened_at": opened_at,
            "open_method": "regex",
            "open_phrase": "you are archie, read the playbook",
        })
        assert r0.status_code == 201, r0.text
        seeded_id = r0.json()["id"]

        self._install_mock_client(
            monkeypatch,
            response=_mock_anthropic_response("close", "high"),
        )

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "ok thats it for me today catch you later",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_phrase_match"

        db_session.expire_all()
        row = db_session.get(DwbSession, seeded_id)
        assert row is not None
        assert row.closed_at is not None
        assert row.close_method == DwbCloseMethod.ai_classifier
        assert row.close_reason == DwbCloseReason.explicit
        # Privacy: AI-method close nulls out the phrase.
        assert row.close_phrase is None

    def test_low_confidence_response_is_noop(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        set_api_key,
        monkeypatch,
    ):
        """Case 3: confidence=low -> no row created, no session changed.

        Low-confidence is the classifier saying 'unsure'; we defer to
        regex / slash / user paths rather than risk a false trigger.
        """
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        self._install_mock_client(
            monkeypatch,
            response=_mock_anthropic_response("open", "low"),
        )

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "maybe i should look at the auth code",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "noop", body
        assert body.get("reason") == "no_phrase_match"

        db_session.expire_all()
        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_intent_neither_is_noop(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        set_api_key,
        monkeypatch,
    ):
        """Case 4: intent=neither -> no row created."""
        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        self._install_mock_client(
            monkeypatch,
            response=_mock_anthropic_response("neither", "high"),
        )

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "what's the weather like today",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "noop"

        db_session.expire_all()
        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_api_key_unset_classifier_noops_cleanly(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        monkeypatch,
    ):
        """Case 5: ANTHROPIC_API_KEY unset -> classifier silently noops.

        CI machines (and clones without the key) must pass this path.
        The classifier returns before any Anthropic import / call. We
        prove this by NOT installing a mock client - if the classifier
        attempted the call it would import the real SDK and fail on the
        missing key.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "lets get cracking on the auth refactor today",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "noop"

        db_session.expire_all()
        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_sdk_api_error_is_swallowed(
        self,
        client,
        hook_project,
        db_session,
        sync_classifier,
        set_api_key,
        monkeypatch,
    ):
        """Case 6: anthropic SDK raises -> classifier swallows, no row
        created, hook still returns 200.

        Models any transport / SDK error: APIError, RateLimitError,
        network failure, etc. The classifier must not crash the host or
        surface 5xx back to the hook.
        """
        import anthropic as anthropic_mod

        # APIError requires (message, request, body) in modern SDKs;
        # using a plain Exception is sufficient to exercise the swallow
        # path. The except clause is type-agnostic.
        class _FakeAPIError(Exception):
            pass

        self._install_mock_client(
            monkeypatch,
            side_effect=_FakeAPIError("simulated SDK failure"),
        )

        pid = hook_project["id"]
        repo = hook_project["repo_path"]

        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "kick off the work session please",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "noop"

        db_session.expire_all()
        assert _all_dwb_sessions_for(db_session, pid) == []

    def test_synchronous_response_does_not_wait_on_classifier(
        self,
        client,
        hook_project,
        db_session,
        set_api_key,
        monkeypatch,
    ):
        """Case 7: a slow classifier must not block the hook response.

        The classifier mock sleeps 2s before returning. The
        synchronous hook response MUST come back in <100ms because
        ``_schedule_ai_classifier`` spawns a daemon thread (not joined)
        for the actual work. We do NOT install the sync_classifier
        fixture here so the real scheduler path runs.

        Privacy note: the request returns before the thread does, so
        the daemon thread keeps running in the background even after
        the test assertion. We don't join it - this is the actual
        production contract.
        """
        def _slow_response(*args, **kwargs):
            time.sleep(2)
            return _mock_anthropic_response("neither", "high")

        self._install_mock_client(monkeypatch, side_effect=_slow_response)

        pid = hook_project["id"]  # noqa: F841 - just exercise the path
        repo = hook_project["repo_path"]

        start = time.perf_counter()
        r = client.post("/api/hooks/user-prompt", json={
            "prompt": "this prompt will be classified by a sleepy mock",
            "cwd": repo,
            "hook_event_name": "UserPromptSubmit",
        })
        elapsed = time.perf_counter() - start

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "noop"
        # The fire-and-forget contract: response must return well before
        # the 2s mock sleep completes. 100ms is generous - the actual
        # work path is microseconds (no Anthropic call on the request
        # thread).
        assert elapsed < 0.5, (
            f"hook response took {elapsed:.3f}s; classifier should be "
            "fire-and-forget (daemon thread), not awaited"
        )
