# Path:          tests/test_dwb_session_activity_events.py
# File:          test_dwb_session_activity_events.py
# Created:       2026-06-19
# Purpose:       Tests for semantic DWB-session activity events session_opened / session_closed (DWB-411)
# Caller:        pytest
# Callees:       app.services.dwb_session.open_session/close_session, POST /api/sessions/*, ActivityLog
# Data In:       Factory-created project, in-process db_session
# Data Out:      Assertions on session_opened / session_closed activity_log rows
# Last Modified: 2026-06-19 (DWB-411)

"""Semantic DWB-session event tests: session_opened, session_closed."""

import json

from sqlalchemy import select

from app.models.activity_log import ActivityLog
from app.models.dwb_session import DwbCloseMethod, DwbCloseReason, DwbOpenMethod
from app.services import dwb_session as svc


def _events(db_session, entity_id, action=None):
    stmt = select(ActivityLog).where(
        ActivityLog.entity_type == "session",
        ActivityLog.entity_id == entity_id,
    )
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    return list(db_session.scalars(stmt).all())


def _details(row):
    return json.loads(row.details) if row.details else None


class TestSessionOpenedEvent:
    def test_open_emits_session_opened(self, db_session, make_project):
        project = make_project()
        row, existing = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        assert existing is None and row is not None
        rows = _events(db_session, row.id, "session_opened")
        assert len(rows) == 1
        assert _details(rows[0]) == {"open_method": "regex"}
        assert rows[0].project_id == project["id"]
        assert rows[0].agent_id is None  # session is project-level, not an agent

    def test_open_records_the_method(self, db_session, make_project):
        project = make_project()
        row, _ = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.slash
        )
        rows = _events(db_session, row.id, "session_opened")
        assert _details(rows[0])["open_method"] == "slash"

    def test_conflict_open_emits_nothing(self, db_session, make_project):
        project = make_project()
        first, _ = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        # Second open on the same project conflicts (single-active invariant).
        dup, existing = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        assert dup is None and existing is not None
        # Only the first session produced an opened event.
        all_opened = db_session.scalars(
            select(ActivityLog).where(
                ActivityLog.entity_type == "session",
                ActivityLog.action == "session_opened",
                ActivityLog.project_id == project["id"],
            )
        ).all()
        assert len(list(all_opened)) == 1


class TestSessionClosedEvent:
    def test_close_emits_session_closed(self, db_session, make_project):
        project = make_project()
        row, _ = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.slash,
            close_reason=DwbCloseReason.explicit,
            headline="wired the activity feed verbs",
        )
        rows = _events(db_session, row.id, "session_closed")
        assert len(rows) == 1
        details = _details(rows[0])
        assert details["close_method"] == "slash"
        assert details["headline"] == "wired the activity feed verbs"
        assert details["total_tokens"] == 0  # no linked hook_sessions

    def test_close_headline_null_when_absent(self, db_session, make_project):
        project = make_project()
        row, _ = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        details = _details(_events(db_session, row.id, "session_closed")[0])
        assert details["headline"] is None
        assert details["close_method"] == "idle_timeout"

    def test_idempotent_reclose_emits_no_second_event(self, db_session, make_project):
        project = make_project()
        row, _ = svc.open_session(
            db_session, project_id=project["id"], open_method=DwbOpenMethod.regex
        )
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        # Re-close: idempotent no-op, must not emit a second event.
        svc.close_session(
            db_session, row,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        assert len(_events(db_session, row.id, "session_closed")) == 1


class TestSessionEventsViaApi:
    def test_open_then_close_via_api(self, client, db_session, make_project):
        project = make_project()
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"],
            "open_method": "regex",
        })
        assert opened.status_code == 201, opened.text
        sid = opened.json()["id"]
        assert len(_events(db_session, sid, "session_opened")) == 1

        closed = client.post(f"/api/sessions/{sid}/close", json={
            "close_method": "regex",
            "close_reason": "explicit",
        })
        assert closed.status_code == 200, closed.text
        assert len(_events(db_session, sid, "session_closed")) == 1
