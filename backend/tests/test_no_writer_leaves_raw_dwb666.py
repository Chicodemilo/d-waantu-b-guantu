# Path: tests/test_no_writer_leaves_raw_dwb666.py
# File: test_no_writer_leaves_raw_dwb666.py
# Created: 2026-10-09 (DWB-666)
# Purpose: Keep the DWB-666 defect closed. No production writer of
#          agent_memories may leave a row in `raw`, because `raw` is the state
#          that waits for a session boundary a subagent cannot trigger.
# Caller: pytest
# Callees: app.services.memory_consolidate.tier_for_raw, app.services.memory_decide
#          (DECIDABLE_TIERS), POST /api/agents/{id}/memories
# Data In: the enum product of the three moment-tags; the live write path
# Data Out: assertions on every reachable tier
# Last Modified: 2026-10-09 (DWB-666)

"""DWB-666: the defect was already closed, and nothing was holding it closed.

THE TICKET DESCRIBES A REAL FAILURE THAT NO LONGER HAPPENS. `consolidate_agent`
tiers raw rows and runs only at a session boundary, and a subagent cannot
trigger one - so a subagent's lesson used to sit `raw`, unscored, in no
candidate list, invisible to every consumer including its own author, until a
human opened a session. The ticket cites fourteen such rows on a live project.

DWB-649 CLOSED IT BY TIERING AT INSERT, before this ticket was written.
Measured at the time this test was added: ONE `raw` row in the entire store,
created 2026-10-07 by a probe on an agent with no project, and nothing from any
day since. Verified live on a throwaway project: an agent with no SessionStart
hook row at all writes a lesson mid-session, the write RESPONSE carries
`tier: working`, and `GET /memory/scored` serves it immediately at score 10.
The write response is the proof - no later consolidation can reach backwards
into it.

SO WHAT IS THIS TEST FOR. The fix was a side effect of another ticket and
nothing asserts it. `raw_memory` could stop calling `tier_for_raw` tomorrow,
`memory_decide` could add `raw` to its decidable set, a fourth writer could
arrive, and every existing test would still pass while subagent lessons went
quietly invisible again for up to a day. That is the shape this codebase keeps
producing: a mechanism that is correct today with nothing making it stay
correct, and a failure whose only symptom is a lesson nobody can observe not
being recalled.

THE OTHER FOUR MOVEMENTS DO NOT NEED A MID-SESSION TRIGGER, AND THAT IS A
PROOF RATHER THAN A JUDGEMENT. `consolidate_agent` also promotes, concludes and
evicts. Every one of those is driven by `memory_score`, which counts CLOSED
sessions only - "an open session is the one currently happening; it becomes
experience when it ends". So within one open session no row's score can change,
and a mid-session pass over them is a guaranteed no-op. The single exception is
promotion to CORE, which keys on `fired_count` and CAN move mid-session; that
is deliberately left alone here, because DWB-665 establishes CORE has no
demotion path and DWB-668 is reconsidering whether CORE is searchable at all.
"""

import itertools

import pytest

from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.models.project import MemoryMode, Project
from app.services import memory_decide
from app.services.memory_consolidate import tier_for_raw


class TestNoReachableTagShapeProducesRaw:
    """`raw_memory`'s writer, over the whole enum product rather than a sample."""

    @pytest.mark.parametrize(
        "cost,caught_by,surprised",
        list(
            itertools.product(
                [None] + list(MemoryCost),
                [None] + list(MemoryCaughtBy),
                [None, True, False],
            )
        ),
    )
    def test_every_tag_combination_lands_outside_raw(self, cost, caught_by, surprised):
        row = AgentMemory(
            agent_id=1, body="x", cost=cost, caught_by=caught_by, surprised=surprised
        )
        tier = tier_for_raw(row)
        assert tier is not MemoryTier.raw, (
            f"cost={cost} caught_by={caught_by} surprised={surprised} produced "
            "`raw`. A raw row waits for a session boundary, and a subagent "
            "cannot trigger one, so it would be invisible to every consumer "
            "until a human opened a session."
        )
        assert tier is not MemoryTier.core


class TestTheAdoptWriterCannotChooseRawEither:
    def test_raw_is_not_a_decidable_tier(self):
        assert MemoryTier.raw not in memory_decide.DECIDABLE_TIERS
        assert MemoryTier.core not in memory_decide.DECIDABLE_TIERS

    def test_decidable_tiers_is_not_empty(self):
        """A guard over an empty set passes for the wrong reason - the same
        vacuous shape this lane keeps finding."""
        assert memory_decide.DECIDABLE_TIERS


class TestTheLiveWritePathNeverStoresRaw:
    """AC3, through the endpoint rather than the service, on an agent that has
    never produced a SessionStart row - which is the whole of what makes a
    subagent different."""

    def test_a_write_is_tiered_and_scoreable_in_the_same_session(
        self, client, db_session, make_project, make_agent
    ):
        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()
        agent = make_agent(project_id=project["id"])
        opened = client.post(
            "/api/sessions/open",
            json={"project_id": project["id"], "open_method": "slash"},
        )
        assert opened.status_code in (200, 201), opened.text

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={
                "body": "a subagent never produces a SessionStart row",
                "condensed": "do not hang visible state on a boundary a subagent cannot trigger",
                "keywords": ["subagent", "session start"],
                "situation": "a subagent wrote a lesson mid-session and no session start has fired",
            },
        )
        assert r.status_code == 201, r.text
        # The WRITE RESPONSE is the evidence. A consolidation running later
        # cannot reach backwards into it, so this distinguishes "tiered at
        # insert" from "tiered by something that happened to run afterwards".
        assert r.json()["tier"] != MemoryTier.raw.value, r.text

        scored = client.get(f"/api/agents/{agent['id']}/memory/scored")
        assert scored.status_code == 200, scored.text
        payload = scored.json()
        entries = payload.get("entries", payload if isinstance(payload, list) else [])
        assert any(e.get("id") == r.json()["id"] for e in entries), (
            "the row was written and tiered but is not served by "
            "GET /memory/scored in the same session, which is the DWB-666 "
            f"failure one step later. Served: {entries}"
        )
