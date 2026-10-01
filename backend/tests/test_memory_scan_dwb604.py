# Path: tests/test_memory_scan_dwb604.py
# File: test_memory_scan_dwb604.py
# Created: 2026-09-30 (DWB-604)
# Purpose: Guard the context-liveness SCAN - three distinct outcomes, a real
#          ticket/epic lookup rather than a mocked assumption, and the two
#          worked examples from the human memory audit and from Miles.
# Caller: pytest
# Callees: app.services.memory_scan
# Data In: factory projects/agents/epics/tickets, agent_memories rows
# Data Out: Assertions on ContextLiveness
# Last Modified: 2026-09-30 (DWB-611: scar_context_bound collapsed into scar -
#                the no-context-key branch now asserts `still_active`, not
#                `cannot_die`; see memory_scan.py's own inline ruling)

"""DWB-604 acceptance, updated for the DWB-611 tier collapse.

Both acceptance examples are reproduced literally, against REAL ticket/epic
rows created through the same factories the rest of the suite uses, not
against a mocked resolver:

- "Given a scar tied to a closed epic/ticket lane, the scan reports context
  finished." -> `TestFinished`.
- "Given a scar tied to a standing, non-closing context (e.g. a general
  coding-standards lesson), the scan reports context cannot die." ->
  `TestCannotDie::test_a_context_naming_nothing_trackable_cannot_die`, which
  uses exactly that wording as an EXPLICIT context_key. Post-collapse this is
  the ONLY path to `cannot_die` - see `TestNoContextRecorded` below for why a
  missing key no longer takes this branch.

`TestStillActive` exists because the module docstring insists a third answer
has to be provable on its own, not inferred as "neither of the other two":
a scar tied to a real, OPEN ticket or epic must come back `still_active`,
which is the case that proves this isn't a two-valued check wearing a third
name.

`TestNoContextRecorded` is new with DWB-611. BEFORE the collapse, a plain
`scar` never carried a context_key by construction, so "no key" reliably meant
"deliberately general" and `cannot_die` was correct. AFTER the collapse, all
scars are context bound (Miles's ruling), so a missing key can only mean the
context was never RECORDED - a data gap, not a judgement - which is the same
failure as an unresolvable project and gets the same answer, `still_active`.
Nothing is lost: the genuine broad-context case still reaches `cannot_die`
through an explicit, unresolvable key, proven in `TestCannotDie`.
"""

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_scan as svc


def _memory(db, *, agent_id, tier=MemoryTier.scar, context_key=None):
    row = AgentMemory(agent_id=agent_id, tier=tier, body="a lesson", context_key=context_key)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestNoContextRecorded:
    """DWB-611: a missing context_key is a DATA GAP after the collapse, not a
    judgement - "could not look", not "will never close". Must report
    `still_active`, the same as an unresolvable project."""

    def test_no_context_key_at_all_is_still_active(self, db_session, agent):
        memory = _memory(db_session, agent_id=agent["id"], context_key=None)
        assert memory.context_key is None
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.still_active

    def test_blank_context_key_is_still_active(self, db_session, agent):
        """memory_decide.py notes a context-bound scar can be adopted before
        its heading survives the round trip, leaving context_key unset. Same
        answer as having no key at all - a whitespace-only string is not a
        named context any more than None is."""
        memory = _memory(db_session, agent_id=agent["id"], context_key="   ")
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.still_active


class TestCannotDie:
    """The ONLY path to cannot_die post-collapse: a named, EXPLICIT context
    that resolves to nothing the project can track."""

    def test_a_context_naming_nothing_trackable_cannot_die(self, db_session, agent):
        """THE TICKET'S OWN WORDED EXAMPLE: a general coding-standards
        lesson names a context, but not one this project can look up and
        watch for closure. Structurally it can never conclude."""
        memory = _memory(
            db_session, agent_id=agent["id"],
            context_key="general coding-standards lesson",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.cannot_die


class TestFinished:
    """THE TICKET'S OWN WORDED EXAMPLE: a scar tied to a closed epic/ticket
    lane reports finished."""

    def test_context_key_matching_a_done_ticket_is_finished(
        self, db_session, agent, make_ticket
    ):
        ticket = make_ticket(
            project_id=agent["project_id"],
            ticket_key="DWB-1701",
            status="done",
            title="Ship the thing",
        )
        memory = _memory(
            db_session, agent_id=agent["id"],
            context_key=f"{ticket['ticket_key']} / Shipping notes",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.finished

    def test_context_key_matching_a_cancelled_ticket_is_finished(
        self, db_session, agent, make_ticket
    ):
        """Cancelled is as closed as done: nothing further happens under
        either status."""
        ticket = make_ticket(
            project_id=agent["project_id"], ticket_key="DWB-1702", status="cancelled",
        )
        memory = _memory(
            db_session, agent_id=agent["id"], context_key=ticket["ticket_key"],
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.finished

    def test_context_key_matching_a_completed_epic_is_finished(
        self, db_session, agent, make_epic
    ):
        epic = make_epic(
            project_id=agent["project_id"], name="IndependenceDay project",
            status="completed",
        )
        memory = _memory(
            db_session, agent_id=agent["id"],
            context_key="IndependenceDay project / Documents",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.finished

    def test_epic_match_is_case_insensitive(self, db_session, agent, make_epic):
        make_epic(
            project_id=agent["project_id"], name="IndependenceDay project",
            status="completed",
        )
        memory = _memory(
            db_session, agent_id=agent["id"],
            context_key="INDEPENDENCEDAY PROJECT / documents",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.finished


class TestStillActive:
    """THE THIRD ANSWER, proved on its own: a real, identifiable, still-open
    context gets neither of the other two signals."""

    def test_context_key_matching_an_open_ticket_is_still_active(
        self, db_session, agent, make_ticket
    ):
        ticket = make_ticket(
            project_id=agent["project_id"], ticket_key="DWB-1703", status="in_progress",
        )
        memory = _memory(
            db_session, agent_id=agent["id"], context_key=ticket["ticket_key"],
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.still_active

    def test_context_key_matching_an_open_epic_is_still_active(
        self, db_session, agent, make_epic
    ):
        make_epic(project_id=agent["project_id"], name="Ongoing Work", status="open")
        memory = _memory(
            db_session, agent_id=agent["id"], context_key="Ongoing Work / notes",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.still_active

    def test_unresolvable_project_defaults_to_still_active_not_cannot_die(
        self, db_session, make_agent
    ):
        """An unscoped agent means the scan cannot even look, which is a
        different failure than a context that resolves to nothing (see the
        module docstring). Must NOT be reported as cannot_die: that is a
        positive claim DWB-606 acts on by writing tier=core, and manufacturing
        it from missing data would promote on no evidence at all."""
        from app.models.agent import Agent

        agent = make_agent()
        db_session.get(Agent, agent["id"]).project_id = None
        db_session.flush()
        memory = _memory(
            db_session, agent_id=agent["id"], context_key="DWB-9999 / whatever",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.still_active


class TestResolutionOrderAndScoping:
    def test_ticket_match_takes_priority_over_epic_match(
        self, db_session, agent, make_ticket, make_epic
    ):
        """A context_key can plausibly mention both a ticket key and its
        epic's name. The ticket is the more precise unit and wins, so a
        closed ticket under a still-open epic reports finished rather than
        the epic's still_active."""
        make_epic(project_id=agent["project_id"], name="Wide Epic", status="open")
        ticket = make_ticket(
            project_id=agent["project_id"], ticket_key="DWB-1704", status="done",
        )
        memory = _memory(
            db_session, agent_id=agent["id"],
            context_key=f"Wide Epic / {ticket['ticket_key']}",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.finished

    def test_a_ticket_key_from_another_project_does_not_match(
        self, db_session, agent, make_project, make_ticket
    ):
        other_project = make_project()
        make_ticket(
            project_id=other_project["id"], ticket_key="OTHR-1", status="done",
        )
        memory = _memory(db_session, agent_id=agent["id"], context_key="OTHR-1")
        # OTHR-1 exists, but not in this agent's project, so it is invisible
        # to the scan and the context resolves to nothing trackable here.
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.cannot_die

    def test_an_epic_name_from_another_project_does_not_match(
        self, db_session, agent, make_project, make_epic
    ):
        other_project = make_project()
        make_epic(
            project_id=other_project["id"], name="Someone Elses Epic",
            status="completed",
        )
        memory = _memory(
            db_session, agent_id=agent["id"], context_key="Someone Elses Epic",
        )
        assert svc.scan_context(db_session, memory) == svc.ContextLiveness.cannot_die


class TestScopeGuard:
    """The scan is defined over the scar family only. Everything else is a
    caller error, not a state to guess an answer for."""

    @pytest.mark.parametrize(
        "tier", [MemoryTier.working, MemoryTier.core, MemoryTier.raw]
    )
    def test_non_scar_tiers_are_refused(self, db_session, agent, tier):
        memory = _memory(db_session, agent_id=agent["id"], tier=tier)
        with pytest.raises(svc.ScanError) as exc_info:
            svc.scan_context(db_session, memory)
        assert exc_info.value.code == "not_a_scar"
