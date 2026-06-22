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

import pytest

from app.config.scoring import INITIAL_INFLUENCE
from app.models.agent_score import AgentScore
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
