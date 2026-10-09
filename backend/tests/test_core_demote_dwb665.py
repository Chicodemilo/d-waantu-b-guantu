# Path: tests/test_core_demote_dwb665.py
# File: test_core_demote_dwb665.py
# Created: 2026-10-09 (DWB-665)
# Purpose: Guard the only path off CORE. A row moves core -> scar/working end to
#          end through the HTTP route, the ruling is journaled and attributable,
#          the decay clock and fired_count are left alone, and nothing in the
#          consolidation machinery can demote on its own.
# Caller: pytest
# Callees: POST /api/agents/{id}/memories/{mid}/demote,
#          app.services.memory_demote, app.services.memory_score,
#          app.services.memory_consolidate, app.models.agent_memory
# Data In: factory agents/projects, CORE agent_memories rows, DWB sessions
# Data Out: Assertions on the stored tier, the derived score at the new tier,
#           the journal record, and the untouched clock/counter fields
# Last Modified: 2026-10-09 (DWB-665)

"""CORE was a one-way door and a mistake was permanent.

`promote_to_core` is the single write site for `tier = core` and nothing wrote
`core` to any other tier. CORE's curve is flat at 10, so a mis-promoted row
could not decay into `GET /memory/scored`'s demote/evict lists either - those
populate from the derived SCORE BAND. The ruling had nowhere to write and the
row had no way to surface. IND holds 39 rows in exactly that state.

DWB-668 raised the stakes rather than lowering them: CORE is now in the search
population, so a mis-promoted row is a LIVE route into an agent's context at
the top band, on a tier that never decays.

THE 39 IND ROWS ARE NOT REPAIRED BY THIS TICKET and no test here touches them.
Criterion 4 scopes that out; re-tiering real rows is a ruling per row.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.models.journal_entry import JournalEntry
from app.models.project import MemoryMode, Project
from app.services import memory_consolidate, memory_demote, memory_score

FLOOR_SESSIONS = 95


@pytest.fixture
def owner(make_project, make_agent, tmp_path, db_session):
    project_json = make_project(repo_path=str(tmp_path))
    project = db_session.get(Project, project_json["id"])
    project.memory_mode = MemoryMode.human_memory
    db_session.flush()
    agent = make_agent(project_id=project.id)
    return {"project": project, "agent_id": agent["id"]}


def _elapse(db, *, project_id, agent_id, n, tag):
    base = datetime.utcnow() - timedelta(days=400)
    out = []
    for i in range(n):
        s = DwbSession(
            project_id=project_id,
            opened_at=base + timedelta(hours=i),
            closed_at=base + timedelta(hours=i, minutes=30),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
        )
        db.add(s)
        db.flush()
        db.add(
            HookSession(
                session_id=f"dwb665-{tag}-{agent_id}-{i}",
                project_id=project_id,
                agent_id=agent_id,
                dwb_session_id=s.id,
                total_tokens=0,
            )
        )
        db.flush()
        out.append(s)
    return out


@pytest.fixture
def aged_core_row(db_session, owner):
    """A CORE row with a long-elapsed clock, so the test can see whether
    demotion resets it. A fresh row would score 10 at every tier and could not
    distinguish 'kept the clock' from 'reset the clock'."""
    origin = _elapse(
        db_session,
        project_id=owner["project"].id,
        agent_id=owner["agent_id"],
        n=1,
        tag="origin",
    )[0]
    _elapse(
        db_session,
        project_id=owner["project"].id,
        agent_id=owner["agent_id"],
        n=FLOOR_SESSIONS,
        tag="decay",
    )
    row = AgentMemory(
        agent_id=owner["agent_id"],
        tier=MemoryTier.core,
        body="never close a sprint while a worker is writing backend files",
        keywords=["sprint close", "backlog ticket"],
        context_key="DWB-665",
        created_session_id=origin.id,
        fired_count=4,
    )
    db_session.add(row)
    db_session.flush()

    gap = memory_score.sessions_since_reinforced(db_session, row)
    assert gap >= 91, f"fixture did not age: gap={gap}"
    assert memory_score.score(row.tier, gap) == 10, (
        "a CORE row must start at 10 or 'the score changed' proves nothing"
    )
    return {**owner, "memory_id": row.id, "gap": gap}


def _reread(db, memory_id):
    db.expire_all()
    return db.get(AgentMemory, memory_id)


class TestDemotionEndToEnd:
    """ACCEPTANCE 5: a CORE row moved to scar/working, re-read via the API,
    with the new tier and score reflecting it."""

    def test_core_to_scar_through_the_route(self, client, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]
        before = _reread(db_session, memory_id)
        assert before.tier == MemoryTier.core
        assert memory_score.score(before.tier, aged_core_row["gap"]) == 10

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted by a false fire"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["previous_tier"] == "core"
        assert payload["tier"] == "scar"
        assert payload["ruled_by_agent_id"] == agent_id

        row = _reread(db_session, memory_id)
        assert row.tier == MemoryTier.scar

        # THE SCORE, re-derived at the new tier. A row that went core -> scar
        # with 95 elapsed sessions lands on the scar floor.
        gap = memory_score.sessions_since_reinforced(db_session, row)
        assert memory_score.score(row.tier, gap) == 6, (
            "the demoted row is still scoring on CORE's flat curve"
        )

    def test_the_api_read_reflects_the_new_tier_and_score(
        self, client, db_session, aged_core_row
    ):
        """Through `GET /memory/scored`, the read an agent's context is built
        from - not just the ORM row."""
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        before = client.get(f"/api/agents/{agent_id}/memory/scored").json()
        entry = next(e for e in before["entries"] if e["id"] == memory_id)
        assert entry["tier"] == "core" and entry["score"] == 10

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "working", "reason": "the context ended long ago"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        after = client.get(f"/api/agents/{agent_id}/memory/scored").json()
        entry = next(e for e in after["entries"] if e["id"] == memory_id)
        assert entry["tier"] == "working"
        assert entry["score"] == 1
        assert entry["band"] == memory_score.BAND_LAST_CONSOLIDATION

    def test_the_demoted_row_becomes_discoverable_in_a_candidate_list(
        self, client, db_session, aged_core_row
    ):
        """CRITERION 3. A CORE row can never appear in demote/evict/promote
        because its score is pinned at 10. After the ruling it is scored on a
        real curve, so it surfaces where consolidation will see it."""
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        before = client.get(f"/api/agents/{agent_id}/memory/scored").json()
        assert memory_id not in before["evict"] + before["demote"]

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "working", "reason": "never applied to this project"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        after = client.get(f"/api/agents/{agent_id}/memory/scored").json()
        assert memory_id in after["evict"], after["evict"]


class TestWhatDemotionMustNotTouch:
    """The absences are the design, so they are asserted rather than described."""

    def test_the_decay_clock_is_not_reset(self, client, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]
        before = _reread(db_session, memory_id)
        created, reinforced = before.created_session_id, before.last_reinforced_session_id

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        row = _reread(db_session, memory_id)
        assert row.created_session_id == created
        assert row.last_reinforced_session_id == reinforced
        assert memory_score.sessions_since_reinforced(db_session, row) == (
            aged_core_row["gap"]
        ), "resetting the clock would reward the mis-promotion with a fresh life"

    def test_fired_count_survives(self, client, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]
        assert _reread(db_session, memory_id).fired_count == 4

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        assert _reread(db_session, memory_id).fired_count == 4, (
            "the recall history is a fact about what happened, not a property "
            "of the tier - and it is the evidence a future ruling rests on"
        )

    def test_the_context_key_survives(self, client, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        assert _reread(db_session, memory_id).context_key == "DWB-665"

    def test_the_body_and_keywords_survive(self, client, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]
        before = _reread(db_session, memory_id)
        body, keywords = before.body, list(before.keywords or [])

        client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        row = _reread(db_session, memory_id)
        assert row.body == body and list(row.keywords or []) == keywords


class TestTheRulingIsRecorded:
    """CRITERION 2: a deliberate, attributable write - not something that could
    be mistaken for the consolidation machinery acting on its own."""

    def test_the_demotion_is_journaled_with_its_reason(
        self, client, db_session, aged_core_row
    ):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "a false consultation fire in S84"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        entry_id = response.json()["journal_entry_id"]
        entry = db_session.get(JournalEntry, entry_id)
        assert entry is not None
        assert "a false consultation fire in S84" in entry.body
        assert str(memory_id) in entry.body
        assert set(memory_demote.DEMOTION_TAGS) <= set(entry.tags or [])

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_a_blank_reason_is_refused_and_nothing_moves(
        self, client, db_session, aged_core_row, reason
    ):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": reason},
            headers={"X-Agent-ID": str(agent_id)},
        )

        assert response.status_code == 400
        assert _reread(db_session, memory_id).tier == MemoryTier.core

    def test_an_unattributed_demotion_is_refused(
        self, client, db_session, aged_core_row
    ):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
        )

        assert response.status_code == 400
        assert _reread(db_session, memory_id).tier == MemoryTier.core

    def test_a_non_owner_is_refused(
        self, client, db_session, aged_core_row, make_agent
    ):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]
        other = make_agent(project_id=aged_core_row["project"].id)

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": "scar", "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(other["id"])},
        )

        assert response.status_code == 403
        assert _reread(db_session, memory_id).tier == MemoryTier.core

    def test_a_non_core_row_is_refused(self, client, db_session, owner):
        """This is the only door off CORE, not a general set-the-tier route."""
        row = AgentMemory(
            agent_id=owner["agent_id"],
            tier=MemoryTier.scar,
            body="a scar",
            keywords=["sprint close", "backlog ticket"],
        )
        db_session.add(row)
        db_session.flush()

        response = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{row.id}/demote",
            json={"to_tier": "working", "reason": "I disagree with this tier"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )

        assert response.status_code == 400
        assert "not core" in response.json()["detail"]
        assert _reread(db_session, row.id).tier == MemoryTier.scar

    @pytest.mark.parametrize("target", ["core", "raw", "nonsense"])
    def test_an_invalid_target_tier_is_refused(
        self, client, db_session, aged_core_row, target
    ):
        memory_id = aged_core_row["memory_id"]
        agent_id = aged_core_row["agent_id"]

        response = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/demote",
            json={"to_tier": target, "reason": "mis-promoted"},
            headers={"X-Agent-ID": str(agent_id)},
        )

        assert response.status_code in (400, 422)
        assert _reread(db_session, memory_id).tier == MemoryTier.core


class TestNothingAutomaticDemotes:
    """CRITERION 2's other half. CORE is deliberately the tier an algorithm may
    not second-guess a human out of, so the decay machinery must not reach this
    movement even now that a path exists."""

    def test_a_consolidation_pass_leaves_core_alone(self, db_session, aged_core_row):
        memory_id = aged_core_row["memory_id"]

        memory_consolidate.consolidate_agent(
            db_session, agent_id=aged_core_row["agent_id"]
        )

        assert _reread(db_session, memory_id).tier == MemoryTier.core

    def test_the_demote_service_has_exactly_one_caller_and_it_is_the_route(self):
        """A sweep that called this would be indistinguishable from the bug it
        repairs. Asserted against the source rather than trusted."""
        import pathlib

        app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
        callers = sorted(
            str(p.relative_to(app_dir))
            for p in app_dir.rglob("*.py")
            if "demote_from_core" in p.read_text(encoding="utf-8")
            and p.name != "memory_demote.py"
        )
        assert callers == ["routers/agents.py"], callers
