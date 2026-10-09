# Path: tests/test_core_is_consulted_dwb668.py
# File: test_core_is_consulted_dwb668.py
# Created: 2026-10-09 (DWB-668)
# Purpose: Guard that CORE is in the search population, that firing a CORE row
#          records what happened without re-promoting it, and that the search
#          population is its OWN constant rather than a widened SCAR_FAMILY.
#          Also pins DWB-665's behaviour change at the promotion site: promotion
#          no longer destroys `context_key`.
# Caller: pytest
# Callees: app.services.memory_consult (CONSULTED_TIERS, consult_scars,
#          match_scars), app.services.memory_promote, app.services.memory_scan,
#          app.services.memory_consolidate
# Data In: factory agents/projects, agent_memories rows at core and scar
# Data Out: Assertions on the searched population, the stored counters, the
#           tier after a consolidation pass, and the promotion site's writes
# Last Modified: 2026-10-09 (DWB-668)

"""The tier that never decays could never be recalled.

`consult_scars` searched `tier.in_(SCAR_FAMILY)`, which is `(scar,)` since
DWB-611. So promotion to CORE - the reward for a lesson that proved itself
three times - removed that lesson from the only path that could ever fire it
again. Measured on 2026-10-09: 126 CORE rows across the project, 86 on one
agent, every one unreachable. Combined with DWB-665 (no way off CORE), a
promoted row could not decay, could not be recalled, could not be corrected by
use and could not be demoted.

Archie's ruling: "a memory tier whose contents can never be recalled is not a
memory tier."

WHAT THIS FILE REFUSES TO TEST BY WIDENING SCAR_FAMILY. The one-line fix was to
add `core` to that tuple. `SCAR_FAMILY` answers "what is a scar" and DWB-611
collapsed two scar tiers into one precisely to stop a second tier list
drifting. The search population is a different question that happened to share
an answer. `TestTheSearchPopulationIsItsOwnConcept` is the guard on that
distinction, because the next person to want a tier findable will reach for the
same one-liner.
"""

import ast
import inspect
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_consolidate, memory_promote, memory_scan
from app.services import memory_consult as svc

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

KEYWORDS = ["sprint close", "backlog ticket"]
SITUATION = "can I run a sprint close while a backlog ticket is still open"


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


def _memory(db, *, agent_id, tier, keywords=None, **kw):
    row = AgentMemory(
        agent_id=agent_id,
        tier=tier,
        body=kw.pop("body", "a lesson that proved itself"),
        keywords=list(keywords) if keywords is not None else None,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _reread(db, memory_id):
    db.expire_all()
    return db.get(AgentMemory, memory_id)


class TestCoreIsSearched:
    """The defect, directly."""

    def test_a_core_row_is_recalled_by_a_situation(self, db_session, agent):
        core = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.core, keywords=KEYWORDS
        )

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 1
        assert [m.id for m in result["entries"]] == [core.id]

    def test_the_same_row_was_invisible_under_the_old_population(
        self, db_session, agent
    ):
        """THE POSITIVE CONTROL. Without it the test above is satisfied by any
        search that returns rows, and would have passed before this ticket if
        the fixture had happened to be a scar.

        This runs the OLD population - `SCAR_FAMILY`, imported from the module
        that still owns it - against the SAME row and asserts it finds nothing,
        which is what makes the recall above attributable to the change.
        """
        core = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.core, keywords=KEYWORDS
        )
        assert core.tier not in memory_scan.SCAR_FAMILY

        # ... and the old population is not simply broken in this fixture: a
        # scar with the same keywords IS found by it. An absence assertion that
        # cannot see what is there is not a measurement.
        scar = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.scar, keywords=KEYWORDS
        )
        found = svc.match_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )
        assert {m.id for m in found["entries"]} == {core.id, scar.id}
        assert [
            m.id for m in found["entries"] if m.tier in memory_scan.SCAR_FAMILY
        ] == [scar.id]

    def test_working_is_still_outside_the_search_population(self, db_session, agent):
        """The structural safety property DWB-632 rests on: `working` is the
        default tier for an UNJUDGED row, and it sits outside the searched set
        so an unjudged scratch note can never accumulate firings. Widening to
        CORE must not have widened to everything."""
        working = _memory(
            db_session,
            agent_id=agent["id"],
            tier=MemoryTier.working,
            keywords=KEYWORDS,
        )

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 0
        assert _reread(db_session, working.id).fired_count == 0

    def test_raw_is_still_outside_the_search_population(self, db_session, agent):
        raw = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.raw, keywords=KEYWORDS
        )
        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )
        assert result["count"] == 0
        assert _reread(db_session, raw.id).fired_count == 0


class TestFiringACoreRowRecordsItWithoutPromotingIt:
    """`fired_count` on a non-decaying row: what it means, and what it must not
    trigger."""

    def test_a_core_row_increments_fired_count_and_moves_the_origin(
        self, db_session, agent
    ):
        core = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.core, keywords=KEYWORDS
        )
        assert core.fired_count == 0

        svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)

        row = _reread(db_session, core.id)
        assert row.fired_count == 1
        assert row.tier == MemoryTier.core

    def test_firing_a_core_row_cannot_re_promote_it(self, db_session, agent):
        """The counter has a writer on CORE now, so the question is whether
        anything downstream acts on it. `maybe_promote_scar` is the only reader
        of `fired_count` in the app and it refuses a non-scar tier outright."""
        core = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.core, keywords=KEYWORDS
        )
        for _ in range(memory_promote.SCAR_FIRED_THRESHOLD + 1):
            svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)
        row = _reread(db_session, core.id)
        assert row.fired_count > memory_promote.SCAR_FIRED_THRESHOLD

        with pytest.raises(memory_scan.ScanError) as exc:
            memory_promote.maybe_promote_scar(db_session, row)
        assert exc.value.code == "not_a_scar"

    def test_a_consolidation_pass_does_not_hand_core_to_the_promoter(
        self, db_session, agent
    ):
        """The other half of the same question, one level up: the refusal above
        only protects us if nothing CALLS it with a CORE row. The consolidation
        pass is the only caller, and it must not raise either."""
        core = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.core, keywords=KEYWORDS
        )
        for _ in range(memory_promote.SCAR_FIRED_THRESHOLD + 1):
            svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)

        result = memory_consolidate.consolidate_agent(
            db_session, agent_id=agent["id"]
        )

        assert core.id not in [mid for mid, _ in result.promoted_scars]
        assert _reread(db_session, core.id).tier == MemoryTier.core

    def test_a_scar_still_promotes_at_the_threshold(self, db_session, agent):
        """The paired state. Without it the test above is satisfied by a
        consolidation pass that promotes nothing at all."""
        scar = _memory(
            db_session, agent_id=agent["id"], tier=MemoryTier.scar, keywords=KEYWORDS
        )
        for _ in range(memory_promote.SCAR_FIRED_THRESHOLD):
            svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)

        result = memory_consolidate.consolidate_agent(
            db_session, agent_id=agent["id"]
        )

        assert (scar.id, "fired_three_times") in result.promoted_scars
        assert _reread(db_session, scar.id).tier == MemoryTier.core


class TestPromotionNoLongerDestroysContextKey:
    """DWB-665's behaviour change, pinned at the promotion site.

    Clearing `context_key` was defensible while CORE was a one-way door -
    nothing came back, so nothing could ever need the value. With a demote path
    it is destruction of something only this row had, and demotion cannot
    restore it.
    """

    def test_a_retier_keeps_the_context_key(self, db_session, agent):
        scar = _memory(
            db_session,
            agent_id=agent["id"],
            tier=MemoryTier.scar,
            keywords=KEYWORDS,
            context_key="DWB-668",
        )

        memory_promote.promote_to_core(
            db_session, agent_id=agent["id"], body=scar.body, memory=scar
        )

        row = _reread(db_session, scar.id)
        assert row.tier == MemoryTier.core
        assert row.context_key == "DWB-668", (
            "promotion destroyed the context_key; demotion cannot restore it"
        )

    def test_no_write_site_in_memory_promote_clears_context_key(self):
        """Structural, because the behavioural test above passes for code that
        clears the value somewhere else in the same module."""
        tree = ast.parse(inspect.getsource(memory_promote))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "context_key"
                        and isinstance(node.value, ast.Constant)
                        and node.value.value is None
                    ):
                        raise AssertionError(
                            f"memory_promote.py clears context_key at line "
                            f"{node.lineno}; DWB-665 made promotion non-lossy"
                        )


class TestTheSearchPopulationIsItsOwnConcept:
    """The guard on the distinction, because the one-line fix is the tempting
    one and it is the one DWB-611 exists to prevent."""

    def test_scar_family_still_means_only_scar(self):
        assert memory_scan.SCAR_FAMILY == (MemoryTier.scar,), (
            "SCAR_FAMILY answers 'what is a scar'. Widening it to make CORE "
            "findable is the drift DWB-611 collapsed two tiers to prevent."
        )

    def test_the_consulted_population_is_named_separately(self):
        assert svc.CONSULTED_TIERS == (MemoryTier.core, MemoryTier.scar)
        assert svc.CONSULTED_TIERS is not memory_scan.SCAR_FAMILY

    def test_the_consultation_query_uses_the_consulted_population(self):
        """Pins which constant the query actually reads. The two tuples could
        agree by accident on any given day; this asserts the call site."""
        source = inspect.getsource(svc.match_scars)
        assert "CONSULTED_TIERS" in source
        assert "SCAR_FAMILY" not in source

    def test_every_tier_is_accounted_for_in_one_of_the_two(self):
        """A tier added later must declare its side rather than silently
        inheriting whichever list the author happened to read first."""
        decided = set(svc.CONSULTED_TIERS) | {MemoryTier.working, MemoryTier.raw}
        assert decided == set(MemoryTier), (
            f"tier(s) {set(MemoryTier) - decided} are in neither the consulted "
            "population nor the deliberately-excluded set; decide which."
        )
