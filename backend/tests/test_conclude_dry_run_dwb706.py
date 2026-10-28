# Path: tests/test_conclude_dry_run_dwb706.py
# File: test_conclude_dry_run_dwb706.py
# Created: 2026-10-28
# Purpose: DWB-706 step 1 - the dry-run counter, taken with the resting-score gate STILL IN PLACE
# Caller: pytest
# Callees: app/services/memory_scar_conclude.conclude_dry_run, _conclude_candidates, evict_concluded_scars, app/services/memory_consolidate.consolidate_agent
# Data In: factory fixtures, closed DWB sessions to drive the decay gap
# Data Out: Assertions on candidates / would_move / at_rest_now and on read-only-ness
# Last Modified: 2026-10-28

"""DWB-706 step 1: size the conclude lane BEFORE changing it.

WHY THE COUNTER SHIPS FIRST AND ALONE. A counter whose first run is in the
same change that alters the behaviour cannot say what the behaviour used to
be. The before-reading has to exist before the change does, so this lands with
the gate untouched and `at_rest_now` still reporting what the gate lets
through.

THE INSTRUMENT IS THE PAIR, NOT EITHER NUMBER. `candidates` and `would_move`
being DIFFERENT is the whole point: one number alone cannot
distinguish "the lane is holding back a flood" from "the lane is holding back
nothing", and those call for opposite decisions.

STEP 2 REMOVED THE GATE, and these tests moved with it rather than being
deleted - see `test_a_finished_scar_is_now_nominated_and_concluded`, which
asserted the opposite until the gate went. Deleting it would have erased the
only evidence in the suite that the gate was ever there.

EVERY ZERO HERE IS PAIRED WITH A CASE THAT MAKES IT NON-ZERO. A counter that
reports 0 because it cannot count is indistinguishable from one reporting 0
because there is nothing to count, and the first is the likelier bug in a
function written to report an absence.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import memory_consolidate
from app.services import memory_scar_conclude as svc


def _closed_session(db, project_id, *, hours_ago=1):
    from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession

    s = DwbSession(
        project_id=project_id,
        opened_at=datetime.utcnow() - timedelta(hours=hours_ago),
        closed_at=datetime.utcnow() - timedelta(hours=hours_ago) + timedelta(minutes=5),
        open_method=DwbOpenMethod.regex,
        close_method=DwbCloseMethod.regex,
    )
    db.add(s)
    db.flush()
    return s


def _hook_session(db, *, agent_id, project_id, dwb_session_id, tag):
    from app.models.hook_session import HookSession

    h = HookSession(
        session_id=f"dwb706-dry-{tag}", agent_id=agent_id, project_id=project_id,
        dwb_session_id=dwb_session_id, total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _elapse(db, *, project_id, agent_id, n):
    """Give the agent `n` closed DWB sessions, which is what moves the gap."""
    for i in range(n):
        s = _closed_session(db, project_id, hours_ago=n - i)
        _hook_session(
            db, agent_id=agent_id, project_id=project_id,
            dwb_session_id=s.id, tag=f"e{i}",
        )


def _memory(db, *, agent_id, tier=MemoryTier.scar, **kw):
    kw.setdefault("body", "a lesson")
    row = AgentMemory(agent_id=agent_id, tier=tier, **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestTheCounterCanCountAtAll:

    def test_a_finished_scar_is_counted_in_would_move(
        self, db_session, agent, make_ticket
    ):
        """THE POSITIVE CONTROL, first, because every other assertion in this
        file is about a zero. If this cannot reach 1, a 0 anywhere else proves
        nothing."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7060", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="pos",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )

        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.scar_family == 1
        assert d.candidates == 1
        assert d.would_move == 1, "the counter cannot report a finished scar"
        assert d.verdicts.get("finished") == 1

    def test_a_still_active_context_is_a_candidate_but_not_a_mover(
        self, db_session, agent, make_ticket
    ):
        """Paired with the test above so `would_move` is shown to
        DISCRIMINATE. Without this, a counter that returned
        `would_move == candidates` would pass the positive control."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7061", status="in_progress",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="act",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )

        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.candidates == 1
        assert d.would_move == 0
        assert d.verdicts.get("still_active") == 1


class TestItShowsTheGapTheGateCreates:

    def test_a_finished_scar_is_now_nominated_and_concluded(
        self, db_session, agent, make_ticket
    ):
        """WAS `test_a_finished_scar_counts_as_would_move_while_the_gate_
        refuses_it`, AND IT ASSERTED THE OPPOSITE.

        Until DWB-706 step 2 this pinned the GAP: the row was finished,
        `would_move` said 1, and `at_rest_now` said 0 because the
        resting-score gate refused to nominate anything. That gap is what the
        gate's removal closed, so the test inverts rather than disappears -
        deleting it would erase the evidence that the gate was ever there.

        `at_rest_now` is still asserted, and still 0, but it now means
        something different: it is a measurement that gates nothing. The row
        is nominated despite it, which is the whole change in one assertion.
        """
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7062", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="gap",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )

        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.would_move == 1
        assert d.at_rest_now == 0, (
            "the row is nowhere near the resting score - which is exactly why "
            "it could never be concluded before the gate was removed"
        )

        # The live pass now acts on it, with no clock involved.
        out = svc.evict_concluded_scars(db_session, agent_id=agent_id)
        assert out.nominated == 1, "the gate is back: a finished scar was not nominated"
        assert len(out.created) == 1
        assert out.unfinished == 0

    def test_the_dry_run_population_agrees_with_the_live_one(
        self, db_session, agent, make_ticket
    ):
        """WAS a cross-check of `at_rest_now` against `_scars_at_rest`, which
        was the gate. DWB-706 removed both, so the check moves to the thing
        that can still drift.

        `conclude_dry_run` re-derives the population in its own traversal
        rather than calling `_conclude_candidates`, which is what keeps its
        two counts consistent with each other - and is exactly how it could
        come to disagree with what the pass actually examines."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7063", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="agree",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=3)

        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.candidates == len(
            svc._conclude_candidates(db_session, agent_id=agent_id)
        ), "the dry run and the pass disagree about what gets examined"
        # And the pass itself nominates that same number.
        out = svc.evict_concluded_scars(db_session, agent_id=agent_id)
        assert out.nominated == d.candidates


class TestUnscoredRowsAreReportedNotResolved:

    def test_both_populations_are_reported(self, db_session, agent, make_ticket):
        """Archie_DWB ruled the unscored rows IN: `gap is None` is a CLOCK
        FACT, and keeping an exclusion on it inside a decision the clock was
        removed from would smuggle the decay dependency back in under another
        name.

        So `candidates` includes them and `candidates_excluding_unscored` is
        kept as the counterfactual, which is what shows a later reader what
        that ruling costs. The two differing is the point; asserting only the
        live one would let the counterfactual silently become a copy."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7064", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="scored",
        )
        # One scored, one with NO origin at all.
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )
        _memory(db_session, agent_id=agent_id, context_key=ticket["ticket_key"])

        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.scar_family == 2
        assert d.unscored_no_origin == 1
        assert d.candidates == 2, "the unscored row must be a candidate now"
        assert d.candidates_excluding_unscored == 1
        assert d.would_move == 2, "both finished rows move"
        assert d.would_move_excluding_unscored == 1
        # The pass agrees: the unscored row is concluded like any other.
        out = svc.evict_concluded_scars(db_session, agent_id=agent_id)
        assert out.nominated == 2 and len(out.created) == 2


class TestItMovesNothing:

    def test_the_dry_run_journals_nothing_and_deletes_nothing(
        self, db_session, agent, make_ticket
    ):
        """It is named a dry run; this is the assertion that makes the name
        true. Counts are taken BEFORE and compared AFTER rather than merely
        checking the return value, because a function that both reports and
        acts would still return a correct-looking report."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7065", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="pure",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )

        memories_before = db_session.scalar(
            select(func.count(AgentMemory.id)).where(AgentMemory.agent_id == agent_id)
        )
        journal_before = db_session.scalar(
            select(func.count(JournalEntry.id)).where(JournalEntry.agent_id == agent_id)
        )
        # POSITIVE CONTROL on the fixture: there must be something it COULD
        # have moved, or "nothing moved" is vacuous.
        d = svc.conclude_dry_run(db_session, agent_id=agent_id)
        assert d.would_move == 1

        assert db_session.scalar(
            select(func.count(AgentMemory.id)).where(AgentMemory.agent_id == agent_id)
        ) == memories_before
        assert db_session.scalar(
            select(func.count(JournalEntry.id)).where(JournalEntry.agent_id == agent_id)
        ) == journal_before


class TestTheRealPassCarriesTheNumbers:

    def test_consolidate_agent_reports_candidates_and_would_move(
        self, db_session, agent, make_ticket
    ):
        """The counter has to be visible from a real pass, not only from a
        function a human remembers to call."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-7066", status="done",
        )
        session = _closed_session(db_session, project_id)
        _hook_session(
            db_session, agent_id=agent_id, project_id=project_id,
            dwb_session_id=session.id, tag="pass",
        )
        _memory(
            db_session, agent_id=agent_id, context_key=ticket["ticket_key"],
            created_session_id=session.id,
        )

        result = memory_consolidate.consolidate_agent(db_session, agent_id=agent_id)
        assert result.conclude_candidates == 1
        assert result.conclude_would_move == 1
        # BEFORE DWB-706 step 2 the next two asserted 0 and [] - the gate let
        # nothing through, so the counter predicted a move the pass could not
        # make. Now the prediction and the action agree, which is the whole
        # change. The pair is still worth asserting together: a counter that
        # silently stopped matching the pass would be worse than no counter.
        assert result.concluded_nominated == 1
        assert len(result.concluded_scars) == 1
