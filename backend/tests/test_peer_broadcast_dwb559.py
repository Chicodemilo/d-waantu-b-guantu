# Path: tests/test_peer_broadcast_dwb559.py
# File: test_peer_broadcast_dwb559.py
# Created: 2026-09-15
# Purpose: DWB-559: peer carrots and sticks broadcast again (reversing the DWB-463 demotion), at info severity so the critical queue stays human-only, with the carrot pile-on call to action extended to peers and sticks staying notify-only.
# Caller: pytest
# Callees: POST /api/projects/{id}/scores/peer, POST /api/projects/{id}/scores/award, app.services.scoring.broadcast_score_change
# Data In: Factory project with three roster agents and an active sprint
# Data Out: Assertions on alert rows, severity, person, CTA text, and broadcast_count
# Last Modified: 2026-09-15 (DWB-559)

"""DWB-559: "broadcast is the fun part of them" (Miles).

DWB-463 demoted peer scoring to the activity feed to cut alert noise. That is
reversed here for peer scoring: the pile-on is the point of a peer economy and
nothing makes an agent read the feed. Noise is controlled by SEVERITY instead,
so a human award still outranks a peer one in the queue.
"""

import pytest
from sqlalchemy import select

from app.models.alert import Alert, AlertCategory, AlertSeverity


@pytest.fixture
def peer_project(client, make_project, make_agent):
    """Project with three roster agents: an actor, a subject and a bystander."""
    project = make_project()
    pid = project["id"]
    names = {}
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
        names[key] = a
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "peer sprint",
        "sprint_number": 1, "status": "active",
    })
    return {"pid": pid, **names}


def _peer(client, w, delta, reason="clean root-cause find"):
    return client.post(
        f"/api/projects/{w['pid']}/scores/peer",
        json={"subject": str(w["subject"]["id"]), "delta": delta, "reason": reason},
        headers={"X-Agent-ID": str(w["actor"]["id"])},
    )


def _alerts_for(db, w, agent_key):
    return db.scalars(
        select(Alert)
        .where(Alert.project_id == w["pid"])
        .where(Alert.recipient_agent_id == w[agent_key]["id"])
    ).all()


class TestPeerCarrotBroadcasts:
    def test_every_roster_agent_and_the_subject_get_a_row(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        r = _peer(client, w, 3)
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] == 3  # actor, subject, bystander
        for key in ("actor", "subject", "bystander"):
            assert len(_alerts_for(db_session, w, key)) == 1

    def test_subject_row_is_second_person_and_never_a_cta(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        _peer(client, w, 4)
        row = _alerts_for(db_session, w, "subject")[0]
        assert row.title.startswith("You received +4")
        assert row.body.startswith("You received +4")
        assert "Pile on" not in row.body

    def test_observer_row_is_third_person_with_the_pile_on_cta(
        self, client, db_session, peer_project,
    ):
        """The CTA is the whole point of the ruling: others get to pile on."""
        w = peer_project
        _peer(client, w, 3, reason="caught my off-by-one")
        row = _alerts_for(db_session, w, "bystander")[0]
        assert row.title == "PeerSubject559 received +3 from PeerActor559"
        assert "PeerActor559 gave PeerSubject559 +3" in row.body
        assert "for caught my off-by-one" in row.body
        assert "Pile on: /carrot PeerSubject559" in row.body

    def test_info_severity_keeps_the_critical_queue_human_only(
        self, client, db_session, peer_project,
    ):
        """DWB-559 judgment call: reinstating peer broadcast must not drown the
        critical queue, so peer rows are info and human rows stay critical."""
        w = peer_project
        _peer(client, w, 3)
        assert all(a.severity == AlertSeverity.info
                   for a in _alerts_for(db_session, w, "bystander"))

        r = client.post(f"/api/projects/{w['pid']}/scores/award",
                        json={"agent": "PeerSubject559", "delta": 5,
                              "reason": "shipped it"})
        assert r.status_code == 201, r.text
        human = [a for a in _alerts_for(db_session, w, "bystander")
                 if a.severity == AlertSeverity.critical]
        assert human, "human awards must stay critical"

    def test_category_is_scoring(self, client, db_session, peer_project):
        w = peer_project
        _peer(client, w, 3)
        assert all(a.category == AlertCategory.scoring
                   for a in _alerts_for(db_session, w, "bystander"))


class TestPeerStickBroadcasts:
    def test_stick_broadcasts_but_is_notify_only(
        self, client, db_session, peer_project,
    ):
        """Human sticks are notify-only; peer sticks match that. You do not
        invite a pile-on onto a demerit."""
        w = peer_project
        r = _peer(client, w, -4, reason="left the suite red")
        assert r.status_code == 201, r.text
        assert r.json()["broadcast_count"] == 3
        row = _alerts_for(db_session, w, "bystander")[0]
        assert row.title == "PeerSubject559 received -4 from PeerActor559"
        assert "Pile on" not in row.body
        assert "left the suite red" in row.body
        assert row.severity == AlertSeverity.info

    def test_stick_subject_row_is_second_person(
        self, client, db_session, peer_project,
    ):
        w = peer_project
        _peer(client, w, -2)
        row = _alerts_for(db_session, w, "subject")[0]
        assert row.body.startswith("You received -2")
        assert "Pile on" not in row.body


class TestUnchangedPaths:
    def test_feed_event_still_emitted_alongside(self, client, peer_project):
        """DWB-463's activity-feed record is not removed, only supplemented."""
        w = peer_project
        _peer(client, w, 3)
        feed = client.get(f"/api/projects/{w['pid']}/activity-feed").json()
        actions = {e.get("action") for e in (
            feed if isinstance(feed, list) else feed.get("events", [])
        )}
        assert "score_awarded" in actions

    def test_auto_trigger_sources_stay_silent(self, db_session, peer_project):
        """Only human and peer broadcast. Auto-triggers are mechanical and far
        too frequent to alert on; that guard is unchanged."""
        from app.services import scoring

        w = peer_project
        count = scoring.broadcast_score_change(
            db_session, project_id=w["pid"],
            subject_agent_id=w["subject"]["id"],
            subject_name=w["subject"]["name"],
            delta=2, reason="ticket closed", source="auto",
        )
        assert count == 0
        assert _alerts_for(db_session, w, "bystander") == []
