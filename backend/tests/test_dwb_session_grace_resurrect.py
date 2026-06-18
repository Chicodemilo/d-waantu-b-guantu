# Path: tests/test_dwb_session_grace_resurrect.py
# File: test_dwb_session_grace_resurrect.py
# Created: 2026-06-17
# Purpose: Tests for DWB-395 grace-window auto-resurrect of just-closed DWB sessions
# Caller: pytest
# Callees: app.services.hook_tracking._maybe_grace_resurrect_dwb_session,
#          app.services.dwb_session, POST /api/hooks/session-start
# Data In: factory fixtures (make_project), db_session, tmp_path repo dirs
# Data Out: Assertions on session reopen behavior + hook_session linkage
# Last Modified: 2026-06-17

"""DWB-395: grace-window auto-resurrect.

When tracking activity lands within 120s of a LOW-PRECISION close (regex or
ai_classifier), the just-closed DWB session is reopened instead of a brand-new
one being created - so a false close (e.g. TL prose tripping the Layer-1 close
catalogue) doesn't fragment the rollup. Deliberate closes (slash, ai_confident,
ai_asked, idle_timeout) are NEVER auto-undone.

These tests pin:
  - resurrect on a regex close inside the window (service helper + end-to-end)
  - resurrect on an ai_classifier close inside the window
  - NON-resurrect on slash / ai_confident / idle_timeout closes
  - NON-resurrect when the close is older than the grace window
  - NON-resurrect when a session is already open
"""

from datetime import UTC, datetime, timedelta

import pytest
import uuid
from sqlalchemy import select

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession
from app.services import dwb_session as dwb_svc
from app.services.hook_tracking import _maybe_grace_resurrect_dwb_session


def _open_and_close(
    db_session,
    project_id: int,
    *,
    close_method: DwbCloseMethod,
    closed_secs_ago: int = 5,
) -> DwbSession:
    """Open a DWB session then close it `closed_secs_ago` seconds in the past
    via the service layer, returning the (flushed) closed row."""
    row, _ = dwb_svc.open_session(
        db_session,
        project_id=project_id,
        opened_at=datetime.now(UTC) - timedelta(minutes=10),
        open_method=DwbOpenMethod.regex,
    )
    dwb_svc.close_session(
        db_session,
        row,
        close_method=close_method,
        close_reason=DwbCloseReason.explicit,
        close_phrase=None,
        now=datetime.now(UTC) - timedelta(seconds=closed_secs_ago),
    )
    return row


class TestGraceResurrectServiceHelper:
    @pytest.mark.parametrize(
        "close_method",
        [DwbCloseMethod.regex, DwbCloseMethod.ai_classifier],
    )
    def test_resurrects_low_precision_close_inside_window(
        self, db_session, make_project, close_method
    ):
        project = make_project()
        row = _open_and_close(
            db_session, project["id"], close_method=close_method, closed_secs_ago=10
        )
        assert row.closed_at is not None

        resurrected_id = _maybe_grace_resurrect_dwb_session(
            db_session, project["id"]
        )
        assert resurrected_id == row.id
        db_session.refresh(row)
        assert row.closed_at is None
        assert row.close_method is None
        assert row.close_reason is None
        assert row.close_phrase is None

    @pytest.mark.parametrize(
        "close_method",
        [
            DwbCloseMethod.slash,
            DwbCloseMethod.ai_confident,
            DwbCloseMethod.ai_asked,
            DwbCloseMethod.idle_timeout,
        ],
    )
    def test_does_not_resurrect_deliberate_close(
        self, db_session, make_project, close_method
    ):
        project = make_project()
        row = _open_and_close(
            db_session, project["id"], close_method=close_method, closed_secs_ago=10
        )

        resurrected_id = _maybe_grace_resurrect_dwb_session(
            db_session, project["id"]
        )
        assert resurrected_id is None
        db_session.refresh(row)
        assert row.closed_at is not None
        assert row.close_method == close_method

    def test_does_not_resurrect_close_older_than_window(
        self, db_session, make_project
    ):
        project = make_project()
        row = _open_and_close(
            db_session,
            project["id"],
            close_method=DwbCloseMethod.regex,
            closed_secs_ago=200,  # > 120s grace window
        )

        resurrected_id = _maybe_grace_resurrect_dwb_session(
            db_session, project["id"]
        )
        assert resurrected_id is None
        db_session.refresh(row)
        assert row.closed_at is not None

    def test_noop_when_session_already_open(self, db_session, make_project):
        project = make_project()
        dwb_svc.open_session(
            db_session,
            project_id=project["id"],
            opened_at=datetime.now(UTC),
            open_method=DwbOpenMethod.regex,
        )
        resurrected_id = _maybe_grace_resurrect_dwb_session(
            db_session, project["id"]
        )
        assert resurrected_id is None

    def test_noop_when_no_sessions(self, db_session, make_project):
        project = make_project()
        assert _maybe_grace_resurrect_dwb_session(db_session, project["id"]) is None


class TestGraceResurrectEndToEnd:
    """The resurrect fires through _active_dwb_session_id, so any hook that
    inserts a hook_session triggers it. Drive it via the real hooks endpoint."""

    @pytest.fixture
    def hook_project(self, make_project, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        return make_project(repo_path=str(repo))

    def _hook_session(self, db_session, session_id):
        db_session.expire_all()
        return db_session.execute(
            select(HookSession).where(HookSession.session_id == session_id)
        ).scalar_one_or_none()

    def test_regex_close_then_hook_activity_resurrects(
        self, client, hook_project, db_session
    ):
        # Open + regex-close a DWB session via the public endpoints.
        opened = client.post(
            "/api/sessions/open",
            json={
                "project_id": hook_project["id"],
                "open_method": "regex",
            },
        )
        assert opened.status_code == 201, opened.text
        dwb_id = opened.json()["id"]

        rc = client.post(
            f"/api/sessions/{dwb_id}/close",
            json={
                "close_method": "regex",
                "close_reason": "explicit",
                "close_phrase": "shut down cycle",
            },
        )
        assert rc.status_code == 200, rc.text
        assert rc.json()["closed_at"] is not None

        # Tracking activity lands: a SessionStart hook. _active_dwb_session_id
        # should resurrect the just-closed regex session and link to it.
        sid = str(uuid.uuid4())
        r = client.post(
            "/api/hooks/session-start",
            json={
                "session_id": sid,
                "cwd": hook_project["repo_path"],
                "hook_event": "SessionStart",
            },
        )
        assert r.status_code == 200, r.text

        # The DWB session is open again...
        detail = client.get(f"/api/sessions/{dwb_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "open"

        # ...and the new hook_session links to the resurrected session, not a
        # fresh one.
        hs = self._hook_session(db_session, sid)
        assert hs is not None
        assert hs.dwb_session_id == dwb_id

    def test_slash_close_then_hook_activity_does_not_resurrect(
        self, client, hook_project, db_session
    ):
        opened = client.post(
            "/api/sessions/open",
            json={
                "project_id": hook_project["id"],
                "open_method": "slash",
                "open_phrase": "/dwb-open",
            },
        )
        assert opened.status_code == 201, opened.text
        dwb_id = opened.json()["id"]

        rc = client.post(
            f"/api/sessions/{dwb_id}/close",
            json={
                "close_method": "slash",
                "close_reason": "explicit",
                "close_phrase": "/dwb-close",
            },
        )
        assert rc.status_code == 200, rc.text

        sid = str(uuid.uuid4())
        r = client.post(
            "/api/hooks/session-start",
            json={
                "session_id": sid,
                "cwd": hook_project["repo_path"],
                "hook_event": "SessionStart",
            },
        )
        assert r.status_code == 200, r.text

        # Deliberate slash close is never auto-undone.
        detail = client.get(f"/api/sessions/{dwb_id}")
        assert detail.json()["status"] == "closed"

        hs = self._hook_session(db_session, sid)
        assert hs is not None
        assert hs.dwb_session_id is None
