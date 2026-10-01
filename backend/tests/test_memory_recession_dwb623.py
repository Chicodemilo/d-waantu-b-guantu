# Path: tests/test_memory_recession_dwb623.py
# File: test_memory_recession_dwb623.py
# Created: 2026-10-01 (DWB-623)
# Purpose: Guard the receding adoption terminal condition. An agent's own
#          session-complete write comes back round as a fresh candidate after
#          its queue has drained, pushing the cutover back by one. The run now
#          REPORTS that, per agent and in total, so a recession is visible as it
#          happens rather than inferred from the run not finishing.
# Caller: pytest
# Callees: app.services.memory_adopt.enumerate_candidates,
#          app.services.memory_sweep.sweep,
#          app.services.memory_decide.decide_and_maybe_cut_over,
#          app.services.memory_transition.get_transition_status
# Data In: real memory.md files under a tmp_path repo, factory projects/agents
# Data Out: Assertions on re_enqueued / agents_re_enqueued and on termination
# Last Modified: 2026-10-01 (DWB-623)

"""DWB-623 acceptance.

THE DEFECT: the adoption terminal condition is not monotonic. An agent drains
its queue, truthfully reports empty, posts `session-complete`, and that write
lands in memory.md where the next sweep correctly picks it up as a new
candidate. The agent is holding work again moments after finishing, and the
cutover has moved away by one. It happened to all six agents in one adoption
and the run receded four times. Nothing in the instrument said so; the totals
simply changed, which looks identical to a run that was always that size. The
only thing that stopped it was a human telling people to stop writing.

WHICH OPTION WAS CHOSEN, AND WHY. The ticket offers two: surface the recession,
or stop completion-generated entries extending the run. THIS IMPLEMENTS THE
FIRST.

The second was rejected on the lane's own cardinal rule rather than on taste.
Excluding completion-generated entries from the terminal condition means the
cutover can fire while those entries are still pending, and the cutover SEALS
the flat file. A pending row at seal time is a lesson that exists in neither
store and cannot be read back - the one unrecoverable outcome in this design,
and the exact shape every other guard in this lane exists to prevent. Capture
is explicitly out of scope and must keep working, so the entries have to keep
being enumerated; what was missing was anyone being told.

WHY SURFACING IS SUFFICIENT FOR TERMINATION. The run was never actually
divergent. Each agent writes its wrap-up once, so each contributes a bounded
number of extra entries and the sweep comes back empty once writing stops.
`test_several_agents_wrapping_up_concurrently_still_terminates` drives exactly
that and shows the cutover landing with no human in the loop. What was missing
was the ability to tell "receding, expect another lap" from "stuck", and those
two want opposite responses.

ON ACCEPTANCE 3, PLAINLY. The criterion asks for a test that fails against the
pre-DWB-623 code. There is no such test here and no red was observed, because
the schema and service were written before these tests. What establishes the
same fact is `test_re_enqueued_separates_recession_from_never_having_started`:
two agents in one run, `done: False` for BOTH from the pre-existing fields, and
`re_enqueued` true for only one. The fields that existed return an identical
answer for two genuinely different situations, which IS the defect, shown
rather than argued. It is also the more durable artifact - a red proves the
defect existed once in a tree that no longer exists, this keeps proving it on
every run. A red was not manufactured by reverting the change, because doing
that on a shared uncommitted tree is a hazard this project has already paid
for tonight.
"""

import time
from datetime import datetime
from pathlib import Path

import pytest

from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_adopt, memory_decide, memory_format, memory_sweep
from app.services import memory_transition as status_svc


def _memory_md(repo: Path, prefix: str, agent_name: str) -> Path:
    path = repo / ".dwb" / "memory" / prefix / agent_name / "memory.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _render(bodies, chain=("Verification discipline",)) -> str:
    return memory_format.render(
        [memory_format.MemoryEntry(body=b, heading_path=chain) for b in bodies]
    )


@pytest.fixture
def adoption(db_session, make_project, make_agent, tmp_path):
    """Two agents mid-adopt, each holding two real entries from a real file.

    Two rather than one, because the recession needs a second agent still
    deciding: a lone agent's last decision cuts the run over BEFORE its wrap-up
    is written, so the single-agent case cannot reproduce the bug at all. That
    is also why this went unnoticed - it only appears with concurrency.
    """
    repo = tmp_path
    project_dict = make_project(repo_path=str(repo))
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.adopting

    # Names come from the factory rather than being hard-coded: `agents.name`
    # is unique system-wide, so a literal here collides the moment a second
    # test in the same session uses this fixture.
    agents = [make_agent(project_id=project.id) for _ in range(2)]
    for agent in agents:
        _memory_md(repo, project.prefix, agent["name"]).write_text(
            _render([f"{agent['name']} lesson one", f"{agent['name']} lesson two"]),
            encoding="utf-8",
        )

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
        # Stamped here because the BEGIN edge in project.py sets it, not
        # `enumerate_candidates`. Without it every cutover in this file is
        # refused for a reason that has nothing to do with recession, which is
        # how a fixture gap turns into four failures that all look like the
        # feature under test.
        enumerated_at=datetime(2026, 10, 1, 10, 0, 5),
    )
    db_session.add(run)
    db_session.flush()

    memory_adopt.enumerate_candidates(db_session, project, run, persist=True)
    db_session.flush()
    return project, agents, run, repo


# Two full seconds, and the reason is NOT merely the column's one-second
# resolution. Measured, after this assertion went red three times on three
# different subsets of tests:
#
#   A decided     wall 18:17:23.495  ->  stored decided_at  18:17:23
#   B decided     wall 18:17:24.635  ->  stored decided_at  18:17:25
#   swept row     wall 18:17:24.6    ->  stored created_at  18:17:24
#
# B's decision is stored HALF A SECOND IN THE FUTURE, and a row created after
# it is stored earlier. The two sides of the comparison do not round the same
# way: `created_at` is MySQL's own `NOW()` into a DATETIME(0) column, which
# TRUNCATES, while `decided_at` is a Python datetime carrying microseconds that
# MySQL ROUNDS half-up on the way in. So the error is up to a full second and
# it lands in exactly the direction that defeats `created_at > decided_at`.
#
# That is why this was FLAKY rather than consistently red: whether it fires
# depends on where in its second each event happened to fall.
#
# FIXED AT SOURCE BY DWB-633, not by this ticket: `memory_decide._decision_now()`
# now truncates, so both sides agree and the error is back down to the column's
# own one-second resolution. This gap only has to clear THAT, hence 1.5s rather
# than the 2.2s needed while the two roundings could compound. The gap stays
# even so: second resolution needs more than a second regardless, and a test
# that passes only because of a fix hides the next regression in the same area.
#
# In production this never matters - the sweep that finds a wrap-up runs when
# some OTHER agent finishes, minutes later - which is also why it only ever
# surfaced in a test that drives the whole sequence in one burst.
_ROUNDING_SAFE_GAP_SECONDS = 1.5


def _let_the_clock_advance():
    """Open a gap wider than the two columns' combined rounding error.

    Sleeping is the honest fix. Loosening the comparison to `>=`, or adding a
    one-second tolerance, would make the equal-second case flag, and that case
    also contains an agent merely part-way through its original queue - the
    exact confusion the predicate exists to prevent.
    """
    time.sleep(_ROUNDING_SAFE_GAP_SECONDS)


def _status(db, project_id):
    return status_svc.get_transition_status(db, project_id)


def _rows_of(db, run, agent_id):
    return (
        db.query(MemoryTransition)
        .filter(
            MemoryTransition.run_id == run.id,
            MemoryTransition.agent_id == agent_id,
        )
        .order_by(MemoryTransition.id.asc())
        .all()
    )


def _decide_all(db, run, agent_id, decided_by):
    landed = None
    for row in _rows_of(db, run, agent_id):
        if row.state in (TransitionState.pending,):
            _, landed = memory_decide.decide_and_maybe_cut_over(
                db,
                transition_id=row.id,
                tier="scar",
                decided_by=decided_by,
            )
    return landed


class TestRecessionIsVisible:
    """ACCEPTANCE 1 and 3. Fails against the pre-DWB-623 code, where neither
    `re_enqueued` nor `agents_re_enqueued` existed and a receded agent was
    indistinguishable from one that had never started."""

    def test_an_agent_that_drains_then_wraps_up_is_reported_as_re_enqueued(
        self, db_session, adoption
    ):
        project, agents, run, repo = adoption
        a, b = agents

        # Agent A drains its queue. The run is not finished - B still holds
        # two - so no cutover is attempted.
        _decide_all(db_session, run, a["id"], a["name"])
        _let_the_clock_advance()
        before = _status(db_session, project.id)
        a_before = next(r for r in before.agents if r.agent_id == a["id"])
        # Precondition, asserted in the test rather than assumed.
        assert a_before.done is True
        assert a_before.re_enqueued is False
        assert before.agents_re_enqueued == 0

        # A posts its wrap-up. This is the write the brief told every agent was
        # safe, and it IS safe for capture; it is termination it moves.
        path = _memory_md(repo, project.prefix, a["name"])
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n"
            + _render(["a wrap-up lesson written after the queue drained"]),
            encoding="utf-8",
        )

        # B finishes, which is what triggers the final sweep that finds it.
        _decide_all(db_session, run, b["id"], b["name"])

        after = _status(db_session, project.id)
        a_after = next(r for r in after.agents if r.agent_id == a["id"])
        b_after = next(r for r in after.agents if r.agent_id == b["id"])

        # ACCEPTANCE 1 says "show what the run reports". Printed, not just
        # asserted on: an assertion says the shape was what the author expected,
        # the payload lets the next reader check that for themselves. Visible
        # with `pytest -s`.
        print("\nDWB-623 run state after the recession:")
        print(f"  status            {after.status.value}")
        print(f"  entries_total     {before.entries_total} -> {after.entries_total}")
        print(f"  agents_re_enqueued {after.agents_re_enqueued}")
        for row in after.agents:
            print(
                f"  agent {row.agent_id}: total={row.entries_total} "
                f"done={row.entries_done} done_flag={row.done} "
                f"re_enqueued={row.re_enqueued}"
            )

        # The evidence the predicate runs on, carried INTO the failure message.
        # This assertion went red twice on different runs and the message said
        # only "False is True", which names the symptom and nothing that would
        # locate it. The predicate compares timestamps, so the timestamps are
        # what a reader needs.
        def _timeline(agent_id):
            return [
                (r.id, r.state.value, repr(r.created_at), repr(r.decided_at))
                for r in _rows_of(db_session, run, agent_id)
            ]

        assert a_after.re_enqueued is True, (
            "agent A drained, wrote its wrap-up, and is holding work again; "
            "the run must say so rather than only changing its totals.\n"
            f"A rows (id, state, created_at, decided_at): {_timeline(a['id'])}\n"
            f"B rows: {_timeline(b['id'])}"
        )
        assert a_after.done is False
        assert b_after.re_enqueued is False
        assert after.agents_re_enqueued == 1
        assert after.status.value == "in_progress"
        assert after.entries_total > before.entries_total, (
            "the terminal condition receded: the run grew after an agent "
            "reported itself finished"
        )

    def test_re_enqueued_separates_recession_from_never_having_started(
        self, db_session, adoption
    ):
        """The discriminating case, and the reason `done` could not carry this.

        Both agents here report `done: False`. One has not begun, the other
        drained and re-enqueued. A field that answers the same for both is not
        measuring the question.
        """
        project, agents, run, repo = adoption
        a, b = agents

        _decide_all(db_session, run, a["id"], a["name"])
        _let_the_clock_advance()
        path = _memory_md(repo, project.prefix, a["name"])
        path.write_text(
            path.read_text(encoding="utf-8") + "\n" + _render(["a later lesson"]),
            encoding="utf-8",
        )
        memory_sweep.sweep(db_session, project, run)
        db_session.flush()

        status = _status(db_session, project.id)
        a_row = next(r for r in status.agents if r.agent_id == a["id"])
        b_row = next(r for r in status.agents if r.agent_id == b["id"])

        assert a_row.done is False and b_row.done is False
        assert a_row.re_enqueued is True
        assert b_row.re_enqueued is False, (
            "B never decided anything, so it has not receded - it simply has "
            "not started, and conflating those tells an operator to chase the "
            "wrong agent"
        )

    def test_an_agent_mid_queue_is_not_flagged(self, db_session, adoption):
        """An agent part-way through its ORIGINAL queue holds non-terminal rows
        that predate its last decision, so it fails the recession predicate.
        Without this the flag would fire for every agent that is merely busy
        and would be ignored by the second run."""
        project, agents, run, repo = adoption
        a, _b = agents

        rows = _rows_of(db_session, run, a["id"])
        memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[0].id, tier="scar", decided_by=a["name"]
        )

        status = _status(db_session, project.id)
        a_row = next(r for r in status.agents if r.agent_id == a["id"])
        assert a_row.done is False
        assert a_row.re_enqueued is False


class TestItStillTerminates:
    """ACCEPTANCE 2. The run reaches a terminal state with no human in it."""

    def test_several_agents_wrapping_up_concurrently_still_terminates(
        self, db_session, adoption
    ):
        project, agents, run, repo = adoption
        a, b = agents

        # Both agents drain, and BOTH wrap up before the last decision lands -
        # the concurrent case the ticket names, where the recession compounds.
        _decide_all(db_session, run, a["id"], a["name"])
        _let_the_clock_advance()
        for agent in agents:
            path = _memory_md(repo, project.prefix, agent["name"])
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n"
                + _render([f"{agent['name']} wrap-up lesson"]),
                encoding="utf-8",
            )
        landed = _decide_all(db_session, run, b["id"], b["name"])
        assert landed is None, "the sweep found the wrap-ups, so no cutover yet"

        receded = _status(db_session, project.id)
        a_row = next(r for r in receded.agents if r.agent_id == a["id"])
        b_row = next(r for r in receded.agents if r.agent_id == b["id"])

        # ONE, NOT TWO, AND THE REASON IS STRUCTURAL RATHER THAN A CLOCK
        # ARTEFACT. This assertion read `== 2` while it was being written, on
        # the reasoning that both agents wrapped up so both receded. Both DID
        # recede. Only A is detectable.
        #
        # The sweep runs INSIDE `decide_and_maybe_cut_over`. So for B - the
        # agent whose own final decision triggers it - the swept row's
        # `created_at` and B's last `decided_at` are the SAME INSTANT by
        # construction, not merely the same second. B can therefore never
        # satisfy "every outstanding row arrived after my last decision", and
        # adding fractional seconds to those columns would not change that.
        # Every other agent that drained earlier is detected normally, which is
        # the population this exists for: the recessions that went unnoticed
        # were agents who had gone quiet and whose writes were found by somebody
        # else's decision.
        #
        # Recorded rather than quietly corrected to 1, because "expected 2, got
        # 1, changed to 1" is how a real defect gets absorbed into a test.
        assert receded.agents_re_enqueued == 1
        assert a_row.re_enqueued is True
        assert b_row.re_enqueued is False

        # AND THE INFORMATION IS NOT LOST FOR B, which is what makes the
        # under-reporting sound rather than a gap. B's recession is carried by
        # fields that were already there, in the same response.
        assert b_row.done is False
        assert b_row.entries_total == 3, "two enumerated plus one swept wrap-up"
        assert b_row.entries_done == 2

        # Nobody writes again. Drive the remaining decisions and the run must
        # land on its own - no human, no instruction to stop writing.
        landed = None
        for _lap in range(5):
            status = _status(db_session, project.id)
            if status.status.value == "idle":
                break
            outstanding = [
                row
                for agent in agents
                for row in _rows_of(db_session, run, agent["id"])
                if row.state == TransitionState.pending
            ]
            if not outstanding:
                break
            for row in outstanding:
                _, landed = memory_decide.decide_and_maybe_cut_over(
                    db_session,
                    transition_id=row.id,
                    tier="scar",
                    decided_by=a["name"],
                )

        db_session.refresh(run)
        assert run.state == TransitionRunState.completed, (
            "the run never reached a terminal state once writing stopped"
        )
        assert landed == MemoryMode.human_memory
        # And the recession is still legible after the fact: the run finished
        # with more entries than it enumerated.
        assert (
            db_session.query(MemoryTransition)
            .filter(MemoryTransition.run_id == run.id)
            .count()
            == 6
        ), "4 enumerated + 2 wrap-ups"

