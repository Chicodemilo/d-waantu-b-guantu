# Path: tests/test_scores.py
# File: test_scores.py
# Created: 2026-06-22
# Purpose: DWB-424 acceptance - score_event ledger + agent_score cache: apply
#          helper updates both, rebuild recomputes from the authoritative
#          ledger, revert appends a netting row, idempotency guard, and the
#          read API (leaderboard + per-agent ledger + rebuild).
# Caller: pytest
# Callees: app.services.scoring, GET /api/projects/{id}/scores,
#          GET /api/agents/{id}/score, POST /api/projects/{id}/scores/rebuild
# Data In: Factory-created projects/agents/sprints via conftest fixtures
# Data Out: Assertions on ScoreEvent / AgentScore rows + API responses
# Last Modified: 2026-06-22

"""Tests for the agent scoring ledger + cache + read API (DWB-424)."""

import json

import pytest

from sqlalchemy import select

from app.config.scoring import INITIAL_INFLUENCE
from app.models.activity_log import ActivityLog
from app.models.agent_score import AgentScore
from app.models.alert import Alert, AlertSeverity
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.services import scoring as svc


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


@pytest.fixture
def scored_project(client, make_project, make_agent):
    """A project with two roster agents and an active sprint."""
    project = make_project()
    pid = project["id"]
    a1 = make_agent(project_id=pid, name="ScoreAlpha", role="backend-worker",
                    api_key="score-alpha")
    a2 = make_agent(project_id=pid, name="ScoreBeta", role="frontend-worker",
                    api_key="score-beta")
    _assign(client, pid, a1["id"])
    _assign(client, pid, a2["id"])
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    sprint = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "score sprint",
        "sprint_number": 1, "status": "active",
    }).json()
    return {"project_id": pid, "sprint_id": sprint["id"],
            "a1": a1["id"], "a2": a2["id"]}


class TestApplyScoreEvent:
    def test_inserts_ledger_row_and_updates_cache(self, db_session, scored_project):
        pid, sid, a1 = scored_project["project_id"], scored_project["sprint_id"], scored_project["a1"]
        event = svc.apply_score_event(
            db_session,
            project_id=pid, subject_agent_id=a1, sprint_id=sid,
            trigger_type=ScoreTriggerType.ticket_closed, delta=5,
            source=ScoreSource.auto, reason="closed DWB-1",
            ref_type="ticket", ref_id=1,
        )
        assert event.id is not None
        assert event.delta == 5
        # cache reflects the delta + starting influence.
        cache = db_session.get(AgentScore, (a1, pid))
        assert cache.reputation == 5
        assert cache.influence == INITIAL_INFLUENCE

    def test_multiple_events_accumulate(self, db_session, scored_project):
        pid, sid, a1 = scored_project["project_id"], scored_project["sprint_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              sprint_id=sid, trigger_type=ScoreTriggerType.ticket_closed,
                              delta=5, source=ScoreSource.auto, reason="a")
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              sprint_id=sid, trigger_type=ScoreTriggerType.rework,
                              delta=-8, source=ScoreSource.auto, reason="b")
        cache = db_session.get(AgentScore, (a1, pid))
        assert cache.reputation == -3

    def test_reason_is_optional(self, db_session, scored_project):
        # Human/peer paths (wave 2) may omit the reason; it persists as NULL.
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        event = svc.apply_score_event(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.carrot, delta=3, source=ScoreSource.human,
        )
        assert event.reason is None

    def test_actor_cost_debits_actor_influence(self, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        # a2 grants a1 +5, spending 5 influence (peer economy shape).
        svc.apply_score_event(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.peer_grant, delta=5,
            source=ScoreSource.peer, actor_agent_id=a2, actor_cost=5,
            reason="nice work",
        )
        subject = db_session.get(AgentScore, (a1, pid))
        actor = db_session.get(AgentScore, (a2, pid))
        assert subject.reputation == 5
        assert actor.influence == INITIAL_INFLUENCE - 5


class TestRebuild:
    def test_rebuild_recomputes_from_ledger(self, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x")
        # Corrupt the cache, then prove rebuild restores it from the ledger.
        cache = db_session.get(AgentScore, (a1, pid))
        cache.reputation = 999
        db_session.flush()
        touched = svc.rebuild_agent_scores(db_session, pid)
        assert touched >= 1
        db_session.refresh(cache)
        assert cache.reputation == 5

    def test_rebuild_resets_drained_agent(self, db_session, scored_project):
        """A cache row whose ledger events were all removed must reset to
        0 / INITIAL_INFLUENCE, not keep stale values (DWB-427 follow-up)."""
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        ev = svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                                   trigger_type=ScoreTriggerType.ticket_closed, delta=7,
                                   source=ScoreSource.auto, reason="x")
        svc.rebuild_agent_scores(db_session, pid)
        cache = db_session.get(AgentScore, (a1, pid))
        assert cache.reputation == 7
        # Remove all of the agent's ledger events, then rebuild again.
        db_session.delete(db_session.get(ScoreEvent, ev.id))
        db_session.commit()
        svc.rebuild_agent_scores(db_session, pid)
        db_session.refresh(cache)
        assert cache.reputation == 0
        assert cache.influence == INITIAL_INFLUENCE


class TestRevert:
    def test_revert_nets_out_and_stamps_original(self, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        original = svc.apply_score_event(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.stick, delta=-8,
            source=ScoreSource.human, reason="bad",
        )
        revert = svc.revert_score_event(db_session, original.id, reason="my mistake")
        assert revert is not None
        assert revert.delta == 8
        db_session.refresh(original)
        assert original.reverted_by == revert.id
        # net reputation back to zero.
        cache = db_session.get(AgentScore, (a1, pid))
        assert cache.reputation == 0

    def test_double_revert_is_noop(self, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        original = svc.apply_score_event(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.stick, delta=-2,
            source=ScoreSource.human, reason="x",
        )
        svc.revert_score_event(db_session, original.id)
        assert svc.revert_score_event(db_session, original.id) is None


class TestIdempotencyGuard:
    def test_event_exists_for_ref(self, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        assert not svc.event_exists_for_ref(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.ticket_closed,
            ref_type="ticket", ref_id=42,
        )
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x",
                              ref_type="ticket", ref_id=42)
        assert svc.event_exists_for_ref(
            db_session, project_id=pid, subject_agent_id=a1,
            trigger_type=ScoreTriggerType.ticket_closed,
            ref_type="ticket", ref_id=42,
        )


class TestLeaderboardAPI:
    def test_leaderboard_sorted_with_sprint_delta_and_influence(
        self, db_session, client, scored_project,
    ):
        pid, sid = scored_project["project_id"], scored_project["sprint_id"]
        a1, a2 = scored_project["a1"], scored_project["a2"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              sprint_id=sid, trigger_type=ScoreTriggerType.ticket_closed,
                              delta=10, source=ScoreSource.auto, reason="x")
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a2,
                              sprint_id=sid, trigger_type=ScoreTriggerType.ticket_closed,
                              delta=3, source=ScoreSource.auto, reason="y")

        rows = client.get(f"/api/projects/{pid}/scores").json()
        assert [r["agent_id"] for r in rows] == [a1, a2]  # sorted desc by reputation
        assert rows[0]["reputation"] == 10
        assert rows[0]["sprint_delta"] == 10
        assert rows[0]["influence"] == INITIAL_INFLUENCE
        assert rows[1]["reputation"] == 3

    def test_leaderboard_includes_roster_agent_with_no_events(
        self, client, scored_project,
    ):
        pid, a2 = scored_project["project_id"], scored_project["a2"]
        rows = client.get(f"/api/projects/{pid}/scores").json()
        beta = [r for r in rows if r["agent_id"] == a2][0]
        assert beta["reputation"] == 0
        assert beta["influence"] == INITIAL_INFLUENCE
        assert beta["sprint_delta"] == 0

    def test_leaderboard_404_unknown_project(self, client):
        assert client.get("/api/projects/999999/scores").status_code == 404


class TestAgentScoreAPI:
    def test_agent_ledger_returns_events_with_reasons(
        self, db_session, client, scored_project,
    ):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="closed the ticket")
        data = client.get(f"/api/agents/{a1}/score", params={"project_id": pid}).json()
        assert data["reputation"] == 5
        assert data["influence"] == INITIAL_INFLUENCE
        assert len(data["ledger"]) == 1
        assert data["ledger"][0]["reason"] == "closed the ticket"
        assert data["ledger"][0]["trigger_type"] == "ticket_closed"

    def test_agent_score_defaults_project_from_home(self, client, scored_project):
        a1 = scored_project["a1"]
        # No project_id query param -> uses the agent's home project.
        data = client.get(f"/api/agents/{a1}/score").json()
        assert data["project_id"] == scored_project["project_id"]

    def test_agent_score_404_unknown_agent(self, client):
        assert client.get("/api/agents/999999/score").status_code == 404


class TestRebuildAPI:
    def test_rebuild_endpoint(self, db_session, client, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x")
        r = client.post(f"/api/projects/{pid}/scores/rebuild")
        assert r.status_code == 200
        assert r.json()["agents_rebuilt"] >= 1


class TestHumanAward:
    def test_carrot_by_name_awards_and_broadcasts(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": "ScoreAlpha", "delta": 10, "reason": "great work",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["subject_agent_id"] == a1
        assert data["delta"] == 10
        assert data["trigger_type"] == "carrot"
        assert data["reputation"] == 10
        # broadcast to both roster agents (a1 + a2)
        assert data["broadcast_count"] == 2

        ev = db_session.scalars(
            select(ScoreEvent).where(ScoreEvent.subject_agent_id == a1)
        ).first()
        assert ev.source == ScoreSource.human
        assert ev.trigger_type == ScoreTriggerType.carrot
        assert ev.actor_agent_id is None and ev.actor_cost == 0

        # subject's own alert is direct + recipient-tagged + elevated severity
        subj_alert = db_session.scalars(
            select(Alert).where(Alert.recipient_agent_id == a1)
            .where(Alert.project_id == pid)
        ).first()
        assert subj_alert.severity == AlertSeverity.critical
        assert "You received +10 from the human" in subj_alert.title
        assert "great work" in subj_alert.body
        # peer's alert is third-person
        other_alert = db_session.scalars(
            select(Alert).where(Alert.recipient_agent_id == a2)
            .where(Alert.project_id == pid)
        ).first()
        assert "ScoreAlpha received +10 from the human" in other_alert.title

    def test_stick_uses_negative_trigger(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": str(a1), "delta": -4, "reason": "regression",
        })
        assert r.status_code == 201
        assert r.json()["trigger_type"] == "stick"
        assert r.json()["reputation"] == -4

    def test_reason_optional(self, client, scored_project):
        pid, a2 = scored_project["project_id"], scored_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": str(a2), "delta": 3,
        })
        assert r.status_code == 201

    def test_zero_delta_rejected(self, client, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": str(a1), "delta": 0,
        })
        assert r.status_code == 400

    def test_unknown_agent_404(self, client, scored_project):
        pid = scored_project["project_id"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": "NoSuchAgent", "delta": 5,
        })
        assert r.status_code == 404


class TestAgentLookupByName:
    def test_score_lookup_by_name(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x")
        r = client.get(f"/api/projects/{pid}/scores/agent", params={"agent": "ScoreAlpha"})
        assert r.status_code == 200
        data = r.json()
        assert data["agent_id"] == a1
        assert data["reputation"] == 5
        assert len(data["ledger"]) == 1

    def test_lookup_unknown_name_404(self, client, scored_project):
        pid = scored_project["project_id"]
        r = client.get(f"/api/projects/{pid}/scores/agent", params={"agent": "Ghost"})
        assert r.status_code == 404


class TestStanding:
    def _board(self, client, db_session, make_project, make_agent, reps):
        """Build a project with len(reps) rostered agents; agent i gets
        reputation reps[i] via a ticket_closed event (so it has score events).
        Returns (project_id, [agent_ids in creation order])."""
        project = make_project()
        pid = project["id"]
        ids = []
        for i, rep in enumerate(reps):
            a = make_agent(project_id=pid, name=f"Stand{i}_{pid}",
                           role="backend-worker", api_key=f"stand-{pid}-{i}")
            client.post("/api/project-agents", json={"project_id": pid, "agent_id": a["id"]})
            ids.append(a["id"])
            if rep != 0:
                svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a["id"],
                                      trigger_type=ScoreTriggerType.ticket_closed, delta=rep,
                                      source=ScoreSource.auto, reason="seed")
        return pid, ids

    def test_full_tier_ladder_eight_agents(self, client, db_session, make_project, make_agent):
        # descending reputations -> ranks 1..8
        reps = [80, 70, 60, 50, 40, 30, 20, 10]
        pid, ids = self._board(client, db_session, make_project, make_agent, reps)
        expected = ["best", "podium", "above", "above", "mid", "mid", "below", "dead_last"]
        for idx, agent_id in enumerate(ids):
            st = svc.get_standing(db_session, agent_id, pid)
            assert st["rank"] == idx + 1, (idx, st)
            assert st["total"] == 8
            assert st["tier"] == expected[idx], (idx, st)
        # #1 facts
        top = svc.get_standing(db_session, ids[0], pid)
        assert top["reputation"] == 80 and top["tier"] == "best"

    def test_unscored_tier(self, client, db_session, make_project, make_agent):
        project = make_project()
        pid = project["id"]
        scored = make_agent(project_id=pid, name=f"Scored_{pid}", role="backend-worker",
                            api_key=f"sc-{pid}")
        unscored = make_agent(project_id=pid, name=f"Unscored_{pid}", role="backend-worker",
                              api_key=f"un-{pid}")
        for a in (scored, unscored):
            client.post("/api/project-agents", json={"project_id": pid, "agent_id": a["id"]})
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=scored["id"],
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x")
        st = svc.get_standing(db_session, unscored["id"], pid)
        assert st["tier"] == "unscored"
        assert st["reputation"] == 0

    def test_tiny_roster_two_agents(self, client, db_session, make_project, make_agent):
        pid, ids = self._board(client, db_session, make_project, make_agent, [5, 2])
        assert svc.get_standing(db_session, ids[0], pid)["tier"] == "best"
        assert svc.get_standing(db_session, ids[1], pid)["tier"] == "dead_last"

    def test_off_roster_agent_returns_none(self, client, db_session, scored_project, make_agent):
        pid = scored_project["project_id"]
        outsider = make_agent(name=f"OffRoster_{pid}", role="backend-worker",
                              api_key=f"off-{pid}")
        assert svc.get_standing(db_session, outsider["id"], pid) is None


class TestProjectMembershipGuard:
    """DWB-430: scores can only be written against agents on the project."""

    def test_award_rejects_non_member_subject(self, client, scored_project, make_agent):
        pid = scored_project["project_id"]
        outsider = make_agent(name="Outsider430A", role="backend-worker",
                              api_key="outsider-430a")  # own project, not on pid
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": "Outsider430A", "delta": 5,
        })
        assert r.status_code == 404
        assert "not on project" in r.json()["detail"].lower()

    def test_award_unknown_name_distinct_message(self, client, scored_project):
        pid = scored_project["project_id"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": "NoSuchAgent430", "delta": 5,
        })
        assert r.status_code == 404
        detail = r.json()["detail"].lower()
        assert "not found" in detail
        assert "not on project" not in detail  # distinct from the membership msg

    def test_award_member_still_succeeds(self, client, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        r = client.post(f"/api/projects/{pid}/scores/award", json={
            "agent": str(a1), "delta": 5,
        })
        assert r.status_code == 201

    def test_peer_rejects_non_member_subject(self, client, scored_project, make_agent):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        outsider = make_agent(name="Outsider430B", role="backend-worker",
                              api_key="outsider-430b")
        r = client.post(f"/api/projects/{pid}/scores/peer",
                        json={"subject": "Outsider430B", "delta": 5},
                        headers={"X-Agent-ID": str(a1)})
        assert r.status_code == 404
        assert "not on project" in r.json()["detail"].lower()

    def test_peer_rejects_non_member_actor(self, client, scored_project, make_agent):
        pid, a2 = scored_project["project_id"], scored_project["a2"]
        outsider = make_agent(name="Outsider430C", role="backend-worker",
                              api_key="outsider-430c")
        r = client.post(f"/api/projects/{pid}/scores/peer",
                        json={"subject": str(a2), "delta": 5},
                        headers={"X-Agent-ID": str(outsider["id"])})
        assert r.status_code == 404
        assert "not on project" in r.json()["detail"].lower()

    def test_peer_member_to_member_still_succeeds(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/peer",
                        json={"subject": str(a2), "delta": 5},
                        headers={"X-Agent-ID": str(a1)})
        assert r.status_code == 201


class TestPeerEconomy:
    def _peer(self, client, pid, actor_id, subject, delta, reason=None):
        body = {"subject": str(subject), "delta": delta}
        if reason is not None:
            body["reason"] = reason
        return client.post(f"/api/projects/{pid}/scores/peer", json=body,
                           headers={"X-Agent-ID": str(actor_id)})

    def test_peer_grant_moves_rep_and_spends_influence(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        r = self._peer(client, pid, a1, a2, 5, "nice fix")
        assert r.status_code == 201
        data = r.json()
        assert data["trigger_type"] == "peer_grant"
        assert data["subject_reputation"] == 5
        assert data["actor_influence_remaining"] == INITIAL_INFLUENCE - 5
        ev = db_session.scalars(
            select(ScoreEvent).where(ScoreEvent.subject_agent_id == a2)
            .where(ScoreEvent.source == ScoreSource.peer)
        ).first()
        assert ev.actor_agent_id == a1 and ev.actor_cost == 5
        # broadcast at NORMAL (info) severity
        alert = db_session.scalars(
            select(Alert).where(Alert.recipient_agent_id == a2)
            .where(Alert.project_id == pid)
        ).first()
        assert alert.severity == AlertSeverity.info

    def test_peer_demerit(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        r = self._peer(client, pid, a1, a2, -4)
        assert r.status_code == 201
        assert r.json()["trigger_type"] == "peer_demerit"
        assert r.json()["subject_reputation"] == -4
        assert r.json()["actor_influence_remaining"] == INITIAL_INFLUENCE - 4

    def test_no_self_scoring(self, client, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        r = self._peer(client, pid, a1, a1, 3)
        assert r.status_code == 400
        assert "self" in r.json()["detail"].lower()

    def test_insufficient_influence_rejected(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        # grant 25 > 20 budget
        r = self._peer(client, pid, a1, a2, 25)
        assert r.status_code == 400
        assert "influence" in r.json()["detail"].lower()

    def test_per_action_ding_cap(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        r = self._peer(client, pid, a1, a2, -6)  # > MAX_DING_PER_ACTION (5)
        assert r.status_code == 400
        assert "per-action" in r.json()["detail"].lower()

    def test_per_target_ding_cap_across_sprint(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        assert self._peer(client, pid, a1, a2, -5).status_code == 201
        assert self._peer(client, pid, a1, a2, -5).status_code == 201  # total 10 = cap
        r = self._peer(client, pid, a1, a2, -1)  # 11 > 10
        assert r.status_code == 400
        assert "per-target ding cap" in r.json()["detail"].lower()

    def test_per_target_grant_cap_across_sprint(self, client, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        assert self._peer(client, pid, a1, a2, 5).status_code == 201
        assert self._peer(client, pid, a1, a2, 5).status_code == 201  # total 10 = cap
        r = self._peer(client, pid, a1, a2, 1)  # 11 > 10
        assert r.status_code == 400
        assert "per-target grant cap" in r.json()["detail"].lower()

    def test_missing_actor_header_rejected(self, client, scored_project):
        pid, a2 = scored_project["project_id"], scored_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/peer", json={"subject": str(a2), "delta": 3})
        assert r.status_code == 400
        assert "x-agent-id" in r.json()["detail"].lower()

    def test_unknown_subject_404(self, client, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        r = self._peer(client, pid, a1, "Ghost", 3)
        assert r.status_code == 404

    def test_influence_is_ledger_derived_and_rebuildable(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        self._peer(client, pid, a1, a2, 5)
        # leaderboard reflects spend; rebuild keeps it consistent
        before = {r["agent_id"]: r["influence"] for r in client.get(f"/api/projects/{pid}/scores").json()}
        assert before[a1] == INITIAL_INFLUENCE - 5
        svc.rebuild_agent_scores(db_session, pid)
        after = {r["agent_id"]: r["influence"] for r in client.get(f"/api/projects/{pid}/scores").json()}
        assert after[a1] == INITIAL_INFLUENCE - 5


def _activity(db, project_id, action):
    rows = db.scalars(
        select(ActivityLog)
        .where(ActivityLog.project_id == project_id)
        .where(ActivityLog.action == action)
    ).all()
    out = []
    for r in rows:
        d = r.details
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except (ValueError, TypeError):
                pass
        out.append((r, d))
    return out


class TestScoreFeedEvents:
    """DWB-432: human + peer scores emit score_awarded / score_docked feed
    events; auto-triggers do NOT."""

    def test_human_carrot_emits_score_awarded(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        client.post(f"/api/projects/{pid}/scores/award",
                    json={"agent": str(a1), "delta": 7, "reason": "shipped it"})
        rows = _activity(db_session, pid, "score_awarded")
        assert len(rows) == 1
        row, details = rows[0]
        assert row.entity_type == "agent"
        assert row.entity_id == a1
        assert details["delta"] == 7
        assert details["source"] == "human"
        assert details["agent"] == "ScoreAlpha"
        assert details["reason"] == "shipped it"

    def test_human_stick_emits_score_docked_signed_delta(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        client.post(f"/api/projects/{pid}/scores/award",
                    json={"agent": str(a1), "delta": -4, "reason": "regression"})
        rows = _activity(db_session, pid, "score_docked")
        assert len(rows) == 1
        _row, details = rows[0]
        assert details["delta"] == -4  # signed
        assert details["source"] == "human"

    def test_reason_truncated_to_100(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        long_reason = "x" * 250
        client.post(f"/api/projects/{pid}/scores/award",
                    json={"agent": str(a1), "delta": 3, "reason": long_reason})
        _row, details = _activity(db_session, pid, "score_awarded")[0]
        assert len(details["reason"]) == 100

    def test_peer_emits_feed_event_with_source_peer(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        client.post(f"/api/projects/{pid}/scores/peer",
                    json={"subject": str(a2), "delta": 5},
                    headers={"X-Agent-ID": str(a1)})
        rows = _activity(db_session, pid, "score_awarded")
        assert len(rows) == 1
        row, details = rows[0]
        assert row.entity_id == a2
        assert row.agent_id == a1  # actor recorded as the activity agent
        assert details["source"] == "peer"

    def test_auto_trigger_does_not_emit_score_feed_event(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="auto")
        assert _activity(db_session, pid, "score_awarded") == []
        assert _activity(db_session, pid, "score_docked") == []


class TestLeadChange:
    """DWB-432: lead_change fires when a score write flips the project #1."""

    def test_first_leader_emits_lead_change(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        client.post(f"/api/projects/{pid}/scores/award",
                    json={"agent": str(a1), "delta": 5})
        rows = _activity(db_session, pid, "lead_change")
        assert len(rows) == 1
        _row, details = rows[0]
        assert details["new_leader"] == "ScoreAlpha"
        assert details["previous_leader"] is None

    def test_overtaking_emits_lead_change(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        client.post(f"/api/projects/{pid}/scores/award", json={"agent": str(a1), "delta": 5})
        client.post(f"/api/projects/{pid}/scores/award", json={"agent": str(a2), "delta": 10})
        rows = _activity(db_session, pid, "lead_change")
        # one for first leader (a1), one for a2 overtaking
        assert len(rows) == 2
        _row, last = rows[0] if rows[0][0].id > rows[1][0].id else rows[1]
        assert last["new_leader"] == "ScoreBeta"
        assert last["previous_leader"] == "ScoreAlpha"

    def test_no_lead_change_when_leader_unchanged(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        client.post(f"/api/projects/{pid}/scores/award", json={"agent": str(a1), "delta": 10})
        client.post(f"/api/projects/{pid}/scores/award", json={"agent": str(a1), "delta": 3})
        # only the first award changed the leader (None -> a1)
        assert len(_activity(db_session, pid, "lead_change")) == 1

    def test_fires_for_auto_source(self, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="auto")
        assert len(_activity(db_session, pid, "lead_change")) == 1


class TestRankAndTier:
    """DWB-432: rank + tier on leaderboard rows and agent-score detail."""

    def test_leaderboard_rows_have_rank_and_tier(self, client, db_session, scored_project):
        pid, a1, a2 = scored_project["project_id"], scored_project["a1"], scored_project["a2"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=10,
                              source=ScoreSource.auto, reason="x")
        rows = client.get(f"/api/projects/{pid}/scores").json()
        assert rows[0]["rank"] == 1 and rows[0]["tier"] == "best"
        # a2 has no events -> unscored even though ranked last
        beta = [r for r in rows if r["agent_id"] == a2][0]
        assert beta["tier"] == "unscored"
        assert all("rank" in r and "tier" in r for r in rows)

    def test_agent_detail_has_rank_and_tier(self, client, db_session, scored_project):
        pid, a1 = scored_project["project_id"], scored_project["a1"]
        svc.apply_score_event(db_session, project_id=pid, subject_agent_id=a1,
                              trigger_type=ScoreTriggerType.ticket_closed, delta=5,
                              source=ScoreSource.auto, reason="x")
        data = client.get(f"/api/agents/{a1}/score", params={"project_id": pid}).json()
        assert data["rank"] == 1
        assert data["tier"] == "best"
