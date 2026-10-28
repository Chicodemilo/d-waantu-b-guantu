# Path: tests/test_context_scope_dwb704.py
# File: test_context_scope_dwb704.py
# Created: 2026-10-28 (DWB-704)
# Purpose: Guard the write-time context-scope gate. A named scope must resolve
#          to something that can close; an ABSENT scope must still be accepted;
#          and a scope-free declaration must stay distinguishable from a data
#          gap rather than collapsing into it.
# Caller: pytest
# Callees: app.services.context_scope, app.services.memory_scan,
#          POST /api/agents/{id}/memories
# Data In: test DB rows via the factory fixtures
# Data Out: assertions on refusals, on the persisted row, and on scan verdicts
# Last Modified: 2026-10-28 (DWB-704)

"""DWB-704: the lane is starved, not broken, and the gate must not overfeed it.

Measured store-wide on 2026-10-28: 868 scar-family rows, 424 with a
`context_key`, 132 distinct values, ZERO ticket-shaped. `scan_context` returns
421 `unresolvable`, 447 `still_active`, 0 `finished`. No scar has ever
concluded. The mechanism itself works - a real ticket key reports
`still_active` while its ticket is open and `finished` once it closes - so what
is missing is a resolvable scope, not a code path.

THE TWO LOAD-BEARING CLASSES HERE GUARD AGAINST THE TWO WRONG FIXES, and both
wrong fixes pass a naive reading of this ticket.

`TestAbsenceIsNotRefused` is the first. The obvious implementation makes
`context_key` mandatory, which looks like the fix and silently destroys every
broad lesson: a scar is DELETED from memory when its context closes, so forcing
an author to borrow the ticket they happened to be sitting on means the lesson
evaporates when that ticket closes. On 2026-10-28, 0 of 23 writes supplied the
field at all, so a mandatory gate would have refused every real write on the
system.

`TestTheDeclarationIsNotTheDataGap` is the second. Both a declared-broad row and
an unrecorded one have a NULL `context_key`, and inferring the declaration from
that NULL is exactly the 2026-10-06 defect that read "I could not resolve this"
as "this scope is eternal" and promoted 381 of 455 rows into CORE. The column
exists so the two states cannot be confused; these tests fail if anything starts
deriving one from the other.

`TestTheGateIsTheScan` is the tripwire. The gate must use `memory_scan`'s own
resolvers, because a second copy would drift and the drift would be invisible:
a write would pass the gate and then resolve differently when the scan ran.
"""

import inspect

from app.models.agent_memory import AgentMemory
from app.models.epic import EpicStatus
from app.models.project import MemoryMode, Project
from app.services import context_scope, memory_scan
from app.services.memory_scan import ContextLiveness, scan_context

GOOD = {
    "body": "a lesson worth keeping, written through the real route",
    "condensed": "the shape of the write is not what this gate is about",
    "keywords": ["context key", "ticket closes"],
    "situation": "I am writing a lesson and wondering what context key to give "
                 "it before the ticket closes",
    "cost": "high",
}


def _writer(client, db_session, make_project, make_agent):
    """An agent on a human_memory project with an open DWB session."""
    project = make_project()
    db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
    db_session.flush()
    agent = make_agent(project_id=project["id"])
    opened = client.post(
        "/api/sessions/open",
        json={"project_id": project["id"], "open_method": "slash"},
    )
    assert opened.status_code in (200, 201), opened.text
    return project, agent


def _post(client, agent_id, **extra):
    return client.post(f"/api/agents/{agent_id}/memories", json={**GOOD, **extra})


def _count(db_session, agent_id):
    db_session.expire_all()
    return db_session.query(AgentMemory).filter(
        AgentMemory.agent_id == agent_id
    ).count()


class TestAbsenceIsNotRefused:
    """`context_key` stays OPTIONAL. The first wrong fix makes it mandatory."""

    def test_a_write_with_no_context_key_is_accepted(
        self, client, db_session, make_project, make_agent
    ):
        _, agent = _writer(client, db_session, make_project, make_agent)
        r = _post(client, agent["id"])
        assert r.status_code == 201, r.text
        assert _count(db_session, agent["id"]) == 1

    def test_the_server_does_not_invent_a_scope(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        """Even with exactly one open ticket on the project, the key stays NULL.

        The original proposal was to fill it from the session's ticket. A
        `DwbSession` carries no ticket, so the server would be guessing from
        assignments - unambiguous for 4 of 69 live agents. A scope the author
        did not choose is the same manufactured claim this area already paid
        for once.
        """
        project, agent = _writer(client, db_session, make_project, make_agent)
        make_ticket(project_id=project["id"])
        r = _post(client, agent["id"])
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row.context_key is None
        assert row.context_free is False


class TestANamedScopeMustBeAbleToClose:
    """If the author DOES name one, it has to resolve to something that ends."""

    def test_a_live_ticket_key_is_accepted_and_stored(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        project, agent = _writer(client, db_session, make_project, make_agent)
        ticket = make_ticket(project_id=project["id"])
        r = _post(client, agent["id"], context_key=ticket["ticket_key"])
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row.context_key == ticket["ticket_key"]
        assert scan_context(db_session, row) == ContextLiveness.still_active

    def test_a_heading_path_is_refused_and_the_message_teaches(
        self, client, db_session, make_project, make_agent
    ):
        """The shape 424 live rows carry."""
        _, agent = _writer(client, db_session, make_project, make_agent)
        r = _post(client, agent["id"], context_key="Verification discipline")
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "Verification discipline" in detail
        assert "context_free" in detail, "the refusal must offer the other answer"
        assert "ticket" in detail and "epic" in detail, "say what was searched"
        assert _count(db_session, agent["id"]) == 0

    def test_an_already_closed_ticket_is_refused(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        """Storing it would write the lesson and then delete it at the next scan."""
        project, agent = _writer(client, db_session, make_project, make_agent)
        ticket = make_ticket(project_id=project["id"])
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        r = _post(client, agent["id"], context_key=ticket["ticket_key"])
        assert r.status_code == 400, r.text
        assert "already" in r.json()["detail"]
        assert _count(db_session, agent["id"]) == 0

    def test_an_open_epic_name_resolves(
        self, client, db_session, make_project, make_agent, make_epic
    ):
        project, agent = _writer(client, db_session, make_project, make_agent)
        epic = make_epic(project_id=project["id"])
        r = _post(client, agent["id"], context_key=f"{epic['name']} / notes")
        assert r.status_code == 201, r.text

    def test_a_completed_epic_is_refused(
        self, client, db_session, make_project, make_agent, make_epic
    ):
        project, agent = _writer(client, db_session, make_project, make_agent)
        epic = make_epic(project_id=project["id"])
        client.patch(f"/api/epics/{epic['id']}", json={"status": "completed"})
        r = _post(client, agent["id"], context_key=f"{epic['name']} / notes")
        assert r.status_code == 400, r.text
        assert _count(db_session, agent["id"]) == 0

    def test_a_ticket_key_from_another_project_does_not_resolve(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        """Scoping. A real key, but not one this project can ever close."""
        _, agent = _writer(client, db_session, make_project, make_agent)
        other = make_ticket()
        r = _post(client, agent["id"], context_key=other["ticket_key"])
        assert r.status_code == 400, r.text
        assert _count(db_session, agent["id"]) == 0


class TestTheDeclarationIsNotTheDataGap:
    """Both have a NULL context_key. Only one is somebody's decision."""

    def test_a_declared_row_scans_as_declared_broad(
        self, client, db_session, make_project, make_agent
    ):
        _, agent = _writer(client, db_session, make_project, make_agent)
        r = _post(client, agent["id"], context_free=True)
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row.context_free is True
        assert row.context_key is None
        assert scan_context(db_session, row) == ContextLiveness.declared_broad

    def test_an_undeclared_row_with_the_same_null_key_scans_differently(
        self, client, db_session, make_project, make_agent
    ):
        """THE DISCRIMINATING PAIR. Identical in the column the old code read.

        Without this, every test above passes against an implementation that
        infers the declaration from the NULL - which is the defect, not the fix.
        """
        _, agent = _writer(client, db_session, make_project, make_agent)
        r = _post(client, agent["id"])
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row.context_key is None
        assert row.context_free is False
        assert scan_context(db_session, row) == ContextLiveness.still_active

    def test_the_declaration_is_echoed_on_the_response(
        self, client, db_session, make_project, make_agent
    ):
        """A flag the author can set and cannot read back is indistinguishable
        from one the server dropped."""
        _, agent = _writer(client, db_session, make_project, make_agent)
        declared = _post(client, agent["id"], context_free=True)
        assert declared.json()["context_free"] is True, declared.text
        plain = _post(client, agent["id"])
        assert plain.json()["context_free"] is False, plain.text

    def test_naming_a_scope_and_declaring_scope_free_is_refused(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        """Opposite claims. The server must not pick one."""
        project, agent = _writer(client, db_session, make_project, make_agent)
        ticket = make_ticket(project_id=project["id"])
        r = _post(client, agent["id"],
                  context_key=ticket["ticket_key"], context_free=True)
        assert r.status_code == 400, r.text
        assert _count(db_session, agent["id"]) == 0

    def test_declared_broad_is_not_cannot_die(self):
        """Declaring no ticket owns a lesson is not a claim that it is eternal.

        `cannot_die` is what `maybe_promote_scar` acts on. If these two are ever
        made equal, a scope-free declaration starts promoting rows into CORE,
        which is precisely the 381-of-455 incident with a new entry point.
        """
        assert ContextLiveness.declared_broad != ContextLiveness.cannot_die

    def test_the_new_verdict_is_inert_at_both_existing_consumers(self):
        """Both act by equality on a different member, so nothing acts on this."""
        from app.services import memory_promote
        promote = inspect.getsource(memory_promote.maybe_promote_scar)
        assert "cannot_die" in promote
        assert "declared_broad" not in promote

        from app.services import memory_scar_conclude
        conclude = inspect.getsource(memory_scar_conclude)
        assert "declared_broad" not in conclude


class TestTheGateIsTheScan:
    """The gate must resolve exactly as the scan later will."""

    def test_the_gate_imports_the_scan_resolvers_rather_than_copying_them(self):
        src = inspect.getsource(context_scope)
        assert "from app.services.memory_scan import" in src
        assert context_scope._resolve_ticket is memory_scan._resolve_ticket
        assert context_scope._resolve_epic is memory_scan._resolve_epic

    def test_the_gate_owns_no_resolution_rule_of_its_own(self):
        """No second regex, no second closed-status set."""
        src = inspect.getsource(context_scope)
        assert "re.compile" not in src
        assert context_scope._TICKET_CLOSED_STATUSES is (
            memory_scan._TICKET_CLOSED_STATUSES
        )

    def test_what_passes_the_gate_is_what_the_scan_can_conclude(
        self, client, db_session, make_project, make_agent, make_ticket
    ):
        """End to end: the property the gate exists to guarantee.

        A write that clears the gate must be a write the scan can later carry
        to `finished`. If the two ever resolve differently this is the test
        that goes red.
        """
        project, agent = _writer(client, db_session, make_project, make_agent)
        ticket = make_ticket(project_id=project["id"])
        r = _post(client, agent["id"], context_key=ticket["ticket_key"])
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        assert scan_context(db_session, row) == ContextLiveness.still_active

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        db_session.expire_all()
        row = db_session.get(AgentMemory, r.json()["id"])
        assert scan_context(db_session, row) == ContextLiveness.finished
