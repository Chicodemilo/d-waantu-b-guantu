# Path: tests/test_topoff_journal_dwb612.py
# File: test_topoff_journal_dwb612.py
# Created: 2026-09-30 (DWB-612)
# Purpose: Guard both halves of top-off's firing pass - a top-off-triggered
#          journal search increments the matched entry's retrieval_count
#          exactly once per search (journal.py's single write site), and,
#          per Miles's 2026-09-30 ruling extending this ticket, the SAME pass
#          also consults scars via memory_consult.consult_scars, using the
#          SAME term, firing fired_count only on a match through that
#          module's single write site. No second increment path for either
#          counter is added here.
# Caller: pytest
# Callees: app/services/hook_tracking (handle_user_prompt, _topoff_journal_check,
#          _topoff_scar_check, _topoff_search_term), app/services/journal
#          (create_entry, for the fixture entry), app/models/agent_memory
#          (AgentMemory, MemoryTier, for the fixture scar)
# Data In: factory projects/agents, hook_sessions rows, JournalEntry rows,
#          AgentMemory rows, UserPromptSubmit payloads
# Data Out: Assertions on the hook response and the persisted retrieval_count /
#           fired_count
# Last Modified: 2026-09-30 (DWB-612: scar half added per Miles's ruling)

"""Tests for DWB-612.

Miles's model, the acceptance bar this file proves against: "during top-off,
if you are repeating a mistake you search the journal, and that search
increments the retrieval count." Before this ticket top-off touched neither
memory nor the journal at all (confirmed by the 2026-09-30 audit and by
test_topoff_dwb590.py, which has no journal fixture at all).

EXTENDED THE SAME DAY, after the DWB-603/610/612 collision: Miles ruled a
scar's `fired_count` only moves on a deliberate "have I made this error
before?" consultation outside normal startup, and that top-off should BE that
consultation - "same pass, same term" - rather than leave it as a surface
nobody calls. `TestScar*` below is the acceptance bar for that half.

This file does not re-test that either write site only increments and lives
where it claims to - test_journal_dwb587.py::TestTheCountHasOneWriter and
Stan's DWB-603 guard already own that, at the whole-app level, and re-running
the same proof here would only prove hook_tracking.py agrees with itself.
What this file owns is the NEW fact: something in the top-off path actually
CALLS both sites, at the right moment (when top-off fires, not every prompt),
with the SAME term that can really match either store, and does not call
either twice.
"""

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.hook_session import HookSession
from app.models.journal_entry import JournalEntry
from app.models.project import Project
from app.services import hook_tracking as svc
from app.services import journal as journal_svc

CWD = "/tmp/dwb612-repo"


@pytest.fixture
def topoff_project(db_session, make_project, tmp_path):
    project = make_project(repo_path=str(tmp_path))
    row = db_session.get(Project, project["id"])
    row.topoff_enabled = True
    row.topoff_interval = 3
    db_session.flush()
    return row


def _hook_session(db, *, project_id, agent_id=None, session_id="dwb612-sess"):
    row = HookSession(
        session_id=session_id,
        project_id=project_id,
        agent_id=agent_id,
        total_tokens=0,
    )
    db.add(row)
    db.flush()
    return row


def _prompt(db, project, *, text="just a normal prompt", session_id="dwb612-sess"):
    return svc.handle_user_prompt(
        db,
        {
            "prompt": text,
            "cwd": project.repo_path,
            "session_id": session_id,
            "hook_event_name": "UserPromptSubmit",
        },
    )


def _fire(db, project, *, text, session_id="dwb612-sess"):
    """Run the interval's worth of prompts and return the FIRING one's
    response - topoff_interval is 3 on the fixture project."""
    for _ in range(2):
        _prompt(db, project, text="filler", session_id=session_id)
    return _prompt(db, project, text=text, session_id=session_id)


def _scar(db, *, agent_id, body):
    row = AgentMemory(agent_id=agent_id, tier=MemoryTier.scar, body=body)
    db.add(row)
    db.flush()
    return row


class TestSearchRunsOnlyWhenTopoffFires:
    def test_non_firing_prompts_carry_no_journal_check(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        for _ in range(2):
            result = _prompt(db_session, topoff_project, text="a perfectly normal prompt")
            assert result["topoff"]["fired"] is False
            assert "journal_check" not in result["topoff"]
            assert "scar_check" not in result["topoff"]

    def test_the_firing_prompt_carries_a_journal_check(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="a prompt long enough to search")

        assert result["topoff"]["fired"] is True
        assert "journal_check" in result["topoff"]
        assert result["topoff"]["journal_check"]["searched"] is True

    def test_the_firing_prompt_carries_a_scar_check_too(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="a prompt long enough to search")

        assert "scar_check" in result["topoff"]
        assert result["topoff"]["scar_check"]["searched"] is True


class TestMatchIncrementsRetrievalCountExactlyOnce:
    def test_a_matching_entry_is_found_and_counted_once(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        # The match direction matters: search_entries matches entry.body LIKE
        # '%term%', and term is the (capped) PROMPT. So the prompt must be a
        # substring OF the entry, not the other way around - a short, exact
        # phrase the agent later re-types is the realistic "I've hit this
        # before" shape this is standing in for.
        entry = journal_svc.create_entry(
            db_session,
            agent_id=agent["id"],
            body=(
                "LESSON: the fcntl lock on conftest blocks a second pytest run "
                "and looks like a hang, not a crash."
            ),
        )
        db_session.commit()
        assert entry.retrieval_count == 0

        prompt_text = "the fcntl lock on conftest blocks a second pytest run"
        result = _fire(db_session, topoff_project, text=prompt_text)

        check = result["topoff"]["journal_check"]
        assert check["searched"] is True
        assert check["matched"] == 1
        assert check["entry_ids"] == [entry.id]

        db_session.refresh(entry)
        assert entry.retrieval_count == 1, "must increment exactly once per search"

    def test_firing_again_with_no_new_match_does_not_recount(
        self, db_session, make_agent, topoff_project
    ):
        """A second firing that does not match this entry must not touch its
        count - proving the increment tracks MATCHES, not firings."""
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        entry = journal_svc.create_entry(
            db_session,
            agent_id=agent["id"],
            body="a very specific past lesson recurs constantly in this codebase",
        )
        db_session.commit()

        _fire(db_session, topoff_project, text="a very specific past lesson recurs")
        db_session.refresh(entry)
        assert entry.retrieval_count == 1

        _fire(db_session, topoff_project, text="something unrelated entirely, twelve chars")
        db_session.refresh(entry)
        assert entry.retrieval_count == 1, "unrelated firing must not recount"

    def test_uses_the_journal_service_write_site_not_a_new_one(self):
        """Structural: DWB-612's code must not assign to `.retrieval_count`
        anywhere. test_journal_dwb587.py::TestTheCountHasOneWriter already
        proves app-wide there is exactly one write site and it is
        journal.py; this asserts hook_tracking.py's own source carries no
        write of its own, so the two guards cannot both be individually true
        while a write hides in a spot neither one happens to scan."""
        import ast
        import inspect

        source = inspect.getsource(svc)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    assert not (
                        isinstance(t, ast.Attribute) and t.attr == "retrieval_count"
                    ), f"hook_tracking.py writes retrieval_count directly at line {node.lineno}"
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    assert kw.arg != "retrieval_count", (
                        f"hook_tracking.py passes retrieval_count= at line {node.lineno}"
                    )


class TestScarMatchIncrementsFiredCountExactlyOnce:
    """The scar half, mirroring the journal class above. Same direction note
    applies: consult_scars matches `AgentMemory.body LIKE '%term%'`, term is
    the (capped) prompt, so the prompt must be a substring OF the scar body."""

    def test_a_matching_scar_is_found_and_fired_once(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            body="LESSON: never grep a transcript, parse it - a grep finds the "
            "conversation about a string, only parsing finds the string.",
        )
        db_session.commit()
        assert scar.fired_count == 0

        prompt_text = "never grep a transcript, parse it"
        result = _fire(db_session, topoff_project, text=prompt_text)

        check = result["topoff"]["scar_check"]
        assert check["searched"] is True
        assert check["matched"] == 1
        assert check["memory_ids"] == [scar.id]

        db_session.refresh(scar)
        assert scar.fired_count == 1, "must increment exactly once per search"

    def test_firing_again_with_no_new_match_does_not_refire(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            body="a very specific past mistake recurs constantly in this codebase",
        )
        db_session.commit()

        _fire(db_session, topoff_project, text="a very specific past mistake recurs")
        db_session.refresh(scar)
        assert scar.fired_count == 1

        _fire(db_session, topoff_project, text="something unrelated entirely, twelve chars")
        db_session.refresh(scar)
        assert scar.fired_count == 1, "unrelated firing must not refire"

    def test_uses_the_consult_service_write_site_not_a_new_one(self):
        """Structural sibling of the journal guard above: hook_tracking.py's
        own source must carry no write of `.fired_count` - that write site
        belongs to memory_consult.py alone (Stan's DWB-603 guard proves it
        app-wide)."""
        import ast
        import inspect

        source = inspect.getsource(svc)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    assert not (
                        isinstance(t, ast.Attribute) and t.attr == "fired_count"
                    ), f"hook_tracking.py writes fired_count directly at line {node.lineno}"
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    assert kw.arg != "fired_count", (
                        f"hook_tracking.py passes fired_count= at line {node.lineno}"
                    )


class TestSameTermDrivesBothChecks:
    """Miles's ruling was explicit: 'same pass, same term.' This is the test
    that would fail if journal and scar matching ever computed the term
    independently and drifted - a single scar+journal pair, each matching
    only a prefix of the firing prompt, must BOTH be found by one firing."""

    def test_one_firing_prompt_matches_both_a_journal_entry_and_a_scar(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        journal_entry = journal_svc.create_entry(
            db_session,
            agent_id=agent["id"],
            body="journal side: the fcntl lock blocks a second pytest run",
        )
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            body="scar side: the fcntl lock blocks a second pytest run",
        )
        db_session.commit()

        result = _fire(db_session, topoff_project, text="the fcntl lock blocks a second pytest run")

        assert result["topoff"]["journal_check"]["matched"] == 1
        assert result["topoff"]["journal_check"]["entry_ids"] == [journal_entry.id]
        assert result["topoff"]["scar_check"]["matched"] == 1
        assert result["topoff"]["scar_check"]["memory_ids"] == [scar.id]


class TestGuardedEdgeCases:
    """Never-raise contract: the hook must survive every degenerate input
    that reaches this code path."""

    def test_short_prompt_is_not_searched(self, db_session, make_agent, topoff_project):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="ok")

        check = result["topoff"]["journal_check"]
        assert check["searched"] is False
        assert check["reason"] == "prompt_too_short"

    def test_no_resolved_agent_is_handled_without_raising(
        self, db_session, topoff_project
    ):
        """A hook_sessions row with no agent_id yet (pending marker not
        claimed) must not crash the search."""
        _hook_session(db_session, project_id=topoff_project.id, agent_id=None)

        result = _fire(db_session, topoff_project, text="a prompt with no agent resolved")

        check = result["topoff"]["journal_check"]
        assert check["searched"] is False
        assert check["reason"] == "no_agent"

    def test_no_journal_entries_at_all_is_a_clean_zero_match(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="nothing in the journal matches this")

        check = result["topoff"]["journal_check"]
        assert check["searched"] is True
        assert check["matched"] == 0
        assert check["entry_ids"] == []

    def test_short_prompt_is_not_scar_searched_either(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="ok")

        check = result["topoff"]["scar_check"]
        assert check["searched"] is False
        assert check["reason"] == "prompt_too_short"

    def test_no_resolved_agent_is_handled_without_raising_on_the_scar_side(
        self, db_session, topoff_project
    ):
        _hook_session(db_session, project_id=topoff_project.id, agent_id=None)

        result = _fire(db_session, topoff_project, text="a prompt with no agent resolved")

        check = result["topoff"]["scar_check"]
        assert check["searched"] is False
        assert check["reason"] == "no_agent"

    def test_no_scars_at_all_is_a_clean_zero_match(
        self, db_session, make_agent, topoff_project
    ):
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])

        result = _fire(db_session, topoff_project, text="nothing in the scars matches this")

        check = result["topoff"]["scar_check"]
        assert check["searched"] is True
        assert check["matched"] == 0
        assert check["memory_ids"] == []

    def test_a_working_tier_memory_is_not_matched_by_scar_consult(
        self, db_session, make_agent, topoff_project
    ):
        """consult_scars is scoped to SCAR_FAMILY. A WORKING memory sharing
        the exact text must not be fired - that would reach past the tier
        boundary memory_scan.SCAR_FAMILY exists to enforce."""
        agent = make_agent(project_id=topoff_project.id)
        _hook_session(db_session, project_id=topoff_project.id, agent_id=agent["id"])
        working = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.working,
            body="a working-tier lesson that happens to share this exact phrase",
        )
        db_session.add(working)
        db_session.commit()

        result = _fire(db_session, topoff_project, text="a working-tier lesson that happens to share")

        check = result["topoff"]["scar_check"]
        assert check["matched"] == 0
        db_session.refresh(working)
        assert working.fired_count == 0


class TestIndependentOfMemoryMode:
    """Top-off's own independence ruling (DWB-590) must survive the journal
    AND scar wiring: neither new function may read memory_mode either."""

    def test_journal_check_source_never_reads_memory_mode(self):
        import inspect

        source = inspect.getsource(svc._topoff_journal_check)
        assert "memory_mode" not in source, source

    def test_scar_check_source_never_reads_memory_mode(self):
        import inspect

        source = inspect.getsource(svc._topoff_scar_check)
        assert "memory_mode" not in source, source
