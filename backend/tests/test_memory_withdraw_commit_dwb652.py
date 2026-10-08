# Path: tests/test_memory_withdraw_commit_dwb652.py
# File: test_memory_withdraw_commit_dwb652.py
# Created: 2026-10-08 (DWB-652)
# Purpose: Guard that the withdraw route COMMITS - structurally, because the
#          test harness cannot observe a commit at all (DWB-653) - and that a
#          withdrawal which fails does not report success.
# Caller: pytest
# Callees: app.routers.agents.withdraw_agent_memory,
#          app.services.memory_withdraw, POST /api/agents/{id}/memories/{mid}/withdraw
# Data In: test DB rows via the factory fixtures; the router source for the
#          structural guards
# Data Out: Assertions on the AST of the route and on failure-path behaviour
# Last Modified: 2026-10-08 (DWB-652)

"""DWB-652: the withdraw route returned 200 and persisted nothing.

READ THIS BEFORE ADDING A TEST HERE, BECAUSE THE OBVIOUS TEST IS WORTHLESS.

`tests/conftest.py:93-110` gives the test and the TestClient ONE session, inside
a single outer transaction that is rolled back at teardown. The route reads and
writes that same session, so a test that calls withdraw and then asserts the row
is gone PASSES WITH AND WITHOUT THE COMMIT - it is reading uncommitted state out
of the session that wrote it. That is DWB-653, it is not fixed here, and it is
why this bug shipped green under DWB-626's own test file.

So the behavioural half of this file is NOT evidence that the fix works, and it
is not presented as such. The real evidence is a live API round-trip in a fresh
request against the dev server, recorded in the ticket. What the suite can
honestly do is two things, and that is what is here:

  1. STRUCTURAL. Assert the commit exists, on the SUCCESS path specifically, by
     walking the route's AST. A structural guard is the right tool when the
     runtime cannot observe the property: it cannot be fooled by the shared
     session because it never runs the route at all. It is also what fails if
     someone later "tidies" the commit into the except block, which would be
     invisible to every behavioural test in this repo.

  2. THE FAILURE PATH, which IS observable in-harness. If the commit raises, the
     caller must not get a 200 and the row must survive. That needs no committed
     state to assert, so the shared session does not hide it.

The ownership and not-found cases are covered by test_memory_withdrawal_dwb626.py
and are not duplicated here.
"""

import ast
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from tests.conftest import MEMORY_WRITE_EXTRAS

ROUTER_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "app" / "routers" / "agents.py"
)
ROUTE_NAME = "withdraw_agent_memory"


def _route_node():
    tree = ast.parse(ROUTER_PATH.read_text(), filename=str(ROUTER_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == ROUTE_NAME:
            return node
    raise AssertionError(
        f"{ROUTE_NAME} is gone from {ROUTER_PATH.name}; this whole file is "
        "asserting against a route that no longer exists"
    )


def _commit_calls(node):
    """Every `<something>.commit()` call inside `node`, as (call, lineno)."""
    return [
        (c, c.lineno)
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "commit"
    ]


@pytest.fixture
def owned_memory(client, db_session, make_project, make_agent):
    """One memory on a human_memory project, owned by a known agent."""
    project = make_project()
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    agent = make_agent(project_id=project["id"])
    opened = client.post(
        "/api/sessions/open",
        json={"project_id": project["id"], "open_method": "slash"},
    )
    assert opened.status_code == 201, opened.text
    written = client.post(
        f"/api/agents/{agent['id']}/memories",
        json={
            **MEMORY_WRITE_EXTRAS,
            "body": "a lesson that turned out to be wrong",
        },
    )
    assert written.status_code == 201, written.text
    return agent["id"], written.json()["id"]


class TestTheCommitExistsOnTheSuccessPath:
    """The structural half. The runtime cannot see this property at all."""

    def test_the_route_commits(self):
        node = _route_node()
        calls = _commit_calls(node)
        assert calls, (
            "the withdraw route contains no commit. The services it calls are "
            "flush-only by contract - memory_withdraw.withdraw_memory says "
            "'the router owns the transaction' and memory_removal."
            "journal_and_remove says 'Does NOT commit' - so with no commit here "
            "the journal entry, the FK break and the delete are all discarded "
            "and the route answers 200 anyway. That is DWB-652."
        )

    def test_the_commit_is_not_buried_in_an_exception_handler(self):
        """A commit reachable ONLY from an `except` would satisfy the test above
        while leaving the success path writing nothing.

        This is the mutation that a behavioural suite could never catch here,
        which is exactly why it is asserted structurally.
        """
        node = _route_node()
        handler_lines = set()
        for handler in [
            h for n in ast.walk(node) if isinstance(n, ast.Try) for h in n.handlers
        ]:
            for inner in ast.walk(handler):
                if hasattr(inner, "lineno"):
                    handler_lines.add(inner.lineno)

        commits = _commit_calls(node)
        on_success = [c for c, line in commits if line not in handler_lines]
        assert on_success, (
            f"every commit in {ROUTE_NAME} sits inside an except handler "
            f"(commit lines {[l for _, l in commits]}, handler lines "
            f"{sorted(handler_lines)}). The success path still persists nothing."
        )

    def test_the_commit_runs_after_the_withdrawal_not_before(self):
        """Committing before the service runs would commit an empty unit of work
        and discard the real one. Asserted by line order, which is crude but is
        the property that matters and is not otherwise observable."""
        node = _route_node()
        withdraw_calls = [
            c.lineno
            for c in ast.walk(node)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "withdraw_memory"
        ]
        assert withdraw_calls, "the route no longer calls withdraw_memory"
        commits = [line for _, line in _commit_calls(node)]
        # Asserted before max(), which raises ValueError on an empty list - a
        # crash reads as a broken test rather than as the missing commit it
        # actually is, and the point of this file is to name the defect.
        assert commits, "the withdraw route contains no commit at all"
        assert max(commits) > min(withdraw_calls), (
            f"commit at {commits} runs before withdraw_memory at "
            f"{withdraw_calls}; the withdrawal would not be in the transaction"
        )


class TestAFailedWithdrawDoesNotReportSuccess:
    """AC3. Observable in-harness because it asserts on what did NOT happen in
    the response, not on committed state."""

    def test_a_commit_failure_is_not_a_200_and_leaves_the_row(
        self, client, db_session, owned_memory, monkeypatch
    ):
        agent_id, memory_id = owned_memory

        real_commit = db_session.commit

        def boom():
            raise RuntimeError("deliberate commit failure")

        monkeypatch.setattr(db_session, "commit", boom)
        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/withdraw",
            json={"reason": "retracting"},
            headers={"X-Agent-ID": str(agent_id)},
        )
        monkeypatch.setattr(db_session, "commit", real_commit)

        assert r.status_code != 200, (
            f"the commit failed and the caller was told the withdrawal "
            f"succeeded: {r.text}"
        )
        assert r.status_code >= 500, r.status_code
        # The body must say the memory survived, since that is what the route
        # promises on this path and it is the only part of the promise this
        # harness can see.
        assert "was NOT withdrawn" in r.text, r.text
        assert str(memory_id) in r.text

        # WHAT IS DELIBERATELY NOT ASSERTED HERE, AND WHY.
        #
        # "the row still exists" is the outcome that matters, and it CANNOT be
        # checked in this harness. The route's failure path calls db.rollback(),
        # and conftest hands the route the SAME session the test is using - the
        # one holding the outer transaction that created this fixture. So the
        # rollback unwinds the fixture's project, agent and memory along with
        # the withdrawal, and `db_session.get(...)` returns None because
        # EVERYTHING is gone, not because the memory was deleted.
        #
        # An earlier version of this test asserted `row is not None` and failed
        # against a correct fix for exactly that reason. In production get_db
        # gives every request its own session, so the rollback discards only
        # that request's work and the row survives - which is verified live in
        # the ticket, not here. This is DWB-653 again, one layer further in.

    def test_an_ownership_refusal_does_not_commit(
        self, client, db_session, owned_memory, make_agent
    ):
        """A 403 must not be a commit. Covered structurally by
        test_the_commit_is_not_buried_in_an_exception_handler, and here as the
        outcome: the row survives and the caller is refused."""
        agent_id, memory_id = owned_memory
        stranger = make_agent()["id"]

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/withdraw",
            json={"reason": "not mine to pull"},
            headers={"X-Agent-ID": str(stranger)},
        )
        assert r.status_code == 403, r.text
        assert db_session.get(AgentMemory, memory_id) is not None


class TestWhatThisSuiteCannotProve:
    """A test that documents the hole, so nobody reads this file as coverage it
    is not.

    Deliberately asserts the DEFECT, not the fix: as long as conftest hands the
    route the same session the test reads from, this passes. The day DWB-653
    gives tests a separately-committing session, this test fails and whoever is
    holding it should delete it and write the real round-trip instead.
    """

    def test_the_harness_shares_one_session_so_commits_are_invisible(self):
        conftest = (
            pathlib.Path(__file__).resolve().parents[0] / "conftest.py"
        ).read_text()
        assert "def override_get_db" in conftest
        assert "transaction.rollback()" in conftest, (
            "conftest no longer rolls the outer transaction back - if tests now "
            "commit for real, DWB-653 may be fixed and this file's structural "
            "guards can be replaced by an actual cross-request round-trip"
        )
