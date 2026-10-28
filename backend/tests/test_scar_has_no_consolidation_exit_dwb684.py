# Path: tests/test_scar_has_no_consolidation_exit_dwb684.py
# File: test_scar_has_no_consolidation_exit_dwb684.py
# Created: 2026-10-28 (DWB-684)
# Purpose: Guard the fact the not_core refusal now asserts - that no scar can
#          ever be nominated by a candidate list - and guard the refusal
#          wording that used to assert the opposite.
# Caller: pytest
# Callees: app.services.memory_score (_CURVE, band), POST .../demote,
#          POST .../withdraw
# Data In: the scoring curve; test DB rows via the factory fixtures
# Data Out: Assertions on the band arithmetic, on the refusal text, and on the
#           one exit that does reach a scar
# Last Modified: 2026-10-28 (DWB-684)

"""DWB-684.

The `not_core` refusal used to close with "every other tier already moves
under consolidation". It was false for the scar tier, and it was the sentence
that stopped anyone looking: a refusal stating a property of the system reads
as something somebody checked.

WHY THE ARITHMETIC IS UNDER TEST AND NOT JUST THE WORDING. The replacement
sentence makes a claim about the scoring curve, and a claim in a string is
exactly as durable as nobody editing the curve. Lower the scar floor by one
and the refusal silently starts lying again in the other direction, with every
test still green. So the property itself is asserted here, next to the words
that depend on it, and anyone moving the curve has to come and read them.

This is the same failure the ticket exists to document, one level up: the
consolidation lane reported success on twelve consecutive passes while being
structurally incapable of acting, because nothing anywhere asserted that it
COULD act. A property that is true and unguarded looks identical to one that
is enforced, right until it quietly stops being true.
"""

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_score

CANDIDATE_BANDS = {
    memory_score.BAND_DEMOTION_CANDIDATE,
    memory_score.BAND_LAST_CONSOLIDATION,
}


@pytest.fixture
def owner(make_project, make_agent):
    project = make_project(memory_mode="human_memory")
    agent = make_agent(project_id=project["id"])
    return {"project_id": project["id"], "agent_id": agent["id"]}


@pytest.fixture
def scar_row(db_session, owner):
    row = AgentMemory(
        agent_id=owner["agent_id"],
        tier=MemoryTier.scar,
        body="a scar that has nowhere to go",
        condensed="a scar that has nowhere to go",
        keywords=["sprint close", "backlog ticket"],
    )
    db_session.add(row)
    db_session.flush()
    return row


class TestNoScarCanEverBeNominated:
    """The claim the refusal now makes, asserted against the curve itself."""

    def test_every_score_a_scar_can_hold_is_outside_the_candidate_bands(self):
        curve = memory_score._CURVE[MemoryTier.scar]
        for value in curve:
            assert memory_score.band(value) not in CANDIDATE_BANDS, (
                f"a scar scoring {value} now lands in "
                f"{memory_score.band(value)!r}. The scar tier has become "
                "nominable, which is a change to what every human_memory agent "
                "is served at spawn. Re-read the not_core refusal in "
                "memory_demote.py and the module docstring in "
                "memory_withdraw.py - both assert this cannot happen."
            )

    def test_the_scar_floor_sits_above_the_demotion_band(self):
        """Stated as the inequality rather than as a list of bands, because the
        inequality is what the sentence in the refusal actually means."""
        floor = min(memory_score._CURVE[MemoryTier.scar])
        highest_candidate_score = max(
            v for v in range(0, 11) if memory_score.band(v) in CANDIDATE_BANDS
        )
        assert floor > highest_candidate_score, (
            f"scar floor {floor} no longer clears the top candidate score "
            f"{highest_candidate_score}"
        )

    def test_the_guard_can_see_a_tier_that_IS_nominable(self):
        """THE CONTROL. Without it, the two assertions above also pass when
        `band()` has been broken into never returning a candidate band at all,
        which is the same reading an empty candidate list gives."""
        working_floor = min(memory_score._CURVE[MemoryTier.working])
        assert memory_score.band(working_floor) in CANDIDATE_BANDS


class TestTheRefusalDoesNotAssertWhatIsFalse:
    def _refuse(self, client, owner, row):
        response = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{row.id}/demote",
            json={"to_tier": "working", "reason": "this tier is wrong"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )
        assert response.status_code == 400, response.text
        return response.json()["detail"]

    def test_it_no_longer_claims_every_other_tier_moves_under_consolidation(
        self, client, owner, scar_row
    ):
        detail = self._refuse(client, owner, scar_row)
        assert "already moves under consolidation" not in detail, (
            "the refusal has regained the false claim DWB-684 removed: the "
            "scar tier does not move under consolidation and cannot"
        )

    def test_it_still_says_why_it_refuses(self, client, owner, scar_row):
        detail = self._refuse(client, owner, scar_row)
        assert "not core" in detail
        assert "scar" in detail

    def test_it_names_the_route_that_does_reach_a_scar(
        self, client, owner, scar_row
    ):
        """A refusal that cannot say what to do instead is a wall, and the
        agent hitting it is holding something it is about to drop."""
        detail = self._refuse(client, owner, scar_row)
        assert "withdraw" in detail

    def test_the_named_route_carries_the_real_ids_not_placeholders(
        self, client, owner, scar_row
    ):
        """The reader is an agent whose call was just refused and who is
        already working out why. A URL it has to substitute into first is a
        cost charged at the worst possible moment, so the refusal hands over
        something that can be used as written."""
        detail = self._refuse(client, owner, scar_row)
        expected = (
            f"/api/agents/{owner['agent_id']}/memories/{scar_row.id}/withdraw"
        )
        assert expected in detail, detail
        assert "{agent_id}" not in detail
        assert "{memory_id}" not in detail


class TestWithdrawIsThatRoute:
    """Exercised rather than inferred: `withdraw_memory` has no tier check, so
    the refusal above is pointing somewhere real."""

    def test_a_scar_can_be_withdrawn_by_its_owner_and_lands_in_the_journal(
        self, client, db_session, owner, scar_row
    ):
        memory_id = scar_row.id
        response = client.post(
            f"/api/agents/{owner['agent_id']}/memories/{memory_id}/withdraw",
            json={"reason": "spent, not wrong"},
            headers={"X-Agent-ID": str(owner["agent_id"])},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["withdrawn"] is True
        # The tier is reported back, so the response itself records that this
        # path accepted a scar.
        assert payload["tier"] == "scar"

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is None

        # The content survived, with the reason appended by
        # memory_removal.journal_and_remove. A withdrawal that could not say
        # where the row went would be indistinguishable from a deletion.
        entry = client.get(f"/api/journal/{payload['journal_entry_id']}")
        assert entry.status_code == 200, entry.text
        body = entry.json()["body"]
        assert "a scar that has nowhere to go" in body
        assert "spent, not wrong" in body
