# Path: tests/test_dwb_sessions.py
# File: test_dwb_sessions.py
# Created: 2026-06-09
# Purpose: Endpoint + service tests for /api/sessions/open and /api/sessions/{id}/close (DWB-336, DWB-381 slash method)
# Caller: pytest
# Callees: app.routers.dwb_sessions, app.services.dwb_session, app.models.dwb_session
# Data In: factory fixtures (make_project), test client
# Data Out: Assertions on HTTP status codes, response bodies, DB state
# Last Modified: 2026-06-11

"""End-to-end tests for the DWB session lifecycle endpoints.

Covers:
  - POST /api/sessions/open
      201 happy path with + without open_phrase
      201 records open_method enum + opened_at correctly
      409 conflict when an active session exists, with active_session_id +
          opened_at surfaced in the body
      201 re-allowed after the active session is closed
      201 in a DIFFERENT project does not conflict
      422 validation when required fields are missing

  - POST /api/sessions/{id}/close
      200 happy path with phrase + method + reason
      200 idempotent close on already-closed (NOT 409)
      200 rolls up total_time_seconds from opened_at -> closed_at
      200 rolls up total_tokens from linked hook_sessions
      404 when session_id does not exist

  - Service contract
      app.services.dwb_session.close_session is imported by both
      dwb_sessions router and idle_sweeper, so a regression on its
      signature would break either. Verified with a structural import test.
"""

from datetime import datetime, timedelta, timezone
from inspect import signature

import pytest

from app.models.dwb_session import DwbCloseMethod, DwbCloseReason, DwbOpenMethod
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType


def _opened_at_iso(minus_hours: int = 0) -> str:
    """ISO 8601 timestamp <minus_hours> ago, UTC, with second precision."""
    dt = datetime.now(timezone.utc) - timedelta(hours=minus_hours)
    return dt.replace(microsecond=0).isoformat()


class TestOpenEndpoint:
    @pytest.mark.parametrize("open_method", ["regex", "slash"])
    def test_201_minimum_body(self, client, make_project, open_method):
        """DWB-381: `slash` is a first-class open_method alongside `regex`.

        Parametrized so the slash escape hatch is exercised by the same
        round-trip assertions as the canonical regex open path - row
        persisted, enum echoed back, is_open marker flipped to 1.
        """
        project = make_project()
        r = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": open_method,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] is not None
        assert body["project_id"] == project["id"]
        assert body["closed_at"] is None
        assert body["open_method"] == open_method
        assert body["open_phrase"] is None
        assert body["is_open"] == 1
        assert body["total_tokens"] == 0
        assert body["total_time_seconds"] == 0

    def test_201_with_open_phrase(self, client, make_project):
        """DWB-351: AI-method opens null out the phrase regardless of
        what the caller sends (privacy: user-typed text never persisted).
        This test now uses open_method=regex to exercise the with-phrase
        success path; the AI-method null-out is covered in
        test_dwb_session_phrase_privacy.py.
        """
        project = make_project()
        r = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "regex",
                "open_phrase": "you are archie, read the playbook",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["open_method"] == "regex"
        assert body["open_phrase"] == "you are archie, read the playbook"

    def test_409_when_active_session_exists(self, client, make_project):
        project = make_project()
        opened = _opened_at_iso()
        r1 = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": opened,
                "open_method": "regex",
            },
        )
        assert r1.status_code == 201
        active_id = r1.json()["id"]

        r2 = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "ai_confident",
            },
        )
        assert r2.status_code == 409, r2.text
        body = r2.json()
        # Conflict body surfaces the active session for debuggability
        assert body["active_session_id"] == active_id
        assert "opened_at" in body
        assert str(active_id) in body["detail"]

    def test_201_after_active_session_closed(self, client, make_project):
        """Re-opening must succeed once the prior session is closed."""
        project = make_project()
        r1 = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "regex",
            },
        )
        assert r1.status_code == 201
        sid = r1.json()["id"]

        # Close it.
        rc = client.post(
            f"/api/sessions/{sid}/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
                "close_phrase": "close the session",
            },
        )
        assert rc.status_code == 200

        # Now a fresh open should land.
        r2 = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "ai_confident",
            },
        )
        assert r2.status_code == 201
        assert r2.json()["id"] != sid

    def test_open_in_different_project_is_independent(
        self, client, make_project
    ):
        """Single-active is scoped per-project, not global."""
        p1 = make_project()
        p2 = make_project()
        for pid in (p1["id"], p2["id"]):
            r = client.post(
                "/api/sessions/open",
                json={
                    "project_id": pid,
                    "opened_at": _opened_at_iso(),
                    "open_method": "regex",
                },
            )
            assert r.status_code == 201, r.text

    def test_422_missing_required_field(self, client, make_project):
        project = make_project()
        # Missing open_method
        r = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
            },
        )
        assert r.status_code == 422

    def test_422_invalid_open_method_enum(self, client, make_project):
        project = make_project()
        r = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "telepathy",  # not in enum
            },
        )
        assert r.status_code == 422


class TestCloseEndpoint:
    def _open(self, client, project_id, opened_iso=None):
        r = client.post(
            "/api/sessions/open",
            json={
                "project_id": project_id,
                "opened_at": opened_iso or _opened_at_iso(),
                "open_method": "regex",
                "open_phrase": "you are archie, read the playbook",
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    @pytest.mark.parametrize(
        "close_method,close_phrase",
        [
            ("regex", "have the team write docs and exit"),
            # DWB-381: `slash` is a first-class close_method. The slash
            # command supplies its own static phrase (`/dwb-close`) when
            # firing the API, so the parametrized phrase covers both shapes.
            ("slash", "/dwb-close"),
        ],
    )
    def test_200_happy_close(
        self, client, make_project, close_method, close_phrase
    ):
        project = make_project()
        opened = self._open(client, project["id"])

        r = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": close_method,
                "close_reason": "explicit",
                "close_phrase": close_phrase,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == opened["id"]
        assert body["closed_at"] is not None
        assert body["close_method"] == close_method
        assert body["close_reason"] == "explicit"
        assert body["close_phrase"] == close_phrase
        assert body["is_open"] is None  # generated column flipped to NULL

    def test_200_idempotent_on_already_closed(self, client, make_project):
        """Closing an already-closed session is a 200 no-op, NOT a 409.
        The idle sweeper relies on this — if a regex/AI close beat it to
        the row, the sweeper's request must not surface as an error.
        """
        project = make_project()
        opened = self._open(client, project["id"])

        first = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
                "close_phrase": "close the session",
            },
        )
        assert first.status_code == 200
        first_body = first.json()

        # Hit close again with completely different metadata — should not
        # overwrite, should still return 200 with the original row.
        second = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": "idle_timeout",
                "close_reason": "idle",
            },
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["close_method"] == first_body["close_method"]
        assert second_body["close_reason"] == first_body["close_reason"]
        assert second_body["closed_at"] == first_body["closed_at"]

    def test_404_when_not_found(self, client):
        r = client.post(
            "/api/sessions/999999999/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
            },
        )
        assert r.status_code == 404

    def test_close_rolls_up_total_time_seconds(self, client, make_project):
        """total_time_seconds = closed_at - opened_at, in whole seconds."""
        project = make_project()
        # Open 2 hours in the past.
        opened_iso = _opened_at_iso(minus_hours=2)
        opened = self._open(client, project["id"], opened_iso=opened_iso)

        r = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
            },
        )
        assert r.status_code == 200
        elapsed = r.json()["total_time_seconds"]
        # 2 hours = 7200 seconds; allow a small fudge for test wall time.
        assert 7100 <= elapsed <= 7300, f"unexpected elapsed: {elapsed}"

    def test_close_rolls_up_linked_hook_session_tokens(
        self, client, db_session, make_project
    ):
        """total_tokens = SUM(hook_sessions.total_tokens WHERE
        dwb_session_id = this.id). Insert two linked hook_sessions and
        confirm the close rollup sums them."""
        project = make_project()
        opened = self._open(client, project["id"])

        # Link two hook_sessions to the open DWB session via raw INSERT
        # so we don't depend on the full hook ingestion pipeline.
        for i, tokens in enumerate([1234, 567]):
            hs = HookSession(
                session_id=f"linked-{opened['id']}-{i}",
                project_id=project["id"],
                start_time=datetime.now(timezone.utc).replace(tzinfo=None),
                end_time=datetime.now(timezone.utc).replace(tzinfo=None),
                status=HookSessionStatus.completed,
                session_type=HookSessionType.teammate,
                total_tokens=tokens,
                dwb_session_id=opened["id"],
            )
            db_session.add(hs)
        db_session.flush()

        r = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
            },
        )
        assert r.status_code == 200
        assert r.json()["total_tokens"] == 1234 + 567


class TestServiceContract:
    """The close service-fn is shared by the router and the idle sweeper.
    A regression on signature breaks one or both, so verify shape directly.

    Imports only — no calls — per ticket spec."""

    def test_close_session_importable_with_expected_signature(self):
        from app.services.dwb_session import close_session

        sig = signature(close_session)
        params = sig.parameters
        # The sweeper passes close_method, close_reason, close_phrase (None),
        # and (optionally) now; the router passes the same names plus the
        # DwbSession instance positionally. Verify those keys are present
        # so either caller will work.
        assert "close_method" in params
        assert "close_reason" in params
        assert "close_phrase" in params
        assert "now" in params

    def test_idle_sweeper_imports_close_session(self):
        """The idle sweeper imports sweep_idle_sessions which calls
        close_session — verify the import chain doesn't blow up at module
        load and the names line up."""
        from app.services.dwb_session import close_session, sweep_idle_sessions
        from app.services.idle_sweeper import _run_one_sweep_sync

        # Just touch the symbols so the test fails on import-time errors.
        assert callable(close_session)
        assert callable(sweep_idle_sessions)
        assert callable(_run_one_sweep_sync)

    def test_open_session_service_returns_existing_on_conflict(
        self, db_session, make_project
    ):
        """open_session returns (None, existing) on conflict so the router
        can build the 409 body without a second query."""
        from app.services.dwb_session import open_session

        project = make_project()
        opened = datetime.now(timezone.utc).replace(microsecond=0)
        first, _ = open_session(
            db_session,
            project_id=project["id"],
            opened_at=opened,
            open_method=DwbOpenMethod.regex,
        )
        db_session.flush()
        assert first is not None

        second, existing = open_session(
            db_session,
            project_id=project["id"],
            opened_at=opened,
            open_method=DwbOpenMethod.ai_confident,
        )
        assert second is None
        assert existing is not None
        assert existing.id == first.id


class TestEnumValues:
    """Sanity test the enum values so a future rename gets caught.

    DWB-381: `slash` added to both DwbOpenMethod and DwbCloseMethod for the
    /dwb-open and /dwb-close slash-command escape hatches.

    DWB-382: `ai_classifier` added to both for the Layer-2 Haiku fallback
    in handle_user_prompt.
    """

    def test_open_methods(self):
        names = {m.value for m in DwbOpenMethod}
        assert names == {
            "regex",
            "ai_confident",
            "ai_asked",
            "slash",
            "ai_classifier",
        }

    def test_close_methods(self):
        names = {m.value for m in DwbCloseMethod}
        assert names == {
            "regex",
            "ai_confident",
            "ai_asked",
            "idle_timeout",
            "slash",
            "ai_classifier",
        }

    def test_close_reasons(self):
        names = {m.value for m in DwbCloseReason}
        assert names == {"explicit", "idle", "manual"}


class TestSlashEscapeHatch:
    """DWB-381: end-to-end round-trip for the /dwb-open + /dwb-close
    slash-command escape hatch. The slash command files (TL-direct) curl
    /api/sessions/open / /api/sessions/{id}/close with method=slash; this
    pins the row stamping so the persisted enum survives a future rewrite.
    """

    def test_slash_open_then_slash_close_roundtrip(self, client, make_project):
        project = make_project()

        ro = client.post(
            "/api/sessions/open",
            json={
                "project_id": project["id"],
                "opened_at": _opened_at_iso(),
                "open_method": "slash",
                "open_phrase": "/dwb-open",
            },
        )
        assert ro.status_code == 201, ro.text
        opened = ro.json()
        assert opened["open_method"] == "slash"
        # `slash` is a deterministic escape hatch (not AI-method), so the
        # phrase persists like regex does — the DWB-351 null-out only fires
        # for ai_confident / ai_asked.
        assert opened["open_phrase"] == "/dwb-open"

        rc = client.post(
            f"/api/sessions/{opened['id']}/close",
            json={
                "close_method": "slash",
                "close_reason": "explicit",
                "close_phrase": "/dwb-close",
            },
        )
        assert rc.status_code == 200, rc.text
        closed = rc.json()
        assert closed["close_method"] == "slash"
        assert closed["close_reason"] == "explicit"
        assert closed["close_phrase"] == "/dwb-close"
        assert closed["closed_at"] is not None
        assert closed["is_open"] is None
