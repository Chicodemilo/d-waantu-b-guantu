# Path: tests/test_memory_session_trigger_dwb650.py
# File: test_memory_session_trigger_dwb650.py
# Created: 2026-10-08 (DWB-650)
# Purpose: Guard the session-open consolidation trigger - that opening a DWB
#          session consolidates EVERY agent on the roster including one that
#          has never had a SessionStart, that a stock project runs nothing,
#          that one agent's failure neither blocks the rest nor fails the open,
#          that a failure is readable afterwards, and that the pass is still
#          not a READ.
# Caller: pytest
# Callees: app.services.dwb_session.open_session, app.services.
#          memory_session_trigger, app.services.memory_consolidate,
#          POST /api/sessions/open
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on persisted tiers, activity_log and error_logs rows
# Last Modified: 2026-10-08 (DWB-650)

"""DWB-650 acceptance: the DWB session open is the trigger.

WHAT WAS BROKEN, AND WHY A GREEN SUITE WAS NOT EVIDENCE. `consolidate_agent`
had one call site, on a Claude Code SessionStart, which fires for ONE agent and
only for one whose identity was already resolved. A subagent's marker is not
renamed until its first SubagentStop, so a subagent never produced a
SessionStart row with an agent attached. Over seven days, all projects: 275
SubagentStop hook_sessions against 10 SessionStart, and the only two agents
holding a SessionStart row were the two team leads. That mechanism was fully
tested and had never once run for the population it was supposed to serve, so
the tests here are written against the POPULATION rather than against the call.

Hence `TestTheAgentNobodyEverReached`, which builds the exact shape that was
unreachable - an agent whose only hook_sessions are SubagentStop and which has
no SessionStart row at all - and asserts it is reached. A test that used a
freshly-made agent with no hook_sessions at all would pass against the old code
too for a different reason, which is the trap this file exists to avoid.

THE TRIGGER IS ASSERTED AT THE SERVICE, NOT AT THE ROUTER. `open_session` has
three callers and will have more. `TestEverySessionOpenPathTriggersIt` calls the
service directly, so the test fails if someone moves the trigger up into the
endpoint - which would work for `POST /api/sessions/open` and silently not work
for the two hook paths that open a session from a matched phrase.

FAILURES ARE TESTED IN PAIRS. Constraint 2 is DWB-636: a swallowed failure reads
exactly like a clean no-op. So every failure test asserts against a CLEAN pass
in the same test, on the same fixture - a record that exists either way is not a
record, and only the difference between the two is evidence.
"""

import ast
import pathlib

import pytest

from app.models.activity_log import ActivityLog
from app.models.agent_memory import AgentMemory, MemoryCost, MemoryTier
from app.models.error_log import ErrorLog
from app.models.hook_session import HookSession
from app.models.project import MemoryMode, Project
from app.models.project_agent import ProjectAgent
from app.services import (
    dwb_session as dwb_svc,
    memory_consolidate,
    memory_score,
    memory_session_trigger,
)

SERVICES_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def human_project(db_session, make_project):
    """A project in human_memory mode with NO session open yet."""
    project = make_project()
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    return project["id"]


@pytest.fixture
def stock_project(make_project):
    return make_project()["id"]


def _roster_agent(db_session, make_agent, project_id, **overrides):
    """An agent that is BOTH scoped to the project and on `project_agents`.

    Both, because the two are different claims and this ticket turns on which
    one the roster query uses: `agents.project_id` is what `memory_origin` and
    `_active_session_id` resolve a session through, `project_agents` is the
    roster `consolidate_project_roster` iterates. A fixture that set only one
    would make a passing test ambiguous about which definition is live.

    `POST /api/agents` already writes the join row, so membership is ASSERTED
    here rather than inserted - adding a second one hits the
    `uq_project_agent` unique constraint, and an assert is the better version
    of that discovery anyway: if agent creation ever stops joining the roster,
    this fails here instead of producing a silently empty pass downstream.
    """
    agent = make_agent(project_id=project_id, **overrides)
    joined = (
        db_session.query(ProjectAgent)
        .filter(ProjectAgent.project_id == project_id)
        .filter(ProjectAgent.agent_id == agent["id"])
        .count()
    )
    assert joined == 1, (
        f"agent {agent['id']} is not on project {project_id}'s roster; every "
        "roster test below would run over an empty set"
    )
    return agent["id"]


def _unassign(db_session, project_id, agent_id):
    """Take an agent OFF the roster while leaving `agents.project_id` set.

    The only way to build the case that tells the two roster definitions apart,
    because agent creation joins both at once.
    """
    db_session.query(ProjectAgent).filter(
        ProjectAgent.project_id == project_id, ProjectAgent.agent_id == agent_id
    ).delete()
    db_session.flush()


def _raw_memory(db_session, agent_id, body, **tags):
    """One pre-DWB-649 style row: tier `raw`, no clock origin.

    No `created_session_id` on purpose. That is the state of the rows this lane
    actually stranded, and it exercises the stamping branch in
    `tier_raw_memories` rather than the easy path.
    """
    row = AgentMemory(agent_id=agent_id, tier=MemoryTier.raw, body=body, **tags)
    db_session.add(row)
    db_session.flush()
    return row


def _pass_rows(db_session, project_id):
    return (
        db_session.query(ActivityLog)
        .filter(ActivityLog.project_id == project_id)
        .filter(ActivityLog.action == memory_session_trigger.ACTIVITY_ACTION)
        .all()
    )


def _error_rows(db_session, project_id):
    return (
        db_session.query(ErrorLog)
        .filter(ErrorLog.project_id == project_id)
        .filter(ErrorLog.endpoint == memory_session_trigger.ERROR_ENDPOINT)
        .all()
    )


# ---------------------------------------------------------------------------
# AC1 / AC2
# ---------------------------------------------------------------------------


class TestTheWholeRosterIsConsolidated:
    """AC1. Every agent on the project, not the opener and not the TL."""

    def test_opening_a_session_tiers_raw_rows_for_every_agent_on_the_roster(
        self, client, db_session, human_project, make_agent
    ):
        a = _roster_agent(db_session, make_agent, human_project)
        b = _roster_agent(db_session, make_agent, human_project)
        c = _roster_agent(db_session, make_agent, human_project)
        rows = [
            _raw_memory(db_session, a, "a-high", cost=MemoryCost.high),
            _raw_memory(db_session, b, "b-untagged"),
            _raw_memory(db_session, c, "c-surprised", surprised=True),
        ]
        db_session.commit()
        assert all(r.tier == MemoryTier.raw for r in rows), "fixture is not raw"

        opened = client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        assert opened.status_code == 201, opened.text

        for row in rows:
            db_session.refresh(row)
        # Named per row rather than "none are raw": an absence assertion over a
        # list that somehow came back empty would pass without touching one.
        assert [r.tier for r in rows] == [
            MemoryTier.scar,
            MemoryTier.working,
            MemoryTier.scar,
        ], [r.tier for r in rows]

    def test_an_agent_scoped_to_the_project_but_NOT_on_the_roster_is_left_alone(
        self, client, db_session, human_project, make_agent
    ):
        """The roster is `project_agents`, and that is a choice with a visible
        consequence. Asserted beside an agent that IS on the roster, in the same
        pass - "nothing moved" on its own would also be true if the pass never
        ran at all."""
        on_roster = _roster_agent(db_session, make_agent, human_project)
        off_roster = make_agent(project_id=human_project)["id"]
        _unassign(db_session, human_project, off_roster)

        moved = _raw_memory(db_session, on_roster, "on roster")
        untouched = _raw_memory(db_session, off_roster, "scoped but unassigned")
        db_session.commit()

        client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )

        db_session.refresh(moved)
        db_session.refresh(untouched)
        assert moved.tier == MemoryTier.working, "the pass did not run at all"
        assert untouched.tier == MemoryTier.raw

    def test_an_inactive_roster_agent_is_still_consolidated(
        self, client, db_session, human_project, make_agent
    ):
        """Deliberate departure from `list_project_team`, which is active-only.
        Excluding retired agents would strand their rows permanently, which is
        this ticket's own defect one population over."""
        retired = _roster_agent(
            db_session, make_agent, human_project, is_active=False
        )
        row = _raw_memory(db_session, retired, "written before retirement")
        db_session.commit()

        client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        db_session.refresh(row)
        assert row.tier == MemoryTier.working


class TestTheAgentNobodyEverReached:
    """AC2, and the reason this ticket exists."""

    def test_an_agent_whose_only_hook_sessions_are_SubagentStop_is_consolidated(
        self, client, db_session, human_project, make_agent
    ):
        """The exact population the old mechanism could not see.

        The agent is given three SubagentStop hook_sessions and ZERO
        SessionStart rows, which is what a subagent's history actually looks
        like: its identity is only resolved when its pending marker is renamed
        at the first SubagentStop, so no SessionStart ever carried its agent_id.
        The absence of a SessionStart row is ASSERTED rather than assumed,
        because a fixture that quietly grew one would turn this into a test of
        the old path.
        """
        agent_id = _roster_agent(db_session, make_agent, human_project)
        for i in range(3):
            db_session.add(
                HookSession(
                    session_id=f"dwb650-subagentstop-{agent_id}-{i}",
                    agent_id=agent_id,
                    project_id=human_project,
                    session_type="subagent",
                    hook_event="SubagentStop",
                    status="completed",
                    total_tokens=10,
                )
            )
        row = _raw_memory(db_session, agent_id, "never once consolidated")
        db_session.commit()

        starts = (
            db_session.query(HookSession)
            .filter(HookSession.agent_id == agent_id)
            .filter(HookSession.hook_event == "SessionStart")
            .count()
        )
        assert starts == 0, (
            "the fixture has a SessionStart row, so it is no longer the "
            "population this ticket is about"
        )
        stops = (
            db_session.query(HookSession)
            .filter(HookSession.agent_id == agent_id)
            .filter(HookSession.hook_event == "SubagentStop")
            .count()
        )
        assert stops == 3, "the SubagentStop rows did not persist"

        client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )

        db_session.refresh(row)
        assert row.tier != MemoryTier.raw
        assert row.tier == MemoryTier.working


class TestEverySessionOpenPathTriggersIt:
    """The trigger lives in the SERVICE. `open_session` has three callers and
    will have more; a trigger wired to the endpoint would work for one of
    them."""

    def test_calling_open_session_directly_consolidates_the_roster(
        self, db_session, human_project, make_agent
    ):
        agent_id = _roster_agent(db_session, make_agent, human_project)
        row = _raw_memory(db_session, agent_id, "opened without the router")
        db_session.flush()

        from app.models.dwb_session import DwbOpenMethod

        new_session, existing = dwb_svc.open_session(
            db_session, project_id=human_project, open_method=DwbOpenMethod.regex
        )
        assert existing is None and new_session is not None

        db_session.refresh(row)
        assert row.tier == MemoryTier.working, (
            "open_session itself did not trigger the pass - if the trigger has "
            "moved to the router, the two hook_tracking open paths are silent"
        )


# ---------------------------------------------------------------------------
# AC3 / AC4 / AC5
# ---------------------------------------------------------------------------


class TestStockProjectsAreUnaffected:
    """AC3."""

    def test_a_stock_project_opens_normally_and_runs_nothing(
        self, client, db_session, stock_project, make_agent
    ):
        agent_id = _roster_agent(db_session, make_agent, stock_project)
        row = _raw_memory(db_session, agent_id, "stock mode, left alone")
        db_session.commit()

        opened = client.post(
            "/api/sessions/open",
            json={"project_id": stock_project, "open_method": "slash"},
        )
        assert opened.status_code == 201, opened.text

        db_session.refresh(row)
        assert row.tier == MemoryTier.raw
        assert _pass_rows(db_session, stock_project) == [], (
            "a declined pass wrote a record claiming work it correctly did not do"
        )

    def test_the_declined_pass_says_why_rather_than_returning_an_empty_result(
        self, db_session, stock_project
    ):
        result = memory_consolidate.consolidate_project_roster(
            db_session, project_id=stock_project
        )
        assert result.ran is False
        assert result.reason == memory_consolidate.SKIPPED_NOT_HUMAN_MEMORY
        assert result.outcomes == []


class TestOneAgentFailingDoesNotTakeTheRestDownWithIt:
    """AC4 and AC5, and they are tested together because the second is only
    meaningful while the first holds."""

    @staticmethod
    def _poison(target_agent_id):
        """A `consolidate_agent` that throws for ONE agent and works for the
        rest, so a pass contains both outcomes at once."""
        real = memory_consolidate.consolidate_agent

        def fake(db, *, agent_id):
            if agent_id == target_agent_id:
                raise RuntimeError("deliberate consolidation failure")
            return real(db, agent_id=agent_id)

        return fake

    def test_the_session_still_opens_and_the_other_agents_still_move(
        self, client, db_session, human_project, make_agent, monkeypatch
    ):
        bad = _roster_agent(db_session, make_agent, human_project)
        good = _roster_agent(db_session, make_agent, human_project)
        bad_row = _raw_memory(db_session, bad, "will not be reached")
        good_row = _raw_memory(db_session, good, "must still be tiered")
        db_session.commit()

        monkeypatch.setattr(
            memory_consolidate, "consolidate_agent", self._poison(bad)
        )
        opened = client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        assert opened.status_code == 201, (
            "a consolidation failure failed the session open - constraint 1"
        )

        db_session.refresh(bad_row)
        db_session.refresh(good_row)
        assert good_row.tier == MemoryTier.working, (
            "one agent's failure stopped the roster"
        )
        assert bad_row.tier == MemoryTier.raw, (
            "the failed agent's work was not rolled back"
        )

    def test_a_failure_is_distinguishable_from_a_clean_pass(
        self, client, db_session, human_project, make_agent, monkeypatch
    ):
        """DWB-636 in one test: the broken outcome and the clean one, side by
        side, on the same project, asserted to DIFFER.

        Asserting only "a failure writes an error row" would pass against a
        path that writes an error row every time. Asserting only "a clean pass
        writes a pass row" would pass against a path that cannot tell the
        difference. The pair is the evidence.
        """
        bad = _roster_agent(db_session, make_agent, human_project)
        good = _roster_agent(db_session, make_agent, human_project)
        db_session.commit()

        # --- the FAILING pass ---
        monkeypatch.setattr(
            memory_consolidate, "consolidate_agent", self._poison(bad)
        )
        client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        session_id = dwb_svc.get_active_session(db_session, human_project).id
        closed = client.post(
            f"/api/sessions/{session_id}/close",
            json={
                "close_method": "slash",
                "close_reason": "explicit",
                "headline": "DWB-650 failure pass",
            },
        )
        # Asserted, not assumed. A 422 here leaves the session open, the second
        # open 409s, and the "clean pass left no record" assertion below fires
        # against working code - which is exactly what an earlier version of
        # this test did.
        assert closed.status_code == 200, closed.text

        failing_passes = _pass_rows(db_session, human_project)
        failing_errors = _error_rows(db_session, human_project)
        assert len(failing_passes) == 1
        assert '"agents_failed": 1' in failing_passes[0].details
        assert len(failing_errors) == 1
        assert str(bad) in failing_errors[0].message
        assert "deliberate consolidation failure" in failing_errors[0].message

        # --- the CLEAN pass, same project, nothing else changed ---
        monkeypatch.undo()
        reopened = client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        assert reopened.status_code == 201, reopened.text

        all_passes = _pass_rows(db_session, human_project)
        all_errors = _error_rows(db_session, human_project)
        clean = [p for p in all_passes if p.id != failing_passes[0].id]
        assert len(clean) == 1, "the clean pass left no record of having run"
        assert '"agents_failed": 0' in clean[0].details
        assert '"agents_attempted": 2' in clean[0].details
        assert len(all_errors) == 1, (
            "the clean pass wrote an error row, so the two are indistinguishable "
            "in the other direction"
        )
        assert good is not None  # named for readability of the fixture above

    def test_the_roster_result_counts_the_failure_rather_than_hiding_it(
        self, db_session, human_project, make_agent, monkeypatch
    ):
        bad = _roster_agent(db_session, make_agent, human_project)
        _roster_agent(db_session, make_agent, human_project)
        db_session.flush()

        monkeypatch.setattr(
            memory_consolidate, "consolidate_agent", self._poison(bad)
        )
        result = memory_consolidate.consolidate_project_roster(
            db_session, project_id=human_project
        )
        assert result.ran is True
        assert result.attempted == 2
        assert result.succeeded == 1
        assert [o.agent_id for o in result.failed] == [bad]
        assert "RuntimeError" in result.failed[0].error


class TestIdempotence:
    """Constraint 4. Inherited from `open_session`'s early return, and asserted
    rather than assumed."""

    def test_the_409_path_runs_no_second_pass(
        self, client, db_session, human_project, make_agent
    ):
        _roster_agent(db_session, make_agent, human_project)
        db_session.commit()

        first = client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )
        assert second.status_code == 409, second.text

        assert len(_pass_rows(db_session, human_project)) == 1


# ---------------------------------------------------------------------------
# AC6 and constraint 3
# ---------------------------------------------------------------------------


class TestTheMathIsNotCopied:
    """AC6. The pass changes which rows are scoreable; it must not change how
    they score."""

    def test_scores_and_bands_after_a_pass_equal_score_and_band_exactly(
        self, client, db_session, human_project, make_agent
    ):
        agent_id = _roster_agent(db_session, make_agent, human_project)
        _raw_memory(db_session, agent_id, "high", cost=MemoryCost.high)
        _raw_memory(db_session, agent_id, "untagged")
        db_session.commit()

        client.post(
            "/api/sessions/open",
            json={"project_id": human_project, "open_method": "slash"},
        )

        payload = client.get(f"/api/agents/{agent_id}/memory/scored").json()
        assert payload["computed"] is True
        entries = [e for e in payload["entries"] if e["scored"]]
        assert len(entries) == 2, "the pass did not make both rows scoreable"

        for entry in entries:
            memory = db_session.get(AgentMemory, entry["id"])
            gap = memory_score.sessions_since_reinforced(db_session, memory)
            expected = memory_score.score(memory.tier, gap)
            assert entry["score"] == expected
            assert entry["band"] == memory_score.band(expected)


class TestThePassIsStillNotARead:
    """Constraint 3, as a structural guard rather than one runtime test per
    path.

    Miles ruled that session start is not a read. The application has exactly
    two write sites for the counters that record a read - `memory_consult._fire`
    for `fired_count` and `journal.search_entries` for `retrieval_count` - and
    neither may be reachable from the roster pass. Fanning out over a roster
    multiplies the agents visited, not the functions reached, so the property
    should survive; "should" is what this class replaces.
    """

    @staticmethod
    def _call_graph():
        """A call graph over `app/services`, resolving module aliases.

        Not a general Python analyser. It handles the two call shapes this
        package actually uses - `module_alias.func(...)` and a bare `func(...)`
        defined in or imported into the same module - which is enough to walk
        this lane, and the positive controls below are what prove it reaches far
        enough to make the negative meaningful.
        """
        modules = {}
        for path in sorted(SERVICES_DIR.glob("*.py")):
            modules[path.stem] = ast.parse(path.read_text(), filename=str(path))

        # module -> {local name: (target module, target func or None)}
        aliases = {}
        functions = {}
        for name, tree in modules.items():
            local_alias = {}
            local_funcs = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "app.services":
                        for a in node.names:
                            local_alias[a.asname or a.name] = (a.name, None)
                    elif node.module.startswith("app.services."):
                        target = node.module.split(".")[-1]
                        for a in node.names:
                            local_alias[a.asname or a.name] = (target, a.name)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    local_funcs[node.name] = node
            aliases[name] = local_alias
            functions[name] = local_funcs
        return modules, aliases, functions

    @classmethod
    def _reachable(cls, start_module, start_func):
        modules, aliases, functions = cls._call_graph()
        seen = set()
        stack = [(start_module, start_func)]
        while stack:
            mod, func = stack.pop()
            if (mod, func) in seen:
                continue
            seen.add((mod, func))
            node = functions.get(mod, {}).get(func)
            if node is None:
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                target = call.func
                if isinstance(target, ast.Attribute) and isinstance(
                    target.value, ast.Name
                ):
                    alias = aliases.get(mod, {}).get(target.value.id)
                    if alias and alias[1] is None:
                        stack.append((alias[0], target.attr))
                elif isinstance(target, ast.Name):
                    imported = aliases.get(mod, {}).get(target.id)
                    if imported and imported[1]:
                        stack.append((imported[0], imported[1]))
                    elif target.id in functions.get(mod, {}):
                        stack.append((mod, target.id))
        return seen

    def test_no_counter_write_site_is_reachable_from_the_roster_pass(self):
        reached = self._reachable("memory_consolidate", "consolidate_project_roster")

        # POSITIVE CONTROLS FIRST. Without them this is an absence assertion
        # that passes loudest when the walker found nothing at all. The last one
        # is the load-bearing control: the walk must get INSIDE journal.py, so
        # that failing to reach `search_entries` is a real absence rather than
        # the walker stopping at the module boundary.
        assert ("memory_consolidate", "consolidate_agent") in reached
        assert ("memory_promote", "maybe_promote_scar") in reached
        assert ("memory_evict", "evict_working_memories") in reached
        assert ("memory_consolidate", "tier_raw_memories") in reached
        assert ("journal", "create_entry") in reached, (
            "the walk never entered journal.py, so the search_entries assertion "
            "below would pass without proving anything"
        )

        # THE NEGATIVE.
        assert ("journal", "search_entries") not in reached, (
            "the roster pass can reach the retrieval_count write site - session "
            "start would count as a READ"
        )
        assert ("memory_consult", "_fire") not in reached, (
            "the roster pass can reach the fired_count write site - session "
            "start would count as a READ"
        )

    def test_the_two_counter_write_sites_are_still_where_this_test_thinks(self):
        """The guard above names two functions. If a counter increment moves to
        a third, the guard keeps passing while the property it protects is
        gone, so the write sites are counted here rather than trusted."""
        sources = {
            p.stem: p.read_text() for p in SERVICES_DIR.glob("*.py")
        }
        writes = []
        for name, src in sources.items():
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg in (
                    "fired_count",
                    "retrieval_count",
                ):
                    holder = None
                    for fn in ast.walk(tree):
                        if isinstance(
                            fn, (ast.FunctionDef, ast.AsyncFunctionDef)
                        ) and fn.lineno <= node.value.lineno <= fn.end_lineno:
                            holder = fn.name
                    writes.append((name, holder, node.arg))
        assert sorted(writes) == sorted(
            [
                ("journal", "search_entries", "retrieval_count"),
                ("memory_consult", "_fire", "fired_count"),
            ]
        ), f"the counter write sites moved: {sorted(writes)}"


class TestNothingHasToRememberToRunIt:
    """The hard constraint, as close to testable as it gets.

    Miles: "this is programmatic. dwb sesh launch does this, no one has to
    remember." The behavioural half is covered by
    TestEverySessionOpenPathTriggersIt. This is the other half: the trigger must
    not be a thing a caller opts into, so `open_session` takes no flag that
    could be left off.
    """

    def test_open_session_has_no_parameter_that_disables_the_pass(self):
        tree = ast.parse((SERVICES_DIR / "dwb_session.py").read_text())
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "open_session"
        )
        params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
        # An ALLOWLIST OF NAMED MEMBERS, each admitted for a stated reason,
        # rather than a loosened rule. A new parameter has to be argued onto
        # this list by whoever adds it, which is the whole mechanism: the
        # question "does this one gate the pass?" gets asked exactly once per
        # parameter, by the person in a position to answer it.
        #
        #   db, project_id, opened_at, open_method, open_phrase
        #       the original five (DWB-650).
        #   open_transcript_key (DWB-682)
        #       the transcript entry the open came from, recorded so that
        #       entry can never open a second session. PURE DATA: it is
        #       assigned onto the row and read by nothing in this file. It
        #       cannot gate the consolidation pass, which runs unconditionally
        #       after the row is flushed, and leaving it off changes only
        #       whether the reopen guard has a key to match on later.
        assert params == [
            "db",
            "project_id",
            "opened_at",
            "open_method",
            "open_phrase",
            "open_transcript_key",
        ], (
            f"open_session grew a parameter: {params}. If one of these gates the "
            "consolidation pass, the trigger is now something a caller has to "
            "remember to ask for, which is what DWB-650 removed. Add it to the "
            "list above WITH A REASON, or make it not gate anything."
        )


class TestOpenTranscriptKeyCannotReachThePass:
    """DWB-682 earned `open_transcript_key` a place on the tripwire's
    allowlist above. THIS is the property that earned it, pinned so the
    widening cannot outlive the reason for it.

    THE TRIPWIRE ASKS A QUESTION IT CANNOT ANSWER ITSELF. It compares a
    parameter list, so it detects that `open_session` grew a parameter and
    then relies on a human to decide whether that parameter can switch the
    pass off. Widening it records the verdict; these two tests record the
    EVIDENCE, and they keep checking it on every run rather than once in a
    report.

    TWO INSTRUMENTS, AND THEY FAIL DIFFERENTLY ON PURPOSE. The first reads
    the source and proves the parameter is never consulted in a branch, so it
    is structurally incapable of choosing a return path. The second runs the
    function across a spread of values and proves the pass fired for every
    one. A structural proof cannot see a trigger that is reached but declines
    internally; a behavioural one cannot see a value nobody thought to try.
    Neither alone would do.
    """

    def _open_session_ast(self):
        tree = ast.parse((SERVICES_DIR / "dwb_session.py").read_text())
        return next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "open_session"
        )

    def test_the_parameter_is_never_read_in_a_branch(self):
        """It flows into the row constructor and nowhere else.

        `open_method` IS read in branches (the timestamp authority and the
        DWB-351 privacy null-out), which is exactly why this test is scoped
        to the ONE parameter whose claim is write-only rather than asserted
        over all of them. A blanket 'no parameter is ever read' would be
        false and would have to be weakened until it proved nothing.
        """
        fn = self._open_session_ast()

        # Every place the name is LOADED (read), anywhere in the body.
        loads = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Name)
            and n.id == "open_transcript_key"
            and isinstance(n.ctx, ast.Load)
        ]
        # POSITIVE CONTROL. A walk that matches nothing proves nothing, and
        # "zero reads" is also what a renamed or deleted parameter looks like.
        assert len(loads) == 1, (
            f"expected exactly one read of open_transcript_key, found "
            f"{len(loads)}. More than one means it is consulted somewhere "
            f"beyond the row constructor; zero means it is gone and this "
            f"test is no longer measuring anything."
        )

        # That single read must be the keyword VALUE in the DwbSession(...)
        # construction - not a condition, not a return expression.
        constructor_values = [
            kw.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "DwbSession"
            for kw in n.keywords
        ]
        assert loads[0] in constructor_values, (
            "open_transcript_key is read somewhere other than the DwbSession "
            "constructor. If it now influences control flow it can gate the "
            "consolidation pass, and its place on the DWB-650 allowlist is "
            "no longer earned."
        )

        # And belt-and-braces on the thing we actually care about: it appears
        # in no test position of any branch, and in no return.
        tests_and_returns = []
        for n in ast.walk(fn):
            if isinstance(n, (ast.If, ast.While, ast.IfExp)):
                tests_and_returns.append(n.test)
            elif isinstance(n, ast.Return) and n.value is not None:
                tests_and_returns.append(n.value)
        guarded = {
            name.id
            for branch in tests_and_returns
            for name in ast.walk(branch)
            if isinstance(name, ast.Name)
        }
        assert "open_transcript_key" not in guarded, (
            "open_transcript_key appears in a branch test or a return value"
        )

    @pytest.mark.parametrize("key", [
        None,                      # every non-transcript caller
        "u-some-entry-uuid",       # the normal case
        "",                        # empty string: falsy, the classic gate
        "/a/path.jsonl#idx:0",     # the fallback form
        "x" * 512,                 # the column's full width
    ])
    def test_the_pass_fires_whatever_the_key_is(
        self, db_session, human_project, make_agent, key
    ):
        """Behavioural half. The values are chosen to include the ones a
        gate would most plausibly key on - None and the empty string - rather
        than five spellings of the happy path.
        """
        agent_id = _roster_agent(db_session, make_agent, human_project)
        row = _raw_memory(db_session, agent_id, f"raw row for key={key!r}")
        db_session.flush()

        from app.models.dwb_session import DwbOpenMethod

        new_session, existing = dwb_svc.open_session(
            db_session,
            project_id=human_project,
            open_method=DwbOpenMethod.regex,
            open_transcript_key=key,
        )
        assert existing is None and new_session is not None
        assert new_session.open_transcript_key == key, (
            "the value did not reach the row, so this run says nothing about "
            "whether that value gates the pass"
        )

        db_session.refresh(row)
        assert row.tier == MemoryTier.working, (
            f"the consolidation pass did not run with "
            f"open_transcript_key={key!r}; the parameter gates the trigger "
            f"and does not belong on the DWB-650 allowlist"
        )
