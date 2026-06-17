# Path: tests/test_dwb_session_phrase_privacy.py
# File: test_dwb_session_phrase_privacy.py
# Created: 2026-06-10
# Purpose: Tests for DWB-351 privacy - AI-layer phrase null-out + UserPromptSubmit prompt scrub on failed_hooks
# Caller: pytest
# Callees: POST /api/sessions/open, POST /api/sessions/{id}/close, app.services.hook_tracking.handle_user_prompt
# Data In: per-test db_session, factory project, direct service calls
# Data Out: Assertions on persisted open_phrase / close_phrase nullability + failed_hooks raw_payload redaction
# Last Modified: 2026-06-10

"""DWB-351 coverage.

User directive: "don't save anything I say to you in a db". The DWB-351
privacy guards enforce this in code:

  1. POST /api/sessions/open with open_method in (ai_confident, ai_asked)
     persists open_phrase as NULL regardless of what the caller sends.
  2. POST /api/sessions/{id}/close with close_method in (ai_confident,
     ai_asked) persists close_phrase as NULL regardless.
  3. POST /api/sessions/open with open_method=regex still stores the
     matched catalogue substring (deterministic, bounded by the
     hardcoded session_phrases.py list - spec explicitly allows this).
  4. handle_user_prompt() failure path scrubs the inbound `prompt` from
     the raw_payload it forwards to log_failed_hook, so the prompt
     never lands in the failed_hooks table.

Decision (per spec): silent null-out, not 400. Stale callers that still
pass a phrase get quiet redaction rather than a hard failure.
"""

from datetime import datetime, timezone

from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.failed_hook import FailedHook


def _read_latest_failed_hook_snippet() -> str | None:
    """Read the most recent FailedHook.payload_snippet via a fresh
    connection.

    log_failed_hook commits through database.SessionLocal() (its own
    transaction), so the per-test db_session (which holds an open
    transaction with REPEATABLE READ isolation) cannot see the row.
    Open a separate connection so the read picks up the latest
    committed state.
    """
    from app import database as app_database

    fresh = app_database.SessionLocal()
    try:
        row = fresh.execute(
            FailedHook.__table__.select().order_by(FailedHook.id.desc()).limit(1)
        ).fetchone()
        return None if row is None else row.payload_snippet
    finally:
        fresh.close()


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# 1. AI-layer open null-out
# ---------------------------------------------------------------------------


class TestOpenPhraseNullOnAILayer:
    """AI-method opens never persist the user-typed phrase."""

    def test_ai_confident_open_nulls_out_phrase(
        self, client, make_project, db_session,
    ):
        proj = make_project()
        r = client.post("/api/sessions/open", json={
            "project_id": proj["id"],
            "opened_at": _iso_now(),
            "open_method": "ai_confident",
            "open_phrase": "ok let's get to work on the dashboard",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["open_phrase"] is None
        assert body["open_method"] == "ai_confident"

        # Verify the row itself, not just the response shape.
        db_session.expire_all()
        row = db_session.get(DwbSession, body["id"])
        assert row is not None
        assert row.open_phrase is None

    def test_ai_asked_open_nulls_out_phrase(
        self, client, make_project, db_session,
    ):
        proj = make_project()
        r = client.post("/api/sessions/open", json={
            "project_id": proj["id"],
            "opened_at": _iso_now(),
            "open_method": "ai_asked",
            "open_phrase": "want me to open it? yes",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["open_phrase"] is None

        db_session.expire_all()
        row = db_session.get(DwbSession, body["id"])
        assert row.open_phrase is None

    def test_regex_open_keeps_matched_catalogue_phrase(
        self, client, make_project, db_session,
    ):
        """Regex opens MAY store the matched substring per spec - the
        catalogue is hardcoded and the matched slice is bounded by it."""
        proj = make_project()
        r = client.post("/api/sessions/open", json={
            "project_id": proj["id"],
            "opened_at": _iso_now(),
            "open_method": "regex",
            "open_phrase": "you are archie",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["open_phrase"] == "you are archie"

        db_session.expire_all()
        row = db_session.get(DwbSession, body["id"])
        assert row.open_phrase == "you are archie"


# ---------------------------------------------------------------------------
# 2. AI-layer close null-out
# ---------------------------------------------------------------------------


class TestClosePhraseNullOnAILayer:
    def _open(self, client, project_id, method="regex"):
        r = client.post("/api/sessions/open", json={
            "project_id": project_id,
            "opened_at": _iso_now(),
            "open_method": method,
        })
        assert r.status_code == 201, r.text
        return r.json()

    def test_ai_confident_close_nulls_out_phrase(
        self, client, make_project, db_session,
    ):
        proj = make_project()
        opened = self._open(client, proj["id"])
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_confident",
            "close_reason": "explicit",
            "close_phrase": "alright that's a wrap for tonight",
            "headline": "privacy test session close",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["close_phrase"] is None
        assert body["close_method"] == "ai_confident"

        db_session.expire_all()
        row = db_session.get(DwbSession, opened["id"])
        assert row.close_phrase is None

    def test_ai_asked_close_nulls_out_phrase(
        self, client, make_project, db_session,
    ):
        proj = make_project()
        opened = self._open(client, proj["id"])
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_asked",
            "close_reason": "manual",
            "close_phrase": "want me to close? yes",
            "headline": "privacy test session close",
        })
        assert r.status_code == 200, r.text
        assert r.json()["close_phrase"] is None

        db_session.expire_all()
        row = db_session.get(DwbSession, opened["id"])
        assert row.close_phrase is None

    def test_regex_close_keeps_matched_catalogue_phrase(
        self, client, make_project, db_session,
    ):
        proj = make_project()
        opened = self._open(client, proj["id"])
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "regex",
            "close_reason": "explicit",
            "close_phrase": "good night",
        })
        assert r.status_code == 200, r.text
        assert r.json()["close_phrase"] == "good night"

        db_session.expire_all()
        row = db_session.get(DwbSession, opened["id"])
        assert row.close_phrase == "good night"


# ---------------------------------------------------------------------------
# 3. handle_user_prompt failure path scrubs `prompt` from failed_hooks
# ---------------------------------------------------------------------------


class TestUserPromptScrubbedFromFailedHooks:
    """If handle_user_prompt raises, the raw_payload written to
    failed_hooks must NOT contain the user-typed prompt verbatim."""

    def test_prompt_redacted_when_open_session_raises(
        self, client, db_session, make_project, monkeypatch,
    ):
        """Force open_session to raise so the exception path runs, then
        inspect the failed_hooks row to confirm the prompt is redacted.

        FailedHook stores the payload as ``payload_snippet`` (Text,
        truncated). The service-level scrub replaces the prompt with
        ``<redacted>`` before passing the dict to log_failed_hook, so
        the snippet must not contain the original text and must contain
        the redaction marker.
        """
        proj = make_project(repo_path="/tmp/dwb351-redact-svc")

        # Patch dwb_svc.open_session to raise. Done at the module the
        # service imports, not the source module, so the patch is visible
        # to the call site.
        import app.services.hook_tracking as ht

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic failure for DWB-351 svc test")

        monkeypatch.setattr(ht.dwb_svc, "open_session", _boom)

        secret = "DWB351-SVC-SECRET you are archie, read the playbook"
        result = ht.handle_user_prompt(db_session, {
            "prompt": secret,
            "cwd": "/tmp/dwb351-redact-svc",
            "hook_event_name": "UserPromptSubmit",
            "session_id": "redact-1",
        })
        # Service swallows the exception and returns an error dict.
        assert result["status"] == "error"

        snippet = _read_latest_failed_hook_snippet()
        assert snippet is not None, "expected a failed_hooks row"
        assert secret not in snippet, (
            f"secret prompt leaked into failed_hooks payload_snippet: {snippet}"
        )
        assert "<redacted>" in snippet

    def test_user_prompt_endpoint_scrubs_on_router_level_failure(
        self, client, db_session, make_project, monkeypatch,
    ):
        """Belt-and-suspenders coverage: the router catches anything that
        leaks out of the service. Force the service to leak (re-raise
        instead of swallowing) and verify the router's log_failed_hook
        call still scrubs."""
        proj = make_project(repo_path="/tmp/dwb351-redact-router")

        import app.routers.hooks as hooks_router

        def _leaky(*args, **kwargs):
            raise RuntimeError("router-level synthetic failure for DWB-351")

        monkeypatch.setattr(hooks_router.svc, "handle_user_prompt", _leaky)

        secret = "DWB351-ROUTER-SECRET this is what the user actually typed"
        r = client.post("/api/hooks/user-prompt", json={
            "prompt": secret,
            "cwd": "/tmp/dwb351-redact-router",
            "hook_event_name": "UserPromptSubmit",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "error"

        snippet = _read_latest_failed_hook_snippet()
        assert snippet is not None, "expected a failed_hooks row"
        assert secret not in snippet, (
            f"secret prompt leaked into failed_hooks payload_snippet: {snippet}"
        )
        assert "<redacted>" in snippet


# ---------------------------------------------------------------------------
# 4. Backfill migration scrub - direct DML coverage
# ---------------------------------------------------------------------------


class TestBackfillScrubsAIPhrases:
    """The migration runs two UPDATEs that null out open_phrase /
    close_phrase for AI-method rows. These tests apply the same SQL via
    the test session to pin the scrub logic in isolation from the
    alembic plumbing."""

    def _apply_scrub(self, db_session):
        from sqlalchemy import text
        db_session.execute(
            text(
                "UPDATE dwb_sessions SET open_phrase = NULL "
                "WHERE open_method IN ('ai_confident', 'ai_asked') "
                "AND open_phrase IS NOT NULL"
            )
        )
        db_session.execute(
            text(
                "UPDATE dwb_sessions SET close_phrase = NULL "
                "WHERE close_method IN ('ai_confident', 'ai_asked') "
                "AND close_phrase IS NOT NULL"
            )
        )
        db_session.flush()

    def test_scrub_nulls_ai_layer_open_phrase(
        self, db_session, make_project,
    ):
        # Seed a row with the violating shape via the ORM (bypassing the
        # service guard so we can simulate a pre-DWB-351 historical row).
        proj = make_project()
        row = DwbSession(
            project_id=proj["id"],
            opened_at=datetime.utcnow(),
            open_method=DwbOpenMethod.ai_confident,
            open_phrase="leftover user text from before the guard",
        )
        db_session.add(row)
        db_session.flush()
        assert row.open_phrase is not None

        self._apply_scrub(db_session)
        db_session.refresh(row)
        assert row.open_phrase is None

    def test_scrub_nulls_ai_layer_close_phrase(
        self, db_session, make_project,
    ):
        proj = make_project()
        row = DwbSession(
            project_id=proj["id"],
            opened_at=datetime.utcnow(),
            closed_at=datetime.utcnow(),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.ai_asked,
            close_phrase="leftover ai close text",
        )
        db_session.add(row)
        db_session.flush()
        assert row.close_phrase is not None

        self._apply_scrub(db_session)
        db_session.refresh(row)
        assert row.close_phrase is None

    def test_scrub_preserves_regex_phrases(self, db_session, make_project):
        """Regex-method phrases must NOT be touched - the catalogue text
        is allowed per spec."""
        proj = make_project()
        row = DwbSession(
            project_id=proj["id"],
            opened_at=datetime.utcnow(),
            open_method=DwbOpenMethod.regex,
            open_phrase="you are archie",
        )
        db_session.add(row)
        db_session.flush()

        self._apply_scrub(db_session)
        db_session.refresh(row)
        assert row.open_phrase == "you are archie"
