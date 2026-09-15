# Path: tests/test_stick_redemption_dwb537.py
# File: test_stick_redemption_dwb537.py
# Created: 2026-09-15
# Purpose: DWB-537 stick redemption: a `redeem:<score_event_id>` token in a memory append grants HALF of that one stick back, once, automatically. Pins every eligibility branch, the grant shape, the once-per-stick DB guard, and that the append itself always succeeds.
# Caller: pytest
# Callees: POST /api/agents/{id}/memory/append, app.services.stick_redemption, app.services.scoring
# Data In: tmp_path repo, factory project + agent + active sprint, hand-applied score_events
# Data Out: Assertions on the redemption verdict, score_event rows, agent_score cache, memory.md contents
# Last Modified: 2026-09-15 (DWB-544: grant is half rounded up)

"""DWB-537 stick redemption.

Rules under test (Miles ruling): half of THAT stick, exactly once, fully
automatic, zero human review, abuse-proof at the API.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.agent_score import AgentScore
from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.services import scoring
from app.services import stick_redemption as red


# A note long enough to clear MIN_NOTE_CHARS (120) once the token is stripped.
LONG_NOTE = (
    "Lesson: I shipped the migration without checking alembic heads and the "
    "second head bit the TL at commit time. Next time run alembic heads before "
    "writing any revision and merge first."
)
assert len(LONG_NOTE) >= red.MIN_NOTE_CHARS
SHORT_NOTE = "oops, sorry about that"


def _memory_path(repo_path, prefix, name):
    return Path(repo_path) / ".dwb/memory" / prefix / name / "memory.md"


@pytest.fixture
def world(client, tmp_path):
    """Project with repo_path (so appends land), one roster agent, one active
    sprint. Returns ids plus a helper that applies a stick to the agent."""
    project = client.post("/api/projects", json={
        "prefix": "RDM", "name": "Redemption", "repo_path": str(tmp_path),
    }).json()
    pid = project["id"]
    agent = client.post("/api/agents", json={
        "project_id": pid, "name": "Stuck", "role": "backend-worker",
        "api_key": "rdm-stuck",
    }).json()
    other = client.post("/api/agents", json={
        "project_id": pid, "name": "Bystander", "role": "tester",
        "api_key": "rdm-other",
    }).json()
    for a in (agent, other):
        r = client.post("/api/project-agents", json={
            "project_id": pid, "agent_id": a["id"],
        })
        assert r.status_code == 201
    epic = client.post("/api/epics", json={"project_id": pid, "name": "E"}).json()
    sprint = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "redeem",
        "sprint_number": 1, "status": "active",
    }).json()
    return {
        "project": project, "pid": pid, "agent": agent, "aid": agent["id"],
        "other": other, "sprint_id": sprint["id"],
    }


def _stick(db, w, *, delta=-6, subject=None, trigger=ScoreTriggerType.stick,
           source=ScoreSource.human, project_id=None):
    return scoring.apply_score_event(
        db,
        project_id=project_id or w["pid"],
        subject_agent_id=subject or w["aid"],
        sprint_id=w["sprint_id"],
        trigger_type=trigger,
        delta=delta,
        source=source,
        reason="test stick",
    )


def _append(client, w, content, *, header=True, agent_id=None):
    aid = agent_id or w["aid"]
    headers = {"X-Agent-ID": str(w["aid"])} if header else {}
    return client.post(
        f"/api/agents/{aid}/memory/append",
        json={"file": "memory", "content": content},
        headers=headers,
    )


def _reputation(db, w):
    row = db.get(AgentScore, (w["aid"], w["pid"]))
    return row.reputation if row else 0


def _redemptions(db, stick_id):
    return db.execute(
        select(ScoreEvent)
        .where(ScoreEvent.trigger_type == ScoreTriggerType.redemption)
        .where(ScoreEvent.ref_id == stick_id)
    ).scalars().all()


# ---------------------------------------------------------------------------
# Token parsing (the ONE regex)
# ---------------------------------------------------------------------------


class TestTokenParse:
    def test_no_token(self):
        assert red.parse_redeem_token("plain note") == (None, "plain note")

    def test_token_extracted_and_stripped(self):
        sid, rest = red.parse_redeem_token("redeem:42 the rest of the lesson")
        assert sid == 42
        assert rest == "the rest of the lesson"

    def test_token_mid_text(self):
        sid, rest = red.parse_redeem_token("before redeem:7 after")
        assert sid == 7
        assert rest == "before  after"

    def test_first_token_wins(self):
        sid, rest = red.parse_redeem_token("redeem:1 and redeem:2")
        assert sid == 1
        assert "redeem:2" in rest  # second token is just text, never evaluated

    @pytest.mark.parametrize("bad", ["redeem:12x", "xredeem:12", "redeem: 12",
                                     "redeem:", "REDEEM:12", "redeem:-3"])
    def test_malformed_tokens_do_not_match(self, bad):
        assert red.parse_redeem_token(bad)[0] is None


# ---------------------------------------------------------------------------
# Append without a token is unchanged (plus the new response field)
# ---------------------------------------------------------------------------


class TestNoToken:
    def test_plain_append_reports_no_token(self, client, world):
        r = _append(client, world, "a normal note without any token")
        assert r.status_code == 201, r.text
        body = r.json()
        assert set(body.keys()) == {
            "agent_id", "file", "path", "timestamp", "bytes_written", "redemption",
        }
        assert body["redemption"] == {
            "granted": False, "reason": "no redeem token in content",
        }

    def test_plain_append_without_header_still_201(self, client, world):
        r = _append(client, world, "legacy caller, no X-Agent-ID", header=False)
        assert r.status_code == 201, r.text
        assert r.json()["redemption"]["granted"] is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGrant:
    def test_half_back_once(self, client, db_session, world):
        stick = _stick(db_session, world, delta=-6)
        assert _reputation(db_session, world) == -6

        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert r.status_code == 201, r.text
        verdict = r.json()["redemption"]
        assert verdict["granted"] is True
        assert verdict["reason"] == f"redeemed stick #{stick.id}: +3"

        rows = _redemptions(db_session, stick.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.delta == 3
        assert row.source == ScoreSource.auto
        assert row.trigger_type == ScoreTriggerType.redemption
        assert row.ref_type == "score_event"
        assert row.ref_id == stick.id
        assert row.actor_agent_id is None
        assert row.actor_cost == 0
        assert row.subject_agent_id == world["aid"]
        assert row.project_id == world["pid"]
        assert row.sprint_id == world["sprint_id"]
        assert row.reason == f"redeemed stick #{stick.id} via memory note"
        assert _reputation(db_session, world) == -3

        # The memory write landed (token and all - it is the agent's note).
        text = _memory_path(world["project"]["repo_path"], "RDM", "Stuck").read_text()
        assert f"redeem:{stick.id}" in text
        assert LONG_NOTE in text

    @pytest.mark.parametrize("delta,expected", [
        (-1, 1), (-2, 1), (-3, 2), (-5, 3), (-7, 4), (-10, 5),
    ])
    def test_half_rounds_up(self, client, db_session, world, delta, expected):
        """DWB-544 (Miles ruling): half of the stick rounded UP, (abs + 1) // 2."""
        stick = _stick(db_session, world, delta=delta)
        r = _append(client, world, f"{LONG_NOTE} redeem:{stick.id}")
        assert r.json()["redemption"]["granted"] is True, r.text
        assert _redemptions(db_session, stick.id)[0].delta == expected

    @pytest.mark.parametrize("trigger,source", [
        (ScoreTriggerType.peer_demerit, ScoreSource.peer),
        (ScoreTriggerType.audit_demerit, ScoreSource.audit),
    ])
    def test_peer_and_audit_demerits_are_redeemable(
        self, client, db_session, world, trigger, source,
    ):
        stick = _stick(db_session, world, delta=-4, trigger=trigger, source=source)
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert r.json()["redemption"]["granted"] is True, r.text

    def test_within_window_still_ok(self, client, db_session, world):
        stick = _stick(db_session, world, delta=-4)
        stick.created_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=47)
        )
        db_session.flush()
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert r.json()["redemption"]["granted"] is True, r.text

    def test_ledger_exposes_redemption_row(self, client, db_session, world):
        stick = _stick(db_session, world, delta=-6)
        _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        r = client.get(f"/api/agents/{world['aid']}/score",
                       params={"project_id": world["pid"]})
        assert r.status_code == 200
        triggers = [e["trigger_type"] for e in r.json()["ledger"]]
        assert "redemption" in triggers
        assert r.json()["reputation"] == -3


# ---------------------------------------------------------------------------
# Every refusal branch: append still 201, nothing granted, ledger untouched
# ---------------------------------------------------------------------------


def _assert_refused(r, db, world, stick_id, fragment):
    assert r.status_code == 201, r.text
    verdict = r.json()["redemption"]
    assert verdict["granted"] is False
    assert fragment in verdict["reason"], verdict["reason"]
    assert _redemptions(db, stick_id) == []


class TestRefusals:
    def test_missing_header(self, client, db_session, world):
        stick = _stick(db_session, world)
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}", header=False)
        _assert_refused(r, db_session, world, stick.id, "X-Agent-ID must match")
        assert _reputation(db_session, world) == -6

    def test_header_mismatch(self, client, db_session, world):
        stick = _stick(db_session, world)
        r = client.post(
            f"/api/agents/{world['aid']}/memory/append",
            json={"file": "memory", "content": f"redeem:{stick.id} {LONG_NOTE}"},
            headers={"X-Agent-ID": str(world["other"]["id"])},
        )
        _assert_refused(r, db_session, world, stick.id, "X-Agent-ID must match")

    def test_unknown_event(self, client, db_session, world):
        r = _append(client, world, f"redeem:999999 {LONG_NOTE}")
        _assert_refused(r, db_session, world, 999999, "not found on project")

    def test_wrong_project(self, client, db_session, world, make_project):
        other_project = make_project()
        stick = _stick(db_session, world, project_id=other_project["id"])
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, stick.id, "not found on project")

    def test_wrong_subject(self, client, db_session, world):
        stick = _stick(db_session, world, subject=world["other"]["id"])
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, stick.id, "was not given to agent")

    def test_positive_event(self, client, db_session, world):
        carrot = _stick(db_session, world, delta=5, trigger=ScoreTriggerType.carrot)
        r = _append(client, world, f"redeem:{carrot.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, carrot.id, "not a redeemable stick")

    def test_negative_non_stick_trigger(self, client, db_session, world):
        rework = _stick(db_session, world, delta=-3,
                        trigger=ScoreTriggerType.rework, source=ScoreSource.auto)
        r = _append(client, world, f"redeem:{rework.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, rework.id, "not a redeemable stick")

    def test_reverted_stick(self, client, db_session, world):
        stick = _stick(db_session, world)
        scoring.revert_score_event(db_session, stick.id, reason="oops")
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, stick.id, "was reverted")

    def test_expired(self, client, db_session, world):
        stick = _stick(db_session, world)
        stick.created_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=49)
        )
        db_session.flush()
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, stick.id, "window closed")

    def test_short_note(self, client, db_session, world):
        stick = _stick(db_session, world)
        r = _append(client, world, f"redeem:{stick.id} {SHORT_NOTE}")
        _assert_refused(r, db_session, world, stick.id, "note too short")
        # The (short) note still landed in memory.md - append never fails.
        text = _memory_path(world["project"]["repo_path"], "RDM", "Stuck").read_text()
        assert SHORT_NOTE in text

    def test_bare_token_only(self, client, db_session, world):
        stick = _stick(db_session, world)
        r = _append(client, world, f"redeem:{stick.id}")
        _assert_refused(r, db_session, world, stick.id, "note too short")


# ---------------------------------------------------------------------------
# Once per stick: query guard, DB guard, redemption-of-redemption
# ---------------------------------------------------------------------------


class TestOncePerStick:
    def test_second_redeem_refused(self, client, db_session, world):
        stick = _stick(db_session, world, delta=-6)
        first = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert first.json()["redemption"]["granted"] is True
        second = _append(client, world, f"redeem:{stick.id} {LONG_NOTE} again")
        assert second.status_code == 201
        assert second.json()["redemption"] == {
            "granted": False, "reason": f"score_event {stick.id} already redeemed",
        }
        assert len(_redemptions(db_session, stick.id)) == 1
        assert _reputation(db_session, world) == -3  # never cumulative

    def test_redemption_row_not_redeemable(self, client, db_session, world):
        stick = _stick(db_session, world, delta=-6)
        _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        redemption = _redemptions(db_session, stick.id)[0]
        r = _append(client, world, f"redeem:{redemption.id} {LONG_NOTE}")
        _assert_refused(r, db_session, world, redemption.id, "not a redeemable stick")

    def test_reverted_redemption_still_blocks_rerun(self, client, db_session, world):
        """Guard the revert path: a human reverting the half-back does not
        re-open the stick for a second redemption (once per stick, ever), and
        the reverting row (negative, trigger=redemption) is not redeemable."""
        stick = _stick(db_session, world, delta=-6)
        _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        redemption = _redemptions(db_session, stick.id)[0]
        revert = scoring.revert_score_event(db_session, redemption.id, reason="undo")
        assert revert is not None and revert.delta == -3
        assert _reputation(db_session, world) == -6

        again = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert again.json()["redemption"]["granted"] is False
        assert "already redeemed" in again.json()["redemption"]["reason"]

        via_revert = _append(client, world, f"redeem:{revert.id} {LONG_NOTE}")
        assert via_revert.json()["redemption"]["granted"] is False
        assert "not a redeemable stick" in via_revert.json()["redemption"]["reason"]
        assert _reputation(db_session, world) == -6

    def test_db_unique_guard_rejects_duplicate_redemption_row(self, db_session, world):
        """The race-safe half: even if two requests pass the query check, the
        UNIQUE index on redemption_of lets only one redemption row land."""
        stick = _stick(db_session, world, delta=-6)
        first = ScoreEvent(
            project_id=world["pid"], subject_agent_id=world["aid"], delta=3,
            source=ScoreSource.auto, trigger_type=ScoreTriggerType.redemption,
            ref_type="score_event", ref_id=stick.id, reason="first",
        )
        db_session.add(first)
        db_session.flush()
        assert first.redemption_of == stick.id

        with db_session.begin_nested():
            db_session.add(ScoreEvent(
                project_id=world["pid"], subject_agent_id=world["aid"], delta=3,
                source=ScoreSource.auto, trigger_type=ScoreTriggerType.redemption,
                ref_type="score_event", ref_id=stick.id, reason="dup",
            ))
            with pytest.raises(IntegrityError):
                db_session.flush()

    def test_non_redemption_rows_do_not_collide(self, db_session, world):
        """redemption_of is NULL for every non-redemption row, so two reverts
        (ref_type score_event, same shape) never trip the unique index."""
        s1 = _stick(db_session, world, delta=-2)
        s2 = _stick(db_session, world, delta=-2)
        r1 = scoring.revert_score_event(db_session, s1.id)
        r2 = scoring.revert_score_event(db_session, s2.id)
        assert r1.redemption_of is None and r2.redemption_of is None
        # And a revert can share ref_id with a redemption without colliding.
        s3 = _stick(db_session, world, delta=-2)
        scoring.apply_score_event(
            db_session, project_id=world["pid"], subject_agent_id=world["aid"],
            trigger_type=ScoreTriggerType.redemption, delta=1,
            source=ScoreSource.auto, ref_type="score_event", ref_id=s3.id,
        )
        scoring.revert_score_event(db_session, s3.id)

    def test_service_reports_lost_race_as_already_redeemed(
        self, db_session, world, monkeypatch,
    ):
        """If the insert itself hits the unique index (a concurrent grant won
        between our query check and our insert), the verdict is 'already
        redeemed', not a 500."""
        stick = _stick(db_session, world, delta=-6)

        def boom(*a, **k):
            raise IntegrityError("INSERT", {}, Exception("dup redemption_of"))

        monkeypatch.setattr(red.scoring, "apply_score_event", boom)
        rolled = []
        monkeypatch.setattr(db_session, "rollback", lambda: rolled.append(True))
        from app.models.agent import Agent
        from app.models.project import Project
        verdict = red.evaluate_redemption(
            db_session,
            agent=db_session.get(Agent, world["aid"]),
            project=db_session.get(Project, world["pid"]),
            caller_agent_id=world["aid"],
            content=f"redeem:{stick.id} {LONG_NOTE}",
        )
        assert verdict == {
            "granted": False, "reason": f"score_event {stick.id} already redeemed",
        }
        assert rolled == [True]


# ---------------------------------------------------------------------------
# The append never fails because of redemption
# ---------------------------------------------------------------------------


class TestAppendAlwaysSucceeds:
    def test_evaluator_crash_is_swallowed(self, client, db_session, world, monkeypatch):
        stick = _stick(db_session, world)

        def explode(*a, **k):
            raise RuntimeError("evaluator bug")

        monkeypatch.setattr(red, "evaluate_redemption", explode)
        monkeypatch.setattr(db_session, "rollback", lambda: None)
        r = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert r.status_code == 201, r.text
        assert r.json()["redemption"] == {
            "granted": False, "reason": "redemption check failed; append kept",
        }
        text = _memory_path(world["project"]["repo_path"], "RDM", "Stuck").read_text()
        assert LONG_NOTE in text


# ---------------------------------------------------------------------------
# Revert cascade (review finding): a reverted stick takes its redemption along
# ---------------------------------------------------------------------------


class TestRevertCascade:
    def test_reverting_redeemed_stick_reverts_redemption_and_nets_zero(
        self, client, db_session, world,
    ):
        stick = _stick(db_session, world, delta=-6)
        _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        redemption = _redemptions(db_session, stick.id)[0]
        assert _reputation(db_session, world) == -3

        revert = scoring.revert_score_event(db_session, stick.id, reason="human undo")
        assert revert is not None and revert.delta == 6
        db_session.refresh(redemption)
        assert redemption.reverted_by is not None
        cascade = db_session.get(ScoreEvent, redemption.reverted_by)
        assert cascade.delta == -3
        assert cascade.trigger_type == ScoreTriggerType.redemption
        assert cascade.ref_type == "score_event" and cascade.ref_id == redemption.id
        assert cascade.reason == f"revert of redeemed stick {stick.id}"
        assert _reputation(db_session, world) == 0

        # Stick is gone and its redemption is reverted; nothing re-opens.
        again = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert again.json()["redemption"]["granted"] is False
        assert "was reverted" in again.json()["redemption"]["reason"]
        assert len(_redemptions(db_session, stick.id)) == 1

    def test_reverting_unredeemed_stick_unchanged(self, db_session, world):
        stick = _stick(db_session, world, delta=-6)
        before = db_session.scalar(
            select(func.count()).select_from(ScoreEvent)
            .where(ScoreEvent.project_id == world["pid"])
        )
        revert = scoring.revert_score_event(db_session, stick.id)
        after = db_session.scalar(
            select(func.count()).select_from(ScoreEvent)
            .where(ScoreEvent.project_id == world["pid"])
        )
        assert revert.delta == 6
        assert after == before + 1  # exactly one new row, no cascade
        assert _reputation(db_session, world) == 0

    def test_reverting_redemption_directly_leaves_stick_alone(
        self, client, db_session, world,
    ):
        stick = _stick(db_session, world, delta=-6)
        _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        redemption = _redemptions(db_session, stick.id)[0]
        revert = scoring.revert_score_event(db_session, redemption.id, reason="undo")
        assert revert.delta == -3
        db_session.refresh(stick)
        assert stick.reverted_by is None
        assert _reputation(db_session, world) == -6
        # Stick still live, but once-per-stick holds.
        again = _append(client, world, f"redeem:{stick.id} {LONG_NOTE}")
        assert "already redeemed" in again.json()["redemption"]["reason"]
