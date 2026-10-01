# Path: tests/test_transition_readback_dwb626.py
# File: test_transition_readback_dwb626.py
# Created: 2026-10-01 (DWB-626)
# Purpose: A deciding agent can read back the entries it decided, with the tier
#          it assigned, DURING adoption - and the read-back cannot become the
#          listing the decide phase forbids.
# Caller: pytest
# Callees: GET /api/memory-transitions/{id}
# Data In: tmp_path repo, factory project + agent, decided and pending rows
# Data Out: assertions on what the read-back returns and what it cannot return
# Last Modified: 2026-10-01 (DWB-626)

"""Separate FILE from the withdrawal tests, and the separation is the point.

Acceptance 3 asks for a demonstration that the absence was real: that a decided
entry could not be read back. That demonstration is this file run against the
PRE-FIX tree, where the endpoint does not exist and these go red.

They can only do that if nothing here imports a module the fix introduces. The
withdrawal tests import `memory_removal` and `memory_withdraw`, which do not
exist at HEAD, so sharing a file would turn the demonstration into a COLLECTION
ERROR - and an error is not a red. It proves the file could not be loaded, not
that the behaviour was missing, which is a different claim and a weaker one.
"""

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)


@pytest.fixture
def decided(db_session, client, tmp_path):
    """One DECIDED transition and one PENDING one, for the same agent."""
    project = client.post("/api/projects", json={
        "prefix": "RDB", "name": "Readback", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": "Reader",
        "role": "backend-worker", "api_key": "dwb626-rdb",
    }).json()

    memory = AgentMemory(
        agent_id=agent["id"], tier=MemoryTier.scar, body="a decided lesson"
    )
    db_session.add(memory)
    db_session.flush()

    run = MemoryTransitionRun(
        project_id=project["id"], direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
    )
    db_session.add(run)
    db_session.flush()

    written = MemoryTransition(
        project_id=project["id"], agent_id=agent["id"], run_id=run.id,
        state=TransitionState.written, source_excerpt="- a decided lesson\n",
        decided_tier=MemoryTier.scar, decided_by="Reader",
        target_memory_id=memory.id,
    )
    pending = MemoryTransition(
        project_id=project["id"], agent_id=agent["id"], run_id=run.id,
        state=TransitionState.pending, source_excerpt="- an undecided candidate\n",
    )
    db_session.add_all([written, pending])
    db_session.flush()
    return project, agent, written, pending


class TestADecidedEntryCanBeReadBack:
    """Acceptance 1, narrowed by ruling: ONE entry by id, never a listing.

    The project is still ADOPTING here, which is the case that had no read-back
    at all - `/memory/scored` returns computed:false with reason
    project_not_in_human_memory_mode until after cutover, so before this an agent
    could only report its own work from its call log, a weaker claim that is
    indistinguishable from outside from a verified one.
    """

    def test_a_decided_entry_can_be_fetched_by_id(self, client, decided):
        _project, _agent, written, _pending = decided
        r = client.get(f"/api/memory-transitions/{written.id}")
        assert r.status_code == 200, (
            f"no read-back of a decided entry exists (got {r.status_code})"
        )
        assert r.json()["id"] == written.id

    def test_it_carries_the_tier_that_was_assigned(self, client, decided):
        _project, _agent, written, _pending = decided
        r = client.get(f"/api/memory-transitions/{written.id}")
        assert r.status_code == 200
        assert r.json()["decided_tier"] == "scar", (
            "the read-back must carry the tier, or it cannot be used to "
            "recognise a mis-tier, which is the whole reason it exists"
        )


class TestItCannotBecomeTheQueue:
    """DWB-594's guard won, and these pin WHY the narrowing holds.

    An agent shown the queue reasons about the queue. A lookup by id cannot hand
    over a set, and refusing a pending row keeps the choice of what an agent
    sees with `next_entry`, which is the only thing allowed to make it.
    """

    def test_there_is_no_listing_route(self, client, decided):
        _project, agent, _written, _pending = decided
        r = client.get(f"/api/memory-transitions/decided?agent_id={agent['id']}")
        assert r.status_code != 200, (
            "a listing of decided entries is reachable; DWB-594's one-entry "
            "constraint is defeated by it"
        )

    def test_a_pending_row_is_refused_rather_than_served(self, client, decided):
        _project, _agent, _written, pending = decided
        r = client.get(f"/api/memory-transitions/{pending.id}")
        assert r.status_code == 409
        assert "not decided" in r.json()["detail"]

    def test_a_missing_id_is_404_not_an_empty_answer(self, client, decided):
        r = client.get("/api/memory-transitions/99999999")
        assert r.status_code == 404
