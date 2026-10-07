# Path: tests/test_raw_memory_write_dwb586.py
# File: test_raw_memory_write_dwb586.py
# Created: 2026-09-29 (DWB-586)
# Purpose: Guard the raw memory write - that it writes `raw` and never NULL,
#          that a write with no open DWB session is REFUSED rather than stored
#          without a clock origin, that no request shape sets a tier, and that
#          it stamps the write-on-close gate.
# Caller: pytest
# Callees: app.services.raw_memory, POST /api/agents/{id}/memories
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on responses and on the persisted row
# Last Modified: 2026-10-07 (DWB-637: AC1's "accepted without a session"
#                case is now the refusal case - see the docstring below)

"""DWB-586 acceptance, spec section 4 and section 7 hard rule 5.

The two acceptance criteria drive the two big classes here.

AC1 WAS about AMBIGUITY: a write with no open session was ACCEPTED, and the
caller had to be able to tell that from a write that landed in one, so the tests
asserted the two responses DIFFER rather than that each was individually
plausible.

DWB-637 REMOVED THE AMBIGUOUS CASE RATHER THAN DISAMBIGUATING IT. A row written
with a null `created_session_id` has no clock origin, so `memory_score` cannot
score it, so it is excluded from every candidate list and never reaches an
agent: it read as stored and behaved as lost, three times, for 612 rows. The
write is now refused with 400.

The SHAPE of AC1 survives and is what the tests below still assert, because the
shape was the valuable part: hold both cases at once and assert they ANSWER
DIFFERENTLY. A guard that passes because the dangerous case answers the same way
as the safe one is the defect this whole lane keeps producing, and "every write
is refused" passes every single-response assertion in isolation exactly as
"every write says none_open" did.

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
def human_memory_agent(client, make_project, make_agent):
    """An agent on its own project, WITH a DWB session open (DWB-637).

    Its own project matters: the session lookup is per-project and the
    single-active invariant is a per-project UNIQUE index, so a shared project
    would let one test's open session leak into another's "no session" case.

    The session is open because a write without one is now refused, and every
    test in this file that is about something ELSE - tiers, moment-tags, the
    write-on-close stamp - needs the write to succeed to assert anything at all.
    Leaving it closed would make those tests pass or fail on the session rule
    rather than on their own subject, which is the "400 for the wrong reason"
    trap this module's docstring already warns about, one level up.
    """
    project = make_project()
    agent = make_agent(project_id=project["id"])
    _open_session(client, project["id"])
    return agent, project


@pytest.fixture
def agent_with_no_session(make_project, make_agent):
    """An agent on its own project with NO session open: the refusal case."""
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
    """AC1 as DWB-637 leaves it: one state lands, the other is refused, and the
    two outcomes are distinguishable."""

    def test_write_during_open_session_carries_that_session_id(
        self, client, agent_with_no_session
    ):
        # Opens the session itself rather than taking the fixture's, so the id
        # asserted below is one this test can see being created.
        agent, project = agent_with_no_session
        session = _open_session(client, project["id"])

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "the gate read the heading, not the column"},
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["created_session_id"] == session["id"]
        assert row["session_state"] == raw_memory.SESSION_OPEN

    def test_write_with_no_open_session_is_refused_and_names_the_fix(
        self, client, agent_with_no_session
    ):
        """DWB-637 criterion 1. The status AND the reason AND the fix.

        Asserting only the 400 would pass against a refusal for any other
        reason - an empty body, a bad tier, a Pydantic error - which reads
        identically to the caller and sends them looking in the wrong place.
        """
        agent, _project = agent_with_no_session

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "encoded with nobody watching"},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "no open DWB session" in detail  # the reason
        assert "cannot be scored" in detail  # why that matters
        assert "/dwb-open" in detail and "/api/sessions/open" in detail  # the fix
        # Role-neutral: opening a session is TL-only, so the line is phrased as
        # a condition rather than an instruction to whoever happens to be here.
        assert "is not yours to do" in detail
        assert "Open a session first" not in detail
        assert "Nothing was written" in detail  # what became of the lesson

    def test_a_refused_write_persists_no_row(
        self, client, db_session, agent_with_no_session
    ):
        """The refusal has to leave the table untouched, not write-then-complain.

        Checked against a SELECT rather than inferred from the status code: the
        whole bug class here is a row that exists and cannot be reached, and a
        400 returned after a flush would reproduce it exactly.
        """
        agent, _project = agent_with_no_session
        client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": "must not land"}
        )
        rows = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent["id"])
            .all()
        )
        assert rows == []

    def test_the_refused_write_succeeds_unchanged_once_a_session_opens(
        self, client, agent_with_no_session
    ):
        """The refusal's own claim, tested rather than trusted.

        The message tells the caller to send the request again unchanged. If
        that is false the refusal is worse than useless, because it costs the
        lesson AND misdirects the retry. Same bytes, both times.
        """
        agent, project = agent_with_no_session
        payload = {"body": "the same lesson, byte for byte", "cost": "low"}

        refused = client.post(f"/api/agents/{agent['id']}/memories", json=payload)
        assert refused.status_code == 400, refused.text

        session = _open_session(client, project["id"])
        accepted = client.post(f"/api/agents/{agent['id']}/memories", json=payload)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["created_session_id"] == session["id"]

    def test_the_two_cases_answer_differently(
        self, client, make_project, make_agent
    ):
        """The point of AC1, kept through DWB-637 and asserted directly.

        The tests above each see ONE of the two cases, so each passes against a
        build that refuses every write, and each passes against a build that
        accepts every write. This one holds both at once and asserts they
        differ. That is the generating question for any guard: what does the
        dangerous case answer here, and does the safe case answer differently?

        Two projects because the single-active session invariant is a
        per-project UNIQUE index - one project cannot be in both states.
        """
        closed_project = make_project()
        closed_agent = make_agent(project_id=closed_project["id"])
        open_project = make_project()
        open_agent = make_agent(project_id=open_project["id"])
        session = _open_session(client, open_project["id"])

        without = client.post(
            f"/api/agents/{closed_agent['id']}/memories", json={"body": "no session"}
        )
        within = client.post(
            f"/api/agents/{open_agent['id']}/memories", json={"body": "in session"}
        )

        assert without.status_code != within.status_code
        assert (without.status_code, within.status_code) == (400, 201)
        # The accepted one carries a real origin, not merely a non-null field.
        assert within.json()["created_session_id"] == session["id"]
        assert within.json()["session_state"] == raw_memory.SESSION_OPEN

    def test_there_is_no_named_success_state_for_a_missing_session(self):
        """DWB-637 criterion 4, asserted on the module rather than on a response.

        `SESSION_NONE_OPEN` named a SUCCESSFUL outcome in which the written row
        had no clock origin. A name for a bad state sitting in the success path
        reads as a supported mode, and the next writer reaches for it. It is
        removed, not re-documented, and this fails if it comes back.
        """
        assert not hasattr(raw_memory, "SESSION_NONE_OPEN")
        assert raw_memory.SESSION_OPEN == "open"


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
        # A session, so a 400 here can only be about the tier. Without one every
        # row would pass for the session reason and this test would certify
        # nothing about tiers at all (DWB-637).
        _open_session(client, project["id"])
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={"body": "trying to tier at write time", "tier": tier},
        )
        assert r.status_code == 400, f"tier {tier!r} was accepted: {r.text}"
        assert "tier" in r.json()["detail"], (
            f"tier {tier!r} was refused for some other reason: {r.text}"
        )

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
        _open_session(client, project["id"])
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
