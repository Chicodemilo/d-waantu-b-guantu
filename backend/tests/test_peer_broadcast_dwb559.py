# Path: tests/test_peer_broadcast_dwb559.py
# File: test_peer_broadcast_dwb559.py
# Created: 2026-09-15
# Purpose: DWB-559: peer carrots and sticks notify through the inter-agent comms channel, not alerts. Proves the messages reach every project agent plus the subject with second/third person phrasing and the carrot pile-on invitation, that no alert rows are created, that human awards still alert, and that capture_agent_comms suppresses only the notification and never the score.
# Caller: pytest
# Callees: POST /api/projects/{id}/scores/peer, POST /api/projects/{id}/scores/award, GET /api/projects/{id}/agent-messages, app.services.scoring.notify_peer_score_via_comms
# Data In: Factory project with three roster agents and an active sprint
# Data Out: Assertions on InterAgentMessage rows, alert absence, response counts, and the capture toggle
# Last Modified: 2026-09-15 (DWB-559)

"""DWB-559: the pile-on goes to the AGENTS, not the human's alert queue.

Miles: "does pile-on have to be noisy? maybe we don't see them on the DWB front
end alerts, maybe just agent comms route." So peer carrots and sticks travel
down the inter-agent comms channel that agents read on their next turn, while
the DWB-463 alert demotion stands: a human does not need every peer grant in
their queue. Human /carrot and /stick are unchanged, because those are the
human's own awards.
"""

import pytest
from sqlalchemy import select

from app.models.alert import Alert
from app.models.inter_agent_message import InterAgentMessage
from app.models.project import Project


@pytest.fixture
def peer_project(client, make_project, make_agent):
    """Project with three roster agents: an actor, a subject and a bystander."""
    project = make_project()
    pid = project["id"]
    agents = {}
    for key, name, role in (
        ("actor", "PeerActor559", "backend-worker"),
        ("subject", "PeerSubject559", "frontend-worker"),
        ("bystander", "PeerBystander559", "tester"),
    ):
        a = make_agent(project_id=pid, name=name, role=role,
                       api_key=f"pb559-{key}")
        r = client.post("/api/project-agents", json={
            "project_id": pid, "agent_id": a["id"],
        })
        assert r.status_code == 201
        agents[key] = a
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "peer sprint",
        "sprint_number": 1, "status": "active",
    })
    return {"pid": pid, **agents}


def _peer(client, w, delta, reason="clean root-cause find"):
    return client.post(
        f"/api/projects/{w['pid']}/scores/peer",
        json={"subject": str(w["subject"]["id"]), "delta": delta, "reason": reason},
        headers={"X-Agent-ID": str(w["actor"]["id"])},
    )


def _messages_for(db, w, agent_key):
    return db.scalars(
        select(InterAgentMessage)
        .where(InterAgentMessage.project_id == w["pid"])
        .where(InterAgentMessage.to_agent_id == w[agent_key]["id"])
    ).all()


def _alerts(db, w):
    return db.scalars(
        select(Alert).where(Alert.project_id == w["pid"])
    ).all()


class TestPeerCarrotNotifiesViaComms:
    def test_every_roster_agent_and_the_subject_get_a_message(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        r = _peer(client, w, 3)
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] == 3  # actor, subject, bystander
        for key in ("actor", "subject", "bystander"):
            assert len(_messages_for(db_session, w, key)) == 1

    def test_no_alert_rows_are_created(self, client, db_session, peer_project):
        """The DWB-463 demotion stands for alerts: the human's queue stays
        free of peer chatter."""
        w = peer_project
        _peer(client, w, 3)
        assert _alerts(db_session, w) == []

    def test_subject_message_is_second_person_and_never_a_cta(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        _peer(client, w, 4)
        msg = _messages_for(db_session, w, "subject")[0]
        assert msg.body.startswith("You received +4")
        assert "Pile on" not in msg.body

    def test_observer_message_is_third_person_with_the_pile_on(
        self, client, db_session, peer_project,
    ):
        """The invitation is the whole point of the ruling: others pile on."""
        w = peer_project
        _peer(client, w, 3, reason="caught my off-by-one")
        msg = _messages_for(db_session, w, "bystander")[0]
        assert "PeerActor559 gave PeerSubject559 +3" in msg.body
        assert "for caught my off-by-one" in msg.body
        assert "Pile on: /carrot PeerSubject559" in msg.body

    def test_message_is_attributed_to_the_actor(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        _peer(client, w, 3)
        msg = _messages_for(db_session, w, "bystander")[0]
        assert msg.from_agent_id == w["actor"]["id"]
        assert msg.from_agent_name == "PeerActor559"
        assert msg.to_agent_name == "PeerBystander559"

    def test_messages_surface_on_the_project_comms_endpoint(
        self, client, peer_project,
    ):
        """It has to be readable where agents actually look."""
        w = peer_project
        _peer(client, w, 3)
        r = client.get(f"/api/projects/{w['pid']}/agent-messages")
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["total"] == 3
        bodies = " ".join(row["body"] for row in payload["rows"])
        assert "Pile on: /carrot PeerSubject559" in bodies
        assert "You received +3" in bodies


class TestPeerStickNotifiesButDoesNotInvite:
    def test_stick_reaches_everyone_and_is_notify_only(
        self, client, db_session, peer_project,
    ):
        """Human sticks are notify-only; peer sticks match. You do not invite a
        dogpile onto a demerit."""
        w = peer_project
        r = _peer(client, w, -4, reason="left the suite red")
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] == 3
        msg = _messages_for(db_session, w, "bystander")[0]
        assert "PeerSubject559 received -4" in msg.body
        assert "left the suite red" in msg.body
        assert "Pile on" not in msg.body
        assert _alerts(db_session, w) == []

    def test_stick_subject_message_is_second_person(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        _peer(client, w, -2)
        msg = _messages_for(db_session, w, "subject")[0]
        assert msg.body.startswith("You received -2")
        assert "Pile on" not in msg.body


class TestCaptureToggle:
    def test_toggle_off_suppresses_notification_but_still_scores(
        self, client, db_session, peer_project,
    ):
        """capture_agent_comms governs the channel, so turning it off silences
        the notification. The grant itself is untouched: the ledger row and the
        reputation move both persist."""
        w = peer_project
        db_session.get(Project, w["pid"]).capture_agent_comms = False
        db_session.flush()

        r = _peer(client, w, 3)
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] == 0
        assert _messages_for(db_session, w, "bystander") == []
        assert _alerts(db_session, w) == []
        # Scored anyway.
        assert r.json()["subject_reputation"] == 3
        score = client.get(f"/api/agents/{w['subject']['id']}/score",
                           params={"project_id": w["pid"]}).json()
        assert score["reputation"] == 3
        assert any(e["trigger_type"] == "peer_grant" for e in score["ledger"])


class TestHumanPathUnchanged:
    def test_human_award_still_alerts_and_sends_no_comms(
        self, client, db_session, peer_project,
    ):
        """Miles's own awards stay in the alert queue where he sees them."""
        w = peer_project
        r = client.post(f"/api/projects/{w['pid']}/scores/award",
                        json={"agent": "PeerSubject559", "delta": 5,
                              "reason": "shipped it"})
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] >= 1
        assert _alerts(db_session, w)
        assert _messages_for(db_session, w, "bystander") == []

    def test_direct_broadcast_call_still_refuses_peer_source(
        self, db_session, peer_project,
    ):
        """The alert-path guard is unchanged at the service level."""
        from app.services import scoring

        w = peer_project
        count = scoring.broadcast_score_change(
            db_session, project_id=w["pid"],
            subject_agent_id=w["subject"]["id"],
            subject_name=w["subject"]["name"],
            delta=2, reason="nice catch", source="peer",
            actor_agent_id=w["actor"]["id"], actor_name=w["actor"]["name"],
        )
        assert count == 0
        assert _alerts(db_session, w) == []


class TestFeedEventUnchanged:
    def test_feed_event_still_emitted_alongside(self, client, peer_project):
        """DWB-463's activity-feed record is supplemented, not replaced."""
        w = peer_project
        _peer(client, w, 3)
        feed = client.get(f"/api/projects/{w['pid']}/activity-feed").json()
        actions = {e.get("action") for e in (
            feed if isinstance(feed, list) else feed.get("events", [])
        )}
        assert "score_awarded" in actions
