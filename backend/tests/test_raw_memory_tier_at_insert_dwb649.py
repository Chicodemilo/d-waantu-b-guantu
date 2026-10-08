# Path: tests/test_raw_memory_tier_at_insert_dwb649.py
# File: test_raw_memory_tier_at_insert_dwb649.py
# Created: 2026-10-08 (DWB-649)
# Purpose: Guard that a memory is SCOREABLE THE MOMENT IT IS WRITTEN - the tier
#          is derived at insert from the moment-tags, the untagged default stays
#          outside the scar family, a caller still cannot name a tier, and
#          tier_raw_memories still drains the rows written before this change.
# Caller: pytest
# Callees: app.services.raw_memory, app.services.memory_consolidate,
#          app.services.memory_scan, POST /api/agents/{id}/memories,
#          GET /api/agents/{id}/memory/scored
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on responses, on persisted rows, and on the scored read
# Last Modified: 2026-10-08 (DWB-649)

"""DWB-649 acceptance: the tier is assigned at insert.

THE DEFECT THIS LOCKS OUT. `memory_score.score` raises ValueError for `raw`, so
a row written `raw` has no score and no band, so it is excluded from every
candidate list and never reaches an agent. The insert site hardcoded
`MemoryTier.raw` and only `memory_consolidate.tier_raw_memories` moved a row
off it, so a lesson was invisible from the moment it was written until some
other job happened to run.

THE TESTS ARE WRITTEN AS OUTCOMES, NOT AS MECHANISM CHECKS. "append_raw_memory
calls tier_for_raw" is satisfiable while the harm continues - the call could
land on a field that is later overwritten, or the response could carry a tier
the row does not. So the central test here is a SEQUENCE WALK with nothing in
between: POST, then GET /memory/scored, and the row has a score and a band.

TWO ASSERTIONS PER CASE, THE POSITIVE AND THE NEGATIVE. `tier is not None`
passes against the old behaviour. `tier != raw` passes against a hypothetical
that tiers everything `scar`. Both are asserted every time, because a guard that
passes for the dangerous case exactly as it passes for the safe one is this
lane's recurring failure.

THE TAG CROSS-PRODUCT RUNS AS ONE PARAMETRISED TEST rather than a handful of
examples, so the `raw` assertion covers EVERY reachable input shape rather than
the three that happened to get written down. The expectations are transcribed
from spec section 4's rule a SECOND time here, by hand, rather than imported
from `tier_for_raw` - importing the table under test would only prove the code
equals itself.

ONE TEST DELIBERATELY RUNS THE OLD BEHAVIOUR BESIDE THE NEW ONE
(`test_a_raw_row_is_unscoreable_which_is_why_the_insert_must_not_write_one`).
It builds a `raw` row directly and shows it comes back unscoreable from the same
endpoint that scores the inserted one, on one fixture, in one run. That is the
permanent version of "revert the source and check the test goes red": the
discrimination is encoded in the suite instead of living in a transcript.
"""

import pytest

from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.models.project import MemoryMode, Project
from app.services import memory_consolidate, memory_scan, memory_score
from tests.conftest import MEMORY_WRITE_EXTRAS


@pytest.fixture
def memory_agent(client, db_session, make_project, make_agent):
    """An agent on its OWN project, in human_memory mode, with a session open.

    Its own project because the session lookup is per-project and the
    single-active invariant is a per-project UNIQUE index; a shared project
    would let one test's session leak into another's.

    The session is open because DWB-637 refuses a write without one. The MODE is
    flipped because `GET /memory/scored` returns `computed: False` for a stock
    project and three empty lists - which would make every assertion below pass
    against a feature that does nothing. The helper asserts `computed` for the
    same reason; this fixture is what makes that assertion satisfiable.
    """
    project = make_project()
    agent = make_agent(project_id=project["id"])
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    r = client.post(
        "/api/sessions/open",
        json={"project_id": project["id"], "open_method": "slash"},
    )
    assert r.status_code == 201, r.text
    return agent, project, r.json()


def _scored_entry(client, agent_id, memory_id):
    """The one entry for `memory_id` from GET /memory/scored, or None.

    Asserts the envelope first. `computed: False` means the endpoint declined to
    run at all (wrong memory_mode, say), and an empty `entries` list under it
    would make every assertion below pass for the wrong reason.
    """
    r = client.get(f"/api/agents/{agent_id}/memory/scored")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["computed"] is True, (
        f"the scored read did not run at all: {payload.get('reason')!r} - "
        "nothing below would be measuring the tier"
    )
    hits = [e for e in payload["entries"] if e["id"] == memory_id]
    assert len(hits) <= 1, "one memory id returned more than one entry"
    return hits[0] if hits else None


class TestScoreableTheMomentItIsWritten:
    """AC1. POST then GET, with NO other call in between."""

    def test_a_new_memory_is_scored_on_the_very_next_read(
        self, client, memory_agent
    ):
        """The whole ticket in one sequence walk.

        Nothing runs between the write and the read: no consolidation, no hook,
        no session restart. If this passes only because some fixture ran
        consolidation, the assertion on `tiered_raw` in
        TestConsolidationStillDrainsTheBacklog would be the thing that caught it.
        """
        agent, _project, _session = memory_agent

        written = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "the gate reported that it ran, not that it landed"},
        )
        assert written.status_code == 201, written.text
        memory_id = written.json()["id"]

        entry = _scored_entry(client, agent["id"], memory_id)

        assert entry is not None, "the row never appeared in the scored read"
        assert entry["scored"] is True, (
            f"written and immediately unscoreable: reason={entry['reason']!r}"
        )
        assert entry["tier"] != MemoryTier.raw.value
        assert entry["reason"] is None, "a scored entry must carry no refusal reason"
        assert entry["score"] is not None and entry["score"] > 0
        # Named bands, not just "not None": `band()` returns one of four strings
        # and anything else means the score fell outside every documented range.
        assert entry["band"] in {
            memory_score.BAND_FULL_TEXT,
            memory_score.BAND_COMPRESSED,
            memory_score.BAND_DEMOTION_CANDIDATE,
            memory_score.BAND_LAST_CONSOLIDATION,
        }, entry["band"]

    def test_a_raw_row_is_unscoreable_which_is_why_the_insert_must_not_write_one(
        self, client, db_session, memory_agent
    ):
        """The broken variant and the real one, side by side, on one fixture.

        This is the discrimination the ticket rests on, made permanent. A `raw`
        row is inserted DIRECTLY (bypassing the endpoint, which can no longer
        produce one) and read back from the same endpoint as the written row. If
        both came back scored, the test above would be proving nothing about the
        tier; if both came back unscored, the feature would not work. They must
        differ, and they must differ in the stated direction.
        """
        agent, _project, session = memory_agent

        written = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "derived at insert"},
        )
        assert written.status_code == 201, written.text
        derived_id = written.json()["id"]

        stranded = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.raw,
            body="written before DWB-649 and never judged",
            created_session_id=session["id"],
        )
        db_session.add(stranded)
        db_session.commit()

        derived_entry = _scored_entry(client, agent["id"], derived_id)
        stranded_entry = _scored_entry(client, agent["id"], stranded.id)

        assert derived_entry is not None and stranded_entry is not None
        assert derived_entry["scored"] is True
        assert stranded_entry["scored"] is False, (
            "a `raw` row scored - memory_score no longer refuses it, so this "
            "ticket's premise (raw == invisible) has changed and the insert-site "
            "argument needs re-reading"
        )
        # `reason` is where the refusal is named; `band` and `score` are None
        # for an unscored row. Asserted on the field that actually carries it,
        # after an earlier version of this test asserted it on `band` and failed
        # against correct code.
        assert stranded_entry["reason"] == memory_score.UNSCORED_UNTIERED
        assert stranded_entry["band"] is None
        assert stranded_entry["score"] is None


class TestTheTierDerivedAtInsert:
    """AC2 and AC3. The rule, transcribed a second time by hand."""

    # (cost, caught_by, surprised, expected tier) - section 4's rule as prose:
    # any ONE of cost high, surprised true, or caught_by not `me` earns a scar;
    # everything else, INCLUDING every untagged row, is working.
    CASES = [
        (None, None, None, "working"),
        ("none", None, None, "working"),
        ("low", None, None, "working"),
        ("high", None, None, "scar"),
        (None, "me", None, "working"),
        (None, "worker", None, "scar"),
        (None, "human", None, "scar"),
        (None, "ci", None, "scar"),
        (None, None, False, "working"),
        (None, None, True, "scar"),
        ("none", "me", False, "working"),
        ("low", "me", False, "working"),
        ("high", "me", False, "scar"),
        ("none", "me", True, "scar"),
        ("none", "human", False, "scar"),
        ("high", "ci", True, "scar"),
    ]

    @pytest.mark.parametrize("cost,caught_by,surprised,expected", CASES)
    def test_every_tag_shape_lands_on_the_stated_tier(
        self, client, db_session, memory_agent, cost, caught_by, surprised, expected
    ):
        agent, _project, _session = memory_agent
        body = {**MEMORY_WRITE_EXTRAS, "body": f"tags {cost}/{caught_by}/{surprised}"}
        if cost is not None:
            body["cost"] = cost
        if caught_by is not None:
            body["caught_by"] = caught_by
        if surprised is not None:
            body["surprised"] = surprised

        r = client.post(f"/api/agents/{agent['id']}/memories", json=body)
        assert r.status_code == 201, r.text
        response_tier = r.json()["tier"]

        row = db_session.get(AgentMemory, r.json()["id"])
        assert row is not None, "nothing persisted; the tier claims are vacuous"

        assert response_tier == expected
        assert row.tier.value == expected, "the response disagrees with the row"
        # Said twice on purpose: the positive AND the one value that means the
        # lesson is invisible. `== expected` alone would pass a mutation that
        # also changed this table.
        assert row.tier != MemoryTier.raw

    def test_no_reachable_tag_shape_produces_raw_or_core(
        self, client, memory_agent
    ):
        """The cross-product as an absence claim, with its positive set asserted
        in the same breath so it cannot pass by scanning nothing."""
        agent, _project, _session = memory_agent

        seen = set()
        for cost, caught_by, surprised, _expected in self.CASES:
            body = {**MEMORY_WRITE_EXTRAS, "body": f"shape {cost}/{caught_by}/{surprised}"}
            if cost is not None:
                body["cost"] = cost
            if caught_by is not None:
                body["caught_by"] = caught_by
            if surprised is not None:
                body["surprised"] = surprised
            r = client.post(f"/api/agents/{agent['id']}/memories", json=body)
            assert r.status_code == 201, r.text
            seen.add(r.json()["tier"])

        assert seen == {"scar", "working"}, (
            f"the endpoint produced tiers outside the derived pair: {seen}"
        )

    def test_the_untagged_default_cannot_reach_core(self, client, memory_agent):
        """AC2 as the STRUCTURAL guard it is, not as a preference.

        `working` sits outside `memory_scan.SCAR_FAMILY`, so `consult_scars`
        never fires an untagged row, so `fired_count` never reaches the
        threshold, so `maybe_promote_scar` can never carry a scratch note to
        CORE - the tier that never decays. The containment check is asserted
        here rather than trusted, because the day `working` joins SCAR_FAMILY
        the default silently stops being a guard.
        """
        agent, _project, _session = memory_agent

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "a scratch note nobody judged"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["tier"] == MemoryTier.working.value

        assert MemoryTier.working not in memory_scan.SCAR_FAMILY, (
            "the untagged default is now scar-family: an unjudged note can fire "
            "its way to CORE, which is the rubber-stamp section 4 forbids"
        )
        assert MemoryTier.scar in memory_scan.SCAR_FAMILY, (
            "SCAR_FAMILY no longer contains scar, so the check above is "
            "answering about an empty set"
        )

    def test_the_insert_agrees_with_consolidation_on_the_same_row(
        self, client, db_session, memory_agent
    ):
        """The claim the ticket rests on: deferring the call cannot change its
        answer, because its three inputs are written once and never reassigned.

        Asserted by running `tier_for_raw` over the PERSISTED row - the state
        consolidation would have seen a session later - and requiring it to
        match what the insert already stored. Two implementations of the rule
        would drift here; one implementation called twice cannot.
        """
        agent, _project, _session = memory_agent

        for cost, caught_by, surprised, _expected in self.CASES:
            body = {**MEMORY_WRITE_EXTRAS, "body": f"agreement {cost}/{caught_by}/{surprised}"}
            if cost is not None:
                body["cost"] = cost
            if caught_by is not None:
                body["caught_by"] = caught_by
            if surprised is not None:
                body["surprised"] = surprised
            r = client.post(f"/api/agents/{agent['id']}/memories", json=body)
            assert r.status_code == 201, r.text

            row = db_session.get(AgentMemory, r.json()["id"])
            assert row is not None
            assert row.tier == memory_consolidate.tier_for_raw(row), (
                "the stored tier is not what consolidation would derive from "
                "the stored tags"
            )

    def test_the_tags_are_still_persisted_as_enums_not_consumed_by_the_tiering(
        self, client, db_session, memory_agent
    ):
        """The moment-tags survive the write. Section 2 gates the SCAN on
        `cost`, so a tiering step that read the tags and dropped them would pass
        every tier assertion above and break the SCAN."""
        agent, _project, _session = memory_agent

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, 
                "body": "the migration was already at head",
                "cost": "high",
                "caught_by": "human",
                "surprised": True,
            },
        )
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row is not None
        assert row.cost == MemoryCost.high
        assert row.caught_by == MemoryCaughtBy.human
        assert row.surprised is True


class TestTheCallerStillCannotNameATier:
    """AC4. DWB-649 moved WHEN the server derives the tier, not WHO."""

    @pytest.mark.parametrize("tier", ["raw", "working", "scar"])
    def test_a_supplied_tier_is_refused_with_tier_not_settable(
        self, client, db_session, memory_agent, tier
    ):
        agent, _project, _session = memory_agent
        before = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent["id"])
            .count()
        )

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "I will pick my own tier", "tier": tier},
        )
        assert r.status_code == 400, r.text
        # The status alone passes for a Pydantic error or an empty body, which
        # read identically to the caller and send them to the wrong place.
        detail = r.json()["detail"]
        assert "cannot be set" in detail
        assert tier in detail

        after = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent["id"])
            .count()
        )
        assert after == before, "a refused write persisted a row anyway"

    def test_tier_core_is_still_refused_by_the_rule_that_governs_it(
        self, client, memory_agent
    ):
        """`core` keeps its own refusal and its own sentence: section 7 hard
        rule 5, not section 4. A refusal that cites the wrong rule teaches the
        caller the wrong thing."""
        agent, _project, _session = memory_agent
        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "straight to core", "tier": "core"},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "hard rule 5" in detail
        assert "core" in detail


class TestConsolidationStillDrainsTheBacklog:
    """AC5. `tier_raw_memories` is left in place and working - it still carries
    every row written before DWB-649, and the backfill ticket uses it."""

    def test_tier_raw_memories_still_tiers_a_pre_existing_raw_row(
        self, db_session, client, memory_agent
    ):
        agent, _project, session = memory_agent

        stranded = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.raw,
            body="written before the insert derived anything",
            cost=MemoryCost.high,
            created_session_id=session["id"],
        )
        db_session.add(stranded)
        db_session.flush()
        assert stranded.tier == MemoryTier.raw, "the fixture is not raw to begin with"

        moved = memory_consolidate.tier_raw_memories(
            db_session, agent_id=agent["id"]
        )

        assert (stranded.id, "scar") in moved, f"the raw row was not tiered: {moved}"
        db_session.refresh(stranded)
        assert stranded.tier == MemoryTier.scar

    def test_a_pass_over_rows_written_through_the_endpoint_finds_nothing(
        self, db_session, client, memory_agent
    ):
        """The new steady state, asserted positively rather than as "it was
        quiet". The endpoint-written row is confirmed to EXIST and to be tiered
        before the empty result is claimed to mean anything - an empty `moved`
        over an empty candidate set would otherwise pass against a write that
        failed entirely.
        """
        agent, _project, _session = memory_agent

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={**MEMORY_WRITE_EXTRAS, "body": "tiered on the way in", "surprised": True},
        )
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row is not None and row.tier == MemoryTier.scar

        moved = memory_consolidate.tier_raw_memories(
            db_session, agent_id=agent["id"]
        )
        assert moved == [], (
            f"consolidation found raw rows for an agent whose only write went "
            f"through the endpoint: {moved}"
        )
