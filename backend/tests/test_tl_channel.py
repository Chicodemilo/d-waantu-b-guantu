# Path: tests/test_tl_channel.py
# File: test_tl_channel.py
# Created: 2026-06-23
# Purpose: Tests for the cross-project team-lead channel (DWB-436 model/migration/cleanup; DWB-437 endpoints added later).
# Caller: pytest
# Callees: app.models.tl_message, /api/tl-channel
# Data In: pytest fixtures
# Data Out: assertions
# Last Modified: 2026-06-23

from datetime import datetime

from app.models.alert import Alert
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.tl_message import TlMessage, TlMessageRead


def _tl(make_agent, **overrides):
    """A team-lead agent (one per project by default)."""
    overrides.setdefault("role", "team-lead")
    return make_agent(**overrides)


class TestTlMessageModel:
    """DWB-436: the tl_messages + tl_message_reads tables, cross-project and
    NOT project-scoped."""

    def test_direct_message_persists(self, db_session, make_agent):
        sender = make_agent()
        recipient = make_agent()
        msg = TlMessage(
            from_agent_id=sender["id"],
            to_agent_id=recipient["id"],
            from_project_id=sender["project_id"],
            body="direct hello",
        )
        db_session.add(msg)
        db_session.flush()
        assert msg.id is not None
        assert msg.created_at is not None  # server_default now()
        assert msg.to_agent_id == recipient["id"]

    def test_broadcast_has_null_recipient(self, db_session, make_agent):
        sender = make_agent()
        msg = TlMessage(
            from_agent_id=sender["id"],
            to_agent_id=None,  # broadcast
            from_project_id=sender["project_id"],
            body="broadcast to all archies",
        )
        db_session.add(msg)
        db_session.flush()
        assert msg.id is not None
        assert msg.to_agent_id is None

    def test_message_spans_projects(self, db_session, make_agent):
        """from_agent and to_agent can live on DIFFERENT projects - the channel
        is cross-project by design."""
        p1_agent = make_agent()
        p2_agent = make_agent()  # auto-creates a separate project
        assert p1_agent["project_id"] != p2_agent["project_id"]
        msg = TlMessage(
            from_agent_id=p1_agent["id"],
            to_agent_id=p2_agent["id"],
            from_project_id=p1_agent["project_id"],
            body="cross-project ping",
        )
        db_session.add(msg)
        db_session.flush()
        assert msg.id is not None

    def test_read_receipt_composite_pk(self, db_session, make_agent):
        sender = make_agent()
        reader = make_agent()
        msg = TlMessage(
            from_agent_id=sender["id"],
            to_agent_id=None,
            from_project_id=sender["project_id"],
            body="track reads",
        )
        db_session.add(msg)
        db_session.flush()

        db_session.add(TlMessageRead(message_id=msg.id, agent_id=reader["id"]))
        db_session.flush()
        row = db_session.get(TlMessageRead, (msg.id, reader["id"]))
        assert row is not None
        assert row.read_at is not None

    def test_read_receipt_cascades_on_message_delete(self, db_session, make_agent):
        """Deleting a message clears its read receipts via ON DELETE CASCADE."""
        sender = make_agent()
        reader = make_agent()
        msg = TlMessage(
            from_agent_id=sender["id"],
            to_agent_id=None,
            from_project_id=sender["project_id"],
            body="will be deleted",
        )
        db_session.add(msg)
        db_session.flush()
        db_session.add(TlMessageRead(message_id=msg.id, agent_id=reader["id"]))
        db_session.flush()
        mid = msg.id

        db_session.delete(msg)
        db_session.flush()
        assert db_session.get(TlMessageRead, (mid, reader["id"])) is None


class TestTlChannelProjectDeleteCleanup:
    """DWB-436: tl_messages.from_project_id is a NOT NULL FK to projects, so a
    project with sent channel messages must still delete cleanly."""

    def test_delete_project_clears_sent_messages(
        self, client, db_session, make_project, make_agent
    ):
        from app.models.agent import Agent

        project = make_project()
        pid = project["id"]
        sender = make_agent()
        reader = make_agent()
        # Home the sender on the project being deleted.
        homed = db_session.get(Agent, sender["id"])
        homed.project_id = pid
        db_session.flush()

        msg = TlMessage(
            from_agent_id=sender["id"],
            to_agent_id=None,
            from_project_id=pid,
            body="sent from the doomed project",
        )
        db_session.add(msg)
        db_session.flush()
        mid = msg.id
        db_session.add(TlMessageRead(message_id=mid, agent_id=reader["id"]))
        db_session.flush()

        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 204
        db_session.expire_all()
        # Message and its read receipt are gone; the sender agent survives.
        assert db_session.get(TlMessage, mid) is None
        assert db_session.get(TlMessageRead, (mid, reader["id"])) is None
        assert db_session.get(Agent, sender["id"]) is not None


class TestTlChannelSend:
    """DWB-437: POST /api/tl-channel - role guard + alert ping."""

    def test_direct_send_creates_message_and_one_alert(
        self, client, db_session, make_agent
    ):
        sender = _tl(make_agent)
        target = _tl(make_agent)
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": "direct hello",
        })
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["status"] == "ok"
        assert data["alert_count"] == 1
        msg = data["message"]
        assert msg["is_broadcast"] is False
        assert msg["to_agent_id"] == target["id"]
        assert msg["from_agent_name"] == sender["name"]
        assert msg["from_project_prefix"] is not None
        # Exactly one alert, addressed to the target.
        alerts = db_session.query(Alert).filter(
            Alert.recipient_agent_id == target["id"]
        ).all()
        assert len(alerts) == 1

    def test_broadcast_pings_every_other_team_lead(
        self, client, db_session, make_agent
    ):
        sender = _tl(make_agent)
        tl2 = _tl(make_agent)
        tl3 = _tl(make_agent)
        worker = make_agent(role="backend-worker")  # must NOT be pinged
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "body": "broadcast to all",
        })
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["message"]["is_broadcast"] is True
        assert data["message"]["to_agent_id"] is None
        # One alert per OTHER team-lead (tl2, tl3) - not the sender, not the worker.
        recipients = {
            a.recipient_agent_id
            for a in db_session.query(Alert).all()
            if a.recipient_agent_id is not None
        }
        assert recipients == {tl2["id"], tl3["id"]}
        assert data["alert_count"] == 2

    def test_send_rejected_when_sender_not_team_lead(self, client, make_agent):
        sender = make_agent(role="backend-worker")
        target = _tl(make_agent)
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": "should fail",
        })
        assert r.status_code == 400
        assert "team-lead" in r.json()["detail"]

    def test_send_rejected_when_recipient_not_team_lead(self, client, make_agent):
        sender = _tl(make_agent)
        target = make_agent(role="pm")
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": "should fail",
        })
        assert r.status_code == 400
        assert "team-lead" in r.json()["detail"]

    def test_send_unknown_recipient_404(self, client, make_agent):
        sender = _tl(make_agent)
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": 999999,
            "body": "no such recipient",
        })
        assert r.status_code == 404

    def test_send_empty_body_400(self, client, make_agent):
        sender = _tl(make_agent)
        target = _tl(make_agent)
        r = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": "   ",
        })
        assert r.status_code == 400


class TestTlChannelList:
    """DWB-437: GET /api/tl-channel - whole channel, cross-project, read-state."""

    def test_list_is_cross_project_most_recent_first(self, client, make_agent):
        a1 = _tl(make_agent)  # project A
        a2 = _tl(make_agent)  # project B
        client.post("/api/tl-channel", json={
            "from_agent_id": a1["id"], "to_agent_id": a2["id"], "body": "first"})
        client.post("/api/tl-channel", json={
            "from_agent_id": a2["id"], "body": "second broadcast"})
        r = client.get("/api/tl-channel")
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) == 2
        # Most-recent-first.
        assert msgs[0]["body"] == "second broadcast"
        assert msgs[1]["body"] == "first"
        # Cross-project: the two messages originate from different projects.
        assert msgs[0]["from_project_id"] != msgs[1]["from_project_id"]
        # Nobody has read yet -> empty read_by roster.
        assert msgs[0]["read_by"] == []

    def test_read_by_roster_carries_reader_names(self, client, make_agent):
        sender = _tl(make_agent)
        reader = _tl(make_agent)
        send = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"], "to_agent_id": reader["id"], "body": "hi"})
        mid = send.json()["message"]["id"]
        # Before read: empty roster (client derives its own read flag from this).
        m = next(x for x in client.get("/api/tl-channel").json() if x["id"] == mid)
        assert m["read_by"] == []
        assert m["read_by_count"] == 0  # convenience mirror of len(read_by)
        # Mark read, then re-check: roster names the reader with a read_at.
        client.post("/api/tl-channel/mark-read", json={
            "agent_id": reader["id"], "message_id": mid})
        m = next(x for x in client.get("/api/tl-channel").json() if x["id"] == mid)
        assert len(m["read_by"]) == 1
        assert m["read_by_count"] == 1
        entry = m["read_by"][0]
        assert entry["agent_id"] == reader["id"]
        assert entry["agent_name"] == reader["name"]
        assert entry["read_at"] is not None


class TestTlChannelUnread:
    """DWB-437: GET /api/tl-channel/unread."""

    def test_unread_includes_broadcasts_and_directs_excludes_own(
        self, client, make_agent
    ):
        me = _tl(make_agent)
        other = _tl(make_agent)
        # Direct to me (unread).
        client.post("/api/tl-channel", json={
            "from_agent_id": other["id"], "to_agent_id": me["id"], "body": "direct to me"})
        # Broadcast by other (unread for me).
        client.post("/api/tl-channel", json={
            "from_agent_id": other["id"], "body": "broadcast"})
        # Direct to other (NOT for me).
        client.post("/api/tl-channel", json={
            "from_agent_id": me["id"], "to_agent_id": other["id"], "body": "to other"})
        # My own broadcast (NOT unread for me).
        client.post("/api/tl-channel", json={
            "from_agent_id": me["id"], "body": "my broadcast"})
        r = client.get(f"/api/tl-channel/unread?agent_id={me['id']}")
        assert r.status_code == 200
        bodies = {m["body"] for m in r.json()}
        assert bodies == {"direct to me", "broadcast"}

    def test_unread_shrinks_after_mark_read_all(self, client, make_agent):
        me = _tl(make_agent)
        other = _tl(make_agent)
        client.post("/api/tl-channel", json={
            "from_agent_id": other["id"], "to_agent_id": me["id"], "body": "a"})
        client.post("/api/tl-channel", json={
            "from_agent_id": other["id"], "body": "b"})
        assert len(client.get(f"/api/tl-channel/unread?agent_id={me['id']}").json()) == 2
        r = client.post("/api/tl-channel/mark-read", json={
            "agent_id": me["id"], "all": True})
        assert r.json()["marked"] == 2
        assert client.get(f"/api/tl-channel/unread?agent_id={me['id']}").json() == []


class TestTlChannelMarkRead:
    """DWB-437: POST /api/tl-channel/mark-read - idempotent."""

    def test_mark_read_idempotent(self, client, make_agent):
        sender = _tl(make_agent)
        me = _tl(make_agent)
        send = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"], "to_agent_id": me["id"], "body": "x"})
        mid = send.json()["message"]["id"]
        first = client.post("/api/tl-channel/mark-read", json={
            "agent_id": me["id"], "message_id": mid})
        assert first.json()["marked"] == 1
        second = client.post("/api/tl-channel/mark-read", json={
            "agent_id": me["id"], "message_id": mid})
        assert second.json()["marked"] == 0

    def test_mark_read_requires_message_or_all(self, client, make_agent):
        me = _tl(make_agent)
        r = client.post("/api/tl-channel/mark-read", json={"agent_id": me["id"]})
        assert r.status_code == 400


class TestChannelPoke:
    """DWB-443: POST /api/hooks/channel-poke - Stop-hook block decision for a
    team-lead with unread channel messages. Never errors the session."""

    def _hook_session(self, db_session, agent_id, project_id, session_id):
        """Seed a hook_session so the poke resolver inherits agent_id from it
        (the same path the tool-use + session-end hooks use)."""
        db_session.add(HookSession(
            session_id=session_id, project_id=project_id, agent_id=agent_id,
            status=HookSessionStatus.active, session_type=HookSessionType.main,
        ))
        db_session.flush()

    def test_poke_blocks_tl_with_unread(self, client, db_session, make_agent):
        recv = _tl(make_agent)
        sender = _tl(make_agent)
        client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"], "to_agent_id": recv["id"],
            "body": "cover the migration"})
        self._hook_session(db_session, recv["id"], recv["project_id"], "poke-sess-1")

        r = client.post("/api/hooks/channel-poke", json={
            "session_id": "poke-sess-1", "hook_event_name": "Stop"})
        assert r.status_code == 200
        data = r.json()
        assert data["decision"] == "block"
        assert "1 Archie Channel message" in data["reason"]
        assert "[direct]" in data["reason"] and sender["name"] in data["reason"]
        assert "cover the migration" in data["reason"]
        assert "/tl" in data["reason"]
        # Surfaced messages were marked read -> a second poke is a no-op.
        r2 = client.post("/api/hooks/channel-poke", json={
            "session_id": "poke-sess-1", "hook_event_name": "Stop"})
        assert r2.json() == {}

    def test_poke_empty_when_no_unread(self, client, db_session, make_agent):
        tl = _tl(make_agent)
        self._hook_session(db_session, tl["id"], tl["project_id"], "poke-sess-2")
        r = client.post("/api/hooks/channel-poke", json={
            "session_id": "poke-sess-2", "hook_event_name": "Stop"})
        assert r.status_code == 200
        assert r.json() == {}

    def test_poke_role_gated_worker_gets_nothing(self, client, db_session, make_agent):
        # A broadcast is visible to the worker's unread query, but the poke is
        # team-lead-only, so the worker gets no block.
        worker = make_agent(role="backend-worker")
        sender = _tl(make_agent)
        client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"], "body": "broadcast"})
        assert len(client.get(f"/api/tl-channel/unread?agent_id={worker['id']}").json()) == 1
        self._hook_session(db_session, worker["id"], worker["project_id"], "poke-sess-3")
        r = client.post("/api/hooks/channel-poke", json={
            "session_id": "poke-sess-3", "hook_event_name": "Stop"})
        assert r.status_code == 200
        assert r.json() == {}

    def test_poke_empty_when_agent_unresolvable(self, client, make_agent):
        # No hook_session, no marker -> agent can't be resolved -> {} (no error).
        r = client.post("/api/hooks/channel-poke", json={
            "session_id": "nonexistent-sess", "hook_event_name": "Stop"})
        assert r.status_code == 200
        assert r.json() == {}

    def test_poke_never_errors_the_session(self, client, db_session, make_agent, monkeypatch):
        recv = _tl(make_agent)
        sender = _tl(make_agent)
        client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"], "to_agent_id": recv["id"], "body": "x"})
        self._hook_session(db_session, recv["id"], recv["project_id"], "poke-sess-4")

        def _boom(*a, **k):
            raise RuntimeError("channel exploded")

        monkeypatch.setattr("app.services.tl_channel.unread_for_agent", _boom)
        r = client.post("/api/hooks/channel-poke", json={
            "session_id": "poke-sess-4", "hook_event_name": "Stop"})
        assert r.status_code == 200
        assert r.json() == {}
