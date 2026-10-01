# Path: tests/test_raw_memory_write_dwb586.py
# File: test_raw_memory_write_dwb586.py
# Created: 2026-09-29 (DWB-586)
# Purpose: Guard the raw memory write - that it writes `raw` and never NULL,
#          that both session states are reported distinguishably, that no
#          request shape sets a tier, and that it stamps the write-on-close gate.
# Caller: pytest
# Callees: app.services.raw_memory, POST /api/agents/{id}/memories
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on responses and on the persisted row
# Last Modified: 2026-09-29 (DWB-586)

"""DWB-586 acceptance, spec section 4 and section 7 hard rule 5.

The two acceptance criteria drive the two big classes here.

AC1 is about AMBIGUITY, not about sessions. A write with no open session is
accepted, and the caller must be able to tell that from a write that landed in
one. So the tests assert the two responses DIFFER, not merely that each is
individually plausible - a bug that reported `none_open` for everything passes
every single-response assertion in isolation.

AC2 is about the refusal NAMING its reason. Asserting a 400 is not enough: a
400 for the wrong reason (say, a Pydantic type error) reads identically to the
caller, so the tests assert on the rule text as well as the status.
"""

import pytest

from app.models.agent import Agent
from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.services import raw_memory


@pytest.fixture
def human_memory_agent(make_project, make_agent):
    """An agent on its own project, with no DWB session open.

    Its own project matters: the session lookup is per-project and the
    single-active invariant is a per-project UNIQUE index, so a shared project
    would let one test's open session leak into another's "no session" case.
    """
    project = make_project()
    return make_agent(project_id=project["id"]), project


def _open_session(client, project_id):
    r = client.post(
        "/api/sessions/open",
        json={"project_id": project_id, "open_method": "slash"},
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestSessionStamping:
    """AC1: both session states land, and they are distinguishable."""

    def test_write_during_open_session_carries_that_session_id(
        self, client, human_memory_agent
    ):
        agent, project = human_memory_agent
        session = _open_session(client, project["id"])

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "the gate read the heading, not the column"},
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["created_session_id"] == session["id"]
        assert row["session_state"] == raw_memory.SESSION_OPEN

    def test_write_with_no_open_session_is_accepted_and_says_so(
        self, client, human_memory_agent
    ):
        agent, _project = human_memory_agent

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "encoded with nobody watching"},
        )
        # Accepted, not refused: losing the lesson because the bookkeeping was
        # not ready is the worse outcome (spec section 4).
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["created_session_id"] is None
        assert row["session_state"] == raw_memory.SESSION_NONE_OPEN

    def test_the_two_session_states_are_distinguishable(
        self, client, make_project, make_agent
    ):
        """The point of AC1, asserted directly rather than implied by the two
        tests above.

        Both of those pass against a build that reports `none_open` for every
        write, because each only ever sees one of the two cases. This one holds
        both responses at once and asserts they differ, which is the only shape
        that catches a collapsed vocabulary.
        """
        closed_project = make_project()
        closed_agent = make_agent(project_id=closed_project["id"])
        open_project = make_project()
        open_agent = make_agent(project_id=open_project["id"])
        _open_session(client, open_project["id"])

        without = client.post(
            f"/api/agents/{closed_agent['id']}/memories", json={"body": "no session"}
        ).json()
        within = client.post(
            f"/api/agents/{open_agent['id']}/memories", json={"body": "in session"}
        ).json()

        assert without["session_state"] != within["session_state"]
        assert without["created_session_id"] != within["created_session_id"]
        # And neither state is an absence of information: both are named.
        assert without["session_state"] and within["session_state"]


class TestTierIsNotSettable:
    """AC2, widened: no request shape sets a tier, and CORE cites its rule."""

    def test_core_is_refused_and_the_refusal_names_the_rule(
        self, client, human_memory_agent
    ):
        agent, _project = human_memory_agent
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "a ruling", "tier": "core"},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        # The rule itself, not just a refusal. A 400 that says "invalid tier"
        # teaches nothing about why CORE in particular is unreachable.
        assert "hard rule 5" in detail
        assert "human" in detail
        assert "evidence" in detail

    @pytest.mark.parametrize("tier", [t.value for t in MemoryTier])
    def test_no_tier_value_is_settable(self, client, make_project, make_agent, tier):
        """Parametrized over the ENUM, not over a hand-listed set.

        A tier added to MemoryTier later is covered by this test the day it is
        added. A hand-written list would pass silently and leave the new value
        settable, which is exactly the hole section 4 exists to close.
        """
        project = make_project()
        agent = make_agent(project_id=project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "trying to tier at write time", "tier": tier},
        )
        assert r.status_code == 400, f"tier {tier!r} was accepted: {r.text}"

    def test_a_refused_write_persists_nothing(
        self, client, db_session, human_memory_agent
    ):
        agent, _project = human_memory_agent
        client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "should not land", "tier": "scar"},
        )
        rows = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent["id"])
            .all()
        )
        assert rows == []


class TestWhatLandsInTheRow:
    """The written row is `raw`, and that is asserted against a row that exists."""

    def test_the_written_tier_is_raw_and_not_null(
        self, client, db_session, human_memory_agent
    ):
        """DWB-584 chose `raw` as an enum value over a nullable tier so the
        scoring query has to NAME it to exclude it. This asserts the write side
        of that choice: a NULL here would let DWB-585 drop the row silently.

        The absence claim (tier is not NULL) is made against a row this test can
        SEE - it asserts the id, body and agent first. An absence assertion over
        a result set that is empty for an unrelated reason passes trivially, and
        that is the failure family this suite is trying not to join.
        """
        agent, _project = human_memory_agent
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "raw and unsorted", "context_key": "node-index-v1"},
        )
        assert r.status_code == 201, r.text
        written = r.json()

        row = db_session.get(AgentMemory, written["id"])
        assert row is not None, "nothing was persisted; the checks below are vacuous"
        assert row.agent_id == agent["id"]
        assert row.body == "raw and unsorted"
        assert row.context_key == "node-index-v1"
        # Only now is the negative meaningful.
        assert row.tier is not None
        assert row.tier == MemoryTier.raw

    def test_the_moment_tags_land_on_the_memory_row(
        self, client, db_session, human_memory_agent
    ):
        """Section 4's tags live on the MEMORY, not the journal (section 6 as
        amended 2026-09-29): all three are read against memories, and section 2
        gates the SCAN on `cost`.

        Asserted against the persisted row rather than the response, because a
        response can echo back a field the write never stored.
        """
        agent, _project = human_memory_agent
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={
                "body": "the migration was already at head",
                "cost": "high",
                "caught_by": "human",
                "surprised": True,
            },
        )
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row is not None, "nothing persisted; the checks below are vacuous"
        assert row.cost == MemoryCost.high
        assert row.caught_by == MemoryCaughtBy.human
        assert row.surprised is True

    def test_surprised_is_tri_state_not_a_boolean(
        self, client, db_session, human_memory_agent
    ):
        """"Was not surprised" and "was never asked" are different facts.

        Section 1 makes prediction error the driver of encoding strength, so a
        write that defaults an unanswered `surprised` to False would record a
        measurement nobody took.
        """
        agent, _project = human_memory_agent
        unasked = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "nobody said"}
        ).json()
        said_no = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "expected it", "surprised": False},
        ).json()

        assert db_session.get(AgentMemory, unasked["id"]).surprised is None
        assert db_session.get(AgentMemory, said_no["id"]).surprised is False

    @pytest.mark.parametrize(
        "field,enum",
        [("cost", MemoryCost), ("caught_by", MemoryCaughtBy)],
    )
    def test_every_enum_value_is_accepted(
        self, client, make_project, make_agent, field, enum
    ):
        """Parametrized over the ENUMS, so a value added to either is covered
        the day it is added rather than silently rejected by a stale Literal."""
        project = make_project()
        agent = make_agent(project_id=project["id"])
        for value in enum:
            r = client.post(
                f"/api/agents/{agent['id']}/memories",
                json={"body": f"tagging {field}", field: value.value},
            )
            assert r.status_code == 201, (field, value.value, r.text)
            assert r.json()[field] == value.value

    def test_empty_body_is_refused(self, client, human_memory_agent):
        agent, _project = human_memory_agent
        r = client.post(f"/api/agents/{agent['id']}/memories", json={"body": "   "})
        assert r.status_code == 400, r.text


class TestWriteOnCloseGate:
    """DWB-519 participation, stamped here so DWB-589 needs no mode-aware branch."""

    def test_a_raw_write_stamps_last_memory_write_at(
        self, client, db_session, human_memory_agent
    ):
        agent, _project = human_memory_agent
        before = db_session.get(Agent, agent["id"]).last_memory_write_at
        assert before is None, "fixture agent already had a memory write recorded"

        r = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "counts as a write"}
        )
        assert r.status_code == 201, r.text

        db_session.expire_all()
        after = db_session.get(Agent, agent["id"]).last_memory_write_at
        assert after is not None, (
            "agents.last_memory_write_at was not stamped; a human_memory project "
            "would fail the DWB-519 write-on-close gate for an agent who wrote"
        )
