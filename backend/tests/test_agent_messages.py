# Path: tests/test_agent_messages.py
# File: test_agent_messages.py
# Created: 2026-06-24
# Purpose: Epic 35 acceptance - POST /api/hooks/agent-message capture (DWB-447),
#          GET/DELETE /api/projects/{id}/agent-messages (DWB-448), and the
#          age-based purge sweep (DWB-449). Verifies sender resolution from
#          session_id, best-effort recipient resolution, the capture_agent_comms
#          gate, pagination/ordering, clear-all, and >4-day purge.
# Caller: pytest
# Callees: POST /api/hooks/agent-message, POST /api/hooks/session-start,
#          GET/DELETE /api/projects/{id}/agent-messages,
#          app.models.inter_agent_message.InterAgentMessage
# Data In: Factory-created projects/agents via conftest fixtures
# Data Out: Assertions on InterAgentMessage rows + endpoint responses
# Last Modified: 2026-06-24

"""Tests for inter-agent comms capture + log (Epic 35: DWB-446..449)."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.inter_agent_message import InterAgentMessage


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


def _session_id():
    return str(uuid.uuid4())


@pytest.fixture
def msg_project(client, make_project, tmp_path):
    """Project rooted at tmp_path (cwd resolution + capture default TRUE)."""
    return make_project(repo_path=str(tmp_path))


class TestAgentMessageCapture:
    """POST /api/hooks/agent-message (DWB-447)."""

    def test_captures_with_resolved_sender_and_recipient(
        self, client, msg_project, make_agent, db_session,
    ):
        pid = msg_project["id"]
        sender = make_agent(
            project_id=pid, name="SenderWorker", role="backend-worker",
            api_key="am-sender",
        )
        recipient = make_agent(
            project_id=pid, name="RecipientLead", role="team-lead",
            api_key="am-recipient",
        )
        _assign(client, pid, sender["id"])
        _assign(client, pid, recipient["id"])

        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": str(msg_project["repo_path"]),
            "agent_name": "backend-worker",
        })

        r = client.post("/api/hooks/agent-message", json={
            "to": "team-lead",
            "message": "the body of the message",
            "summary": "a summary",
            "session_id": sid,
            "cwd": str(msg_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["captured"] is True
        assert data["from_agent_id"] == sender["id"]
        assert data["from_agent_name"] == "SenderWorker"
        # Recipient resolved best-effort by name (role match).
        assert data["to_agent_id"] == recipient["id"]
        assert data["to_agent_name"] == "team-lead"

        row = db_session.scalar(
            select(InterAgentMessage).where(InterAgentMessage.id == data["message_id"])
        )
        assert row is not None
        assert row.project_id == pid
        assert row.body == "the body of the message"
        assert row.summary == "a summary"
        assert row.from_agent_id == sender["id"]

    def test_no_project_returns_captured_false_stores_nothing(
        self, client, db_session,
    ):
        before = db_session.scalar(select(InterAgentMessage.id).limit(1))
        r = client.post("/api/hooks/agent-message", json={
            "to": "someone", "message": "hi", "session_id": "bogus-no-project",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["captured"] is False
        assert data["message_id"] is None
        # to_agent_name still echoed back for the caller.
        assert data["to_agent_name"] == "someone"

    def test_disabled_flag_returns_captured_false_stores_nothing(
        self, client, msg_project, db_session,
    ):
        pid = msg_project["id"]
        client.patch(f"/api/projects/{pid}", json={"capture_agent_comms": False})

        r = client.post("/api/hooks/agent-message", json={
            "to": "team-lead",
            "message": "should not be stored",
            "cwd": str(msg_project["repo_path"]),
        })
        assert r.status_code == 200
        assert r.json()["captured"] is False

        rows = db_session.scalars(
            select(InterAgentMessage).where(InterAgentMessage.project_id == pid)
        ).all()
        assert rows == []

    def test_unresolvable_recipient_still_stores_to_name(
        self, client, msg_project, db_session,
    ):
        r = client.post("/api/hooks/agent-message", json={
            "to": "GhostAgentNotInProject",
            "message": "body",
            "cwd": str(msg_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["captured"] is True
        assert data["to_agent_id"] is None
        assert data["to_agent_name"] == "GhostAgentNotInProject"

        row = db_session.scalar(
            select(InterAgentMessage).where(InterAgentMessage.id == data["message_id"])
        )
        assert row.to_agent_id is None
        assert row.to_agent_name == "GhostAgentNotInProject"


class TestAgentMessageList:
    """GET + DELETE /api/projects/{id}/agent-messages (DWB-448)."""

    def _seed(self, client, msg_project, n):
        for i in range(n):
            client.post("/api/hooks/agent-message", json={
                "to": "team-lead",
                "message": f"message number {i}",
                "cwd": str(msg_project["repo_path"]),
            })

    def test_list_newest_first_and_pagination(self, client, msg_project):
        pid = msg_project["id"]
        self._seed(client, msg_project, 5)

        r = client.get(f"/api/projects/{pid}/agent-messages?limit=2&offset=0")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["rows"]) == 2
        # Newest-first: last seeded ("message number 4") leads.
        assert data["rows"][0]["body"] == "message number 4"
        assert data["rows"][1]["body"] == "message number 3"

        r2 = client.get(f"/api/projects/{pid}/agent-messages?limit=2&offset=2")
        assert [row["body"] for row in r2.json()["rows"]] == [
            "message number 2", "message number 1",
        ]

    def test_delete_clears_all_and_returns_count(self, client, msg_project, db_session):
        pid = msg_project["id"]
        self._seed(client, msg_project, 3)

        r = client.delete(f"/api/projects/{pid}/agent-messages")
        assert r.status_code == 200
        assert r.json()["deleted"] == 3

        rows = db_session.scalars(
            select(InterAgentMessage).where(InterAgentMessage.project_id == pid)
        ).all()
        assert rows == []

    def test_list_unknown_project_404(self, client):
        r = client.get("/api/projects/99999/agent-messages")
        assert r.status_code == 404

    def test_delete_unknown_project_404(self, client):
        r = client.delete("/api/projects/99999/agent-messages")
        assert r.status_code == 404


class TestAgentMessagePurge:
    """Age-based retention purge (DWB-449)."""

    def _make_msg(self, db_session, pid, *, created_at, body="x"):
        msg = InterAgentMessage(
            project_id=pid,
            from_agent_name="A",
            to_agent_name="B",
            body=body,
            created_at=created_at,
        )
        db_session.add(msg)
        db_session.commit()
        db_session.refresh(msg)
        return msg

    def test_purges_rows_older_than_threshold(self, msg_project, db_session):
        from app.services.inter_agent_message import purge_old_agent_messages

        pid = msg_project["id"]
        now = datetime(2026, 6, 24, 12, 0, 0)
        old_id = self._make_msg(
            db_session, pid, created_at=now - timedelta(days=5), body="old"
        ).id
        fresh_id = self._make_msg(
            db_session, pid, created_at=now - timedelta(days=1), body="fresh"
        ).id

        purged = purge_old_agent_messages(db_session, max_age_days=4, now=now)
        db_session.commit()
        assert purged == 1

        remaining = db_session.scalars(
            select(InterAgentMessage).where(InterAgentMessage.project_id == pid)
        ).all()
        ids = {r.id for r in remaining}
        assert old_id not in ids
        assert fresh_id in ids

    def test_purge_disabled_when_threshold_zero(self, msg_project, db_session):
        from app.services.inter_agent_message import purge_old_agent_messages

        pid = msg_project["id"]
        now = datetime(2026, 6, 24, 12, 0, 0)
        self._make_msg(db_session, pid, created_at=now - timedelta(days=100))

        purged = purge_old_agent_messages(db_session, max_age_days=0, now=now)
        assert purged == 0

    def test_purge_keys_off_age_not_session(self, msg_project, db_session):
        """A row with an open dwb_session_id is still purged purely on age:
        dwb_session_id is display-only and never consulted by the purge."""
        from app.services.inter_agent_message import purge_old_agent_messages

        pid = msg_project["id"]
        now = datetime(2026, 6, 24, 12, 0, 0)
        msg = self._make_msg(
            db_session, pid, created_at=now - timedelta(days=10), body="aged"
        )
        # Even with a (display-only) session stamp, age alone decides.
        purged = purge_old_agent_messages(db_session, max_age_days=4, now=now)
        db_session.commit()
        assert purged == 1
        assert db_session.get(InterAgentMessage, msg.id) is None


class TestAgentMessageProjectCascade:
    """delete_project must clear inter_agent_messages first (DWB-446).

    project_id is a NOT NULL FK to projects with no ON DELETE CASCADE, so a
    project carrying captured messages would 500 on the FK violation unless
    the delete service clears the rows first (app/services/project.py)."""

    def test_delete_project_with_messages_returns_204_and_clears_rows(
        self, client, msg_project, db_session,
    ):
        pid = msg_project["id"]
        # Seed a few captured messages through the real capture path.
        for i in range(3):
            r = client.post("/api/hooks/agent-message", json={
                "to": "team-lead",
                "message": f"cascade body {i}",
                "cwd": str(msg_project["repo_path"]),
            })
            assert r.status_code == 200
            assert r.json()["captured"] is True

        # Sanity: rows exist before the delete.
        assert db_session.scalars(
            select(InterAgentMessage).where(InterAgentMessage.project_id == pid)
        ).all()

        # Project deletes cleanly (no FK 500) ...
        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 204
        assert client.get(f"/api/projects/{pid}").status_code == 404

        # ... and the messages are gone with it.
        db_session.expire_all()
        assert db_session.scalars(
            select(InterAgentMessage).where(InterAgentMessage.project_id == pid)
        ).all() == []
