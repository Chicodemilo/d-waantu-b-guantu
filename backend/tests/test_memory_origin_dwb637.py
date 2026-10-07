# Path: tests/test_memory_origin_dwb637.py
# File: test_memory_origin_dwb637.py
# Created: 2026-10-07 (DWB-637)
# Purpose: Guard the session-origin precondition - that no writer of
#          agent_memories can mint a row with no clock origin, that the two
#          caller-facing endpoints refuse per request and per decision, that
#          the refusal is recoverable, and that a WRITTEN row is READ BACK by
#          the thing that serves memory to an agent.
# Caller: pytest
# Callees: app.services.memory_origin, app.services.raw_memory,
#          app.services.memory_decide, app.services.memory_promote,
#          app.services.memory_mode
# Data In: factory projects/agents, a real memory.md on disk, DWB sessions
# Data Out: Assertions on status codes, on persisted rows, and on served text
# Last Modified: 2026-10-07 (DWB-637)

"""DWB-637 acceptance: an unscoreable row cannot be written.

THE BUG, SO A READER DOES NOT HAVE TO RE-DERIVE IT. `agent_memories` rows are
scored from `COALESCE(last_reinforced_session_id, created_session_id)`. With
both NULL there is no origin: `memory_score.sessions_since_reinforced` returns
None, the row comes back `scored: false`, `memory_context` filters on band so
it lands in no section, and `memory_mode.memory_full_for` serves the sealed
pointer instead. The row exists, counts in a row count, and never reaches an
agent. 612 rows across three occurrences.

WHY THE OBVIOUS TEST IS THE ONE THAT MISSED ALL THREE. "Assert the row was
written" passes in every one of those outages. The row WAS written. So the
load-bearing test in this file is `TestItIsActuallyReadBack`, which drives the
real spawn-prepare path and asserts the lesson comes back out - storage proves
nothing about delivery, and delivery is the only property any of this has.

THREE CLASSES HERE, AND THEY FAIL INDEPENDENTLY:

1. The REFUSALS (criteria 1 and 2), each asserted against its own opposite in
   the same test, because "everything is refused" passes every one-sided
   assertion exactly as "everything is accepted" did.
2. The WRITE-SITE ENUMERATION, discovered from source rather than hand-listed,
   so a fourth writer of `agent_memories` fails this file on the day it is
   written instead of on the day someone notices an empty context. The ticket
   named two writers; there were three.
3. The READ-BACK, end to end.
"""

import ast
import pathlib
from datetime import datetime, timezone

import pytest

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.memory_transition import MemoryTransition, TransitionState
from app.models.project import Project
from app.services import memory_mode as seal_svc
from app.services import memory_origin, memory_promote, raw_memory

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# Every function under app/ that CONSTRUCTS an AgentMemory, with why each one
# is safe. Hand-written on purpose and compared against a set discovered from
# source below: the discovery catches a new writer appearing, this list is what
# makes the failure legible instead of a bare count mismatch.
KNOWN_WRITE_SITES = {
    "services/raw_memory.py::append_raw_memory": "refuses; caller-facing 400",
    "services/memory_decide.py::decide": "refuses; caller-facing 400",
    "services/memory_promote.py::promote_to_core": "refuses; caller defers first",
}


def _open_session(db, project_id):
    row = DwbSession(
        project_id=project_id,
        open_method=DwbOpenMethod.slash,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def _give_agent_memory(repo_path, prefix, agent_name, body):
    """A real stock memory.md where the DWB-594 enumerator looks."""
    path = (
        pathlib.Path(repo_path) / ".dwb" / "memory" / prefix / agent_name / "memory.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


LESSON = "cmp -s, never diff: the alias returns rc=0 for different tracked files"


@pytest.fixture
def adopting(client, db_session, make_project, make_agent, tmp_path):
    """A project mid-adoption with one candidate, and an open session.

    Returns (project_id, agent_id, session, transitions).
    """
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"])
    _give_agent_memory(
        tmp_path, project["prefix"], agent["name"], f"## Lesson\n{LESSON}\n"
    )
    session = _open_session(db_session, project["id"])

    r = client.patch(
        f"/api/projects/{project['id']}",
        json={"memory_mode": "adopting", "memory_mode_confirmed": True},
    )
    assert r.status_code == 200, r.text

    rows = (
        db_session.query(MemoryTransition)
        .filter(MemoryTransition.project_id == project["id"])
        .all()
    )
    # The probe asserts its own start state: a fixture that enumerated nothing
    # would let every test below pass by never reaching a decision at all.
    assert rows, "fixture produced no transition rows; the tests below are vacuous"
    return project["id"], agent["id"], session, rows


class TestTheRawWriteRefuses:
    """Criterion 1, asserted against its own opposite."""

    def test_refused_without_a_session_and_accepted_with_one(
        self, client, db_session, make_project, make_agent
    ):
        """Both cases in one test, because that is the only shape that catches
        a guard answering the same way for the safe and the dangerous case.

        Two projects, because the single-active session invariant is a
        per-project UNIQUE index: one project cannot be in both states at once.
        """
        closed = make_project()
        closed_agent = make_agent(project_id=closed["id"])
        opened = make_project()
        opened_agent = make_agent(project_id=opened["id"])
        session = _open_session(db_session, opened["id"])

        refused = client.post(
            f"/api/agents/{closed_agent['id']}/memories", json={"body": LESSON}
        )
        accepted = client.post(
            f"/api/agents/{opened_agent['id']}/memories", json={"body": LESSON}
        )

        assert (refused.status_code, accepted.status_code) == (400, 201), (
            refused.text,
            accepted.text,
        )
        assert accepted.json()["created_session_id"] == session.id

    def test_the_refusal_names_the_reason_and_the_fix(
        self, client, make_project, make_agent
    ):
        """A 400 alone is not the criterion. A 400 for an unrelated reason
        reads identically to the caller and sends them looking in the wrong
        place, which is how a recoverable refusal becomes a lost lesson."""
        project = make_project()
        agent = make_agent(project_id=project["id"])
        detail = client.post(
            f"/api/agents/{agent['id']}/memories", json={"body": LESSON}
        ).json()["detail"]

        assert "no open DWB session" in detail  # the reason
        assert "cannot be scored" in detail  # why that matters
        assert "/dwb-open" in detail  # the route, for whoever can use it
        assert "/api/sessions/open" in detail
        assert "Nothing was written" in detail  # what became of the lesson

        # THE FIX LINE MUST NOT TELL THE READER TO DO A TL-ONLY ACT. Session
        # lifecycle is the TL's; a worker is the agent most likely to hit this
        # refusal and is not permitted to open one. An imperative here either
        # gets ignored, which teaches workers to skim refusals, or gets
        # followed. Asserted on the phrasing because the bug was the phrasing.
        assert "is not yours to do" in detail, (
            "the fix line assumes the reader may open a session; it must be "
            "conditional, because the caller most likely to be refused cannot"
        )
        assert "tell your team lead" in detail
        assert "Open a session first" not in detail, (
            "the old imperative is back: it instructs a blocked worker to "
            "perform a TL-only action"
        )


class TestTheDecisionRefusesPerDecision:
    """Criterion 2. The half the BEGIN-edge guard structurally cannot cover."""

    def test_a_session_closing_mid_adoption_stops_the_run(
        self, client, db_session, adopting
    ):
        """THE SHAPE OF THE OUTAGE, reproduced and then refused.

        The BEGIN guard runs ONCE, at the mode flip, and passed here - the
        fixture opened a session before adopting. The stamp runs PER DECISION.
        So the dangerous state is reached AFTER the only guard that existed,
        and every remaining row went back to NULL with nothing re-checking.
        """
        _project_id, _agent_id, session, rows = adopting
        assert len(rows) >= 1

        # The first decision, with the session still open: it lands.
        first = client.post(
            f"/api/memory-transitions/{rows[0].id}/decide",
            json={"tier": "working", "decided_by": "test"},
        )
        assert first.status_code == 200, first.text

        # Now the session closes mid-run, which is the whole scenario.
        db_session.get(DwbSession, session.id).closed_at = datetime.now(timezone.utc)
        db_session.flush()

        again = client.post(
            f"/api/memory-transitions/{rows[0].id}/decide",
            json={"tier": "working", "decided_by": "test"},
        )
        # Already decided, so this row answers for a different reason. The
        # assertion that matters is on a row that has NOT been decided, which
        # the next test covers; this one only pins that a second decision on a
        # terminal row is still refused for its own reason rather than being
        # masked by the new one.
        assert again.status_code == 400

    def test_an_undecided_entry_is_refused_and_stays_decidable(
        self, client, db_session, adopting
    ):
        """A refusal must leave the entry re-decidable. A guard that strands a
        half-judged run is worse than the bug: the NULL origins were at least
        recoverable by a backfill, where a transition row stuck in a terminal
        state with no memory behind it is not."""
        _project_id, _agent_id, session, rows = adopting
        row = rows[0]

        db_session.get(DwbSession, session.id).closed_at = datetime.now(timezone.utc)
        db_session.flush()

        r = client.post(
            f"/api/memory-transitions/{row.id}/decide",
            json={"tier": "working", "decided_by": "test"},
        )
        assert r.status_code == 400, r.text
        assert "no open DWB session" in r.json()["detail"]

        db_session.expire_all()
        after = db_session.get(MemoryTransition, row.id)
        assert after.state == TransitionState.pending, (
            "a refused decision left the entry in a terminal state; the run "
            "cannot be resumed and the lesson is unreachable"
        )
        assert after.target_memory_id is None
        assert after.decided_tier is None

    def test_a_refused_decision_writes_no_memory_row(
        self, client, db_session, adopting
    ):
        """Against a SELECT, not inferred from the status code. The bug class
        is a row that exists and cannot be reached, and a 400 returned after a
        flush would reproduce it exactly."""
        _project_id, agent_id, session, rows = adopting
        db_session.get(DwbSession, session.id).closed_at = datetime.now(timezone.utc)
        db_session.flush()

        client.post(
            f"/api/memory-transitions/{rows[0].id}/decide",
            json={"tier": "scar", "decided_by": "test"},
        )
        db_session.expire_all()
        assert (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent_id)
            .all()
            == []
        )

    def test_a_skip_is_refused_too(self, client, db_session, adopting):
        """The sub-decision, pinned so it is a choice rather than an oversight.

        A skip writes a journal entry, which is reachable by search whatever
        its origin, so a skip loses nothing on its own. It is refused anyway:
        allowing skips while writes are refused lets a run reach its end with
        its keepers rejected and its noise recorded, and fire the cutover on
        that - a run that reads as finished and is not.
        """
        _project_id, _agent_id, session, rows = adopting
        db_session.get(DwbSession, session.id).closed_at = datetime.now(timezone.utc)
        db_session.flush()

        r = client.post(
            f"/api/memory-transitions/{rows[0].id}/decide",
            json={"tier": None, "decided_by": "test"},
        )
        assert r.status_code == 400, r.text
        assert "no open DWB session" in r.json()["detail"]

    def test_the_run_resumes_once_a_session_is_open_again(
        self, client, db_session, adopting
    ):
        """The refusal's own claim: send the request again, unchanged."""
        project_id, _agent_id, session, rows = adopting
        db_session.get(DwbSession, session.id).closed_at = datetime.now(timezone.utc)
        db_session.flush()

        payload = {"tier": "working", "decided_by": "test"}
        assert (
            client.post(
                f"/api/memory-transitions/{rows[0].id}/decide", json=payload
            ).status_code
            == 400
        )

        reopened = _open_session(db_session, project_id)
        r = client.post(f"/api/memory-transitions/{rows[0].id}/decide", json=payload)
        assert r.status_code == 200, r.text

        db_session.expire_all()
        written = db_session.get(
            AgentMemory, db_session.get(MemoryTransition, rows[0].id).target_memory_id
        )
        assert written.created_session_id == reopened.id


class TestTheBackgroundWriterDefers:
    """The third writer, which the ticket did not name.

    `memory_promote.promote_to_core` minted CORE rows with no origin at all -
    not a fallback, no attempt. CORE is the worst tier to lose: its curve scores
    10 in every bucket, so it is the one memory that should never be missing.
    """

    def test_journal_promotion_is_deferred_with_no_session_and_lands_with_one(
        self, db_session, make_project, make_agent
    ):
        """Both halves, because "deferred" alone passes against a promotion
        that never works at all."""
        from app.services import journal as journal_svc

        project = make_project()
        agent = make_agent(project_id=project["id"])
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="a story reached for", tags=["p637"]
        )
        for _ in range(journal_svc.PROMOTION_THRESHOLD):
            journal_svc.search_entries(db_session, agent_id=agent["id"], tags=["p637"])
        assert entry.retrieval_count >= journal_svc.PROMOTION_THRESHOLD

        deferred = memory_promote.promote_journal_candidates(
            db_session, agent_id=agent["id"]
        )
        assert deferred == []
        # Deferred, not consumed: the journal entry is untouched, so the next
        # pass with a session proposes it again. That is the whole reason this
        # path defers rather than raising.
        db_session.expire_all()
        assert db_session.query(AgentMemory).filter(
            AgentMemory.source_journal_id == entry.id
        ).all() == []

        session = _open_session(db_session, project["id"])
        created = memory_promote.promote_journal_candidates(
            db_session, agent_id=agent["id"]
        )
        assert len(created) == 1
        assert created[0].tier == MemoryTier.core
        assert created[0].created_session_id == session.id

    def test_the_write_site_itself_still_refuses(
        self, db_session, make_project, make_agent
    ):
        """The deferral above is the CALLER's politeness. The write site is the
        guard, and it has to hold for a future caller that does not know to
        check - which is precisely how this writer got into this state."""
        project = make_project()
        agent = make_agent(project_id=project["id"])
        with pytest.raises(memory_origin.MemoryOriginMissing):
            memory_promote.promote_to_core(
                db_session, agent_id=agent["id"], body="minted with no clock"
            )


class TestEveryWriteSiteIsCovered:
    """Discovery by pattern, with the pattern's coverage asserted.

    A hand-written list of writers is a list that the next writer is not on.
    This walks `app/` for AgentMemory constructions and compares what it finds
    against what this file claims to know about, so adding a fourth writer
    fails here rather than six weeks later in somebody's empty context.
    """

    @staticmethod
    def _discovered() -> dict[str, str]:
        found: dict[str, str] = {}
        for path in sorted(APP_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "AgentMemory"
                    ):
                        key = f"{path.relative_to(APP_DIR)}::{node.name}"
                        found[key] = str(inner.lineno)
        return found

    def test_the_scan_finds_something(self):
        """The positive control. A scan that matched nothing would make the
        comparison below pass perfectly and prove nothing at all - an empty set
        equals an empty set, and a glob that silently stops matching is the
        single most common way a source guard dies."""
        assert self._discovered(), (
            "the AgentMemory construction scan found no write sites; the "
            "pattern or the path is wrong, and the check below is vacuous"
        )

    def test_no_unknown_writer_of_agent_memories_exists(self):
        discovered = set(self._discovered())
        known = set(KNOWN_WRITE_SITES)
        assert discovered == known, (
            "the set of functions constructing AgentMemory has changed.\n"
            f"  new: {sorted(discovered - known)}\n"
            f"  gone: {sorted(known - discovered)}\n"
            "Every writer must resolve its clock origin through "
            "app/services/memory_origin.py - require_session_origin for a "
            "caller-facing write, deferrable_session_origin for a background "
            "pass - and must then be added to KNOWN_WRITE_SITES with which of "
            "the two it uses. A row written without an origin cannot be scored "
            "and never reaches an agent."
        )


class TestItIsActuallyReadBack:
    """CRITERION 6, AND THE ONLY TEST HERE THAT WOULD HAVE CAUGHT THE OUTAGES.

    Every other assertion in this file is about rows and status codes. All three
    occurrences had correct rows and 200s. This drives `memory_mode.memory_full_for`
    - the real spawn-prepare path - and asserts the adopted lesson comes back out
    of it rather than the sealed pointer.
    """

    def test_an_adopted_lesson_is_served_at_spawn(self, client, db_session, adopting):
        project_id, agent_id, _session, rows = adopting

        for row in rows:
            r = client.post(
                f"/api/memory-transitions/{row.id}/decide",
                json={"tier": "scar", "decided_by": "test"},
            )
            assert r.status_code == 200, r.text

        db_session.expire_all()
        served = seal_svc.memory_full_for(
            db_session.get(Project, project_id),
            "STOCK CONTENT MUST NEVER BE SERVED",
            db=db_session,
            agent=db_session.get(Agent, agent_id),
        )

        assert served != seal_svc.STOCK_MEMORY_SEALED_POINTER, (
            "adopted memory came back as the sealed pointer: the rows exist "
            "but cannot be scored, so nothing will ever reach an agent"
        )
        assert LESSON in served, (
            "the store served something, but not the lesson that was adopted"
        )
        assert "STOCK CONTENT MUST NEVER BE SERVED" not in served


class TestNoExistingRowIsModified:
    """Criterion 7. This ticket is guards, not data."""

    def test_a_row_with_a_null_origin_is_left_exactly_as_it_was(
        self, client, db_session, make_project, make_agent
    ):
        """The 216 NULL rows on IND are Barry's backfill, not this ticket's.

        A guard that quietly repaired what it found would make the backfill's
        before/after numbers lie, and would hide how many rows were affected.
        """
        project = make_project()
        agent = make_agent(project_id=project["id"])
        legacy = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.scar,
            body="written before the guard existed",
            created_session_id=None,
        )
        db_session.add(legacy)
        db_session.flush()
        legacy_id = legacy.id

        # Something happens on this project: a session opens, a write lands.
        _open_session(db_session, project["id"])
        assert (
            client.post(
                f"/api/agents/{agent['id']}/memories", json={"body": "a new lesson"}
            ).status_code
            == 201
        )

        db_session.expire_all()
        after = db_session.get(AgentMemory, legacy_id)
        assert after is not None, "the guard deleted a pre-existing row"
        assert after.created_session_id is None, (
            "the guard back-stamped an existing row; this ticket does not touch "
            "data, and a silent repair would corrupt the backfill's own count"
        )
        assert after.body == "written before the guard existed"


class TestTheNamedSuccessStateIsGone:
    """Criterion 4."""

    def test_raw_memory_has_no_none_open_outcome(self):
        assert not hasattr(raw_memory, "SESSION_NONE_OPEN"), (
            "SESSION_NONE_OPEN named a SUCCESSFUL write whose row had no clock "
            "origin. A name for a bad state sitting in the success path reads "
            "as a supported mode and the next writer reaches for it."
        )
        assert raw_memory.SESSION_OPEN == "open"
