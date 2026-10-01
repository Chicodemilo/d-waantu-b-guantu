# Path: tests/test_memory_reinforce_dwb621.py
# File: test_memory_reinforce_dwb621.py
# Created: 2026-10-01 (DWB-621)
# Purpose: Guard Miles's ruling that a RECALLED scar returns to full strength.
#          A genuine consultation sets last_reinforced_session_id to the active
#          DWB session, which the existing curve already scores 10. The half
#          that matters more: injection, session start, the dashboard and the
#          consolidation job must remain STRUCTURALLY incapable of reinforcing,
#          proven against a scar sitting at its resting floor.
# Caller: pytest
# Callees: app.services.memory_consult.consult_scars, app.services.memory_score,
#          app.services.memory_context, app.services.memory_mode,
#          app.services.memory_consolidate, ast
# Data In: factory projects/agents, agent_memories rows, dwb_sessions/hook_sessions
# Data Out: Assertions on the STORED last_reinforced_session_id and derived score
# Last Modified: 2026-10-01 (DWB-621)

"""DWB-621 acceptance.

THE DEFECT: `last_reinforced_session_id` had no writer anywhere in `app/`. One
read at memory_score.py:184, two docstrings, nothing else. So the decay clock
ran one way only and every scar walked down to its floor and stayed there for
the life of the install, however useful it kept proving.

THE FIX IS ONE FIELD ON A WRITE THAT ALREADY HAPPENS. `consult_scars` was
already the single write site for `fired_count`; it now sets the reinforcement
origin in the same UPDATE. The curve is untouched: `sessions_since_reinforced`
does COALESCE(last_reinforced, created), so moving the origin to the ACTIVE
session yields zero sessions elapsed, which the existing table already scores
10. A second scoring path would be a second mechanism for one outcome and the
two would drift.

WHY MOST OF THIS FILE IS ABOUT WHAT MUST *NOT* HAPPEN. DWB-612 deleted
`_fire_scars` so that injection could not fire a counter. The obvious
implementation of THIS ticket - reinforce wherever a scar is rendered - reads
as correct and is the exact failure, because it reintroduces that by a side
door. Miles's governing rule: a read is injection-shaped when it can be
satisfied with NO QUESTION in it. A scar in a spawn payload was handed over,
not recalled.

A NOTE ON ONE FALSE GREEN THIS FILE DELIBERATELY AVOIDS. `maybe_promote_scar`
retiers a scar to CORE at fired_count 3, and CORE scores 10 at every bucket.
A test that consulted repeatedly and then asserted "score is 10" would pass
against a completely broken reinforcement path, because the promotion alone
produces that number. Every scoring assertion here therefore also asserts the
tier is still `scar`, and the fixtures keep fired_count below the threshold.
That is the "does this distinguish the correct implementation from the
plausible wrong one" question, asked of this file's own assertions.
"""

import ast
import pathlib
from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.models.project import MemoryMode, Project
from app.services import memory_consolidate, memory_context, memory_mode
from app.services import memory_consult as svc
from app.services import memory_score

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

TERM = "zzdwb621onlyinthisrow"
BODY = f"a lesson about {TERM} that cost us a morning"

# 91+ elapsed sessions puts a scar in the open-ended last bucket, where the
# curve reads 6. That is the resting floor the ticket says it never leaves.
FLOOR_SESSIONS = 95
SCAR_FLOOR_SCORE = 6
FULL_STRENGTH = 10


def _elapse(db, *, project_id, agent_id, n, tag):
    """`n` CLOSED DWB sessions, each with a hook session for this agent.

    Real rows rather than a patched counter: the COALESCE and the INNER JOIN in
    `sessions_since_reinforced` are the parts that decide this ticket, and
    faking the gap would leave exactly those unexercised.
    """
    base = datetime.utcnow() - timedelta(days=400)
    sessions = [
        DwbSession(
            project_id=project_id,
            opened_at=base + timedelta(hours=i),
            closed_at=base + timedelta(hours=i, minutes=30),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
        )
        for i in range(n)
    ]
    db.add_all(sessions)
    db.flush()
    db.add_all(
        [
            HookSession(
                session_id=f"dwb621-{tag}-{agent_id}-{i}",
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=s.id,
                total_tokens=0,
            )
            for i, s in enumerate(sessions)
        ]
    )
    db.flush()
    return sessions


def _open_session(db, project_id):
    """The currently-happening session. Not closed, so it never counts itself
    as elapsed experience."""
    s = DwbSession(
        project_id=project_id,
        opened_at=datetime.utcnow(),
        closed_at=None,
        open_method=DwbOpenMethod.slash,
    )
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def floored(db_session, make_project, make_agent, tmp_path):
    """A scar at its resting floor on a human_memory project.

    Returns (memory_id, project_id, agent_id). The fixture ASSERTS the start
    state it claims, rather than leaving the reader to trust the arithmetic:
    a probe that drives a system into a start state proves that state in the
    probe, because a silently-failed setup makes every later result a
    confident measurement of the wrong thing.
    """
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"])
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()

    origin = _elapse(
        db_session, project_id=project["id"], agent_id=agent["id"], n=1, tag="origin"
    )[0]
    memory = AgentMemory(
        agent_id=agent["id"],
        tier=MemoryTier.scar,
        body=BODY,
        created_session_id=origin.id,
        last_reinforced_session_id=None,
        fired_count=0,
    )
    db_session.add(memory)
    db_session.flush()

    _elapse(
        db_session,
        project_id=project["id"],
        agent_id=agent["id"],
        n=FLOOR_SESSIONS,
        tag="decay",
    )

    gap = memory_score.sessions_since_reinforced(db_session, memory)
    assert gap >= 91, f"fixture did not reach the floor bucket: gap={gap}"
    assert memory_score.score(memory.tier, gap) == SCAR_FLOOR_SCORE
    assert memory.last_reinforced_session_id is None

    return memory.id, project["id"], agent["id"]


def _reread(db, memory_id):
    """Re-SELECT. Every assertion in this file is about what is STORED, not
    about an object the test is still holding."""
    db.expire_all()
    return db.get(AgentMemory, memory_id)


def _score_of(db, memory_id):
    row = _reread(db, memory_id)
    gap = memory_score.sessions_since_reinforced(db, row)
    if gap is None:
        return None, row
    return memory_score.score(row.tier, gap), row


class TestAConsultationReinforces:
    """ACCEPTANCE 1. These fail against the pre-DWB-621 code, where nothing
    ever wrote the field."""

    def test_consultation_sets_the_origin_to_the_active_session(
        self, db_session, floored
    ):
        memory_id, project_id, agent_id = floored
        active = _open_session(db_session, project_id)

        svc.consult_scars(db_session, agent_id=agent_id, term=TERM)

        assert _reread(db_session, memory_id).last_reinforced_session_id == active.id

    def test_a_floored_scar_returns_to_full_strength(self, db_session, floored):
        memory_id, project_id, agent_id = floored
        active = _open_session(db_session, project_id)

        svc.consult_scars(db_session, agent_id=agent_id, term=TERM)

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id == active.id
        assert memory_score.sessions_since_reinforced(db_session, row) == 0
        assert value == FULL_STRENGTH
        # The number is 10 for the RIGHT reason: still a scar scoring its top
        # bucket, not a row promoted to CORE, which scores 10 at every bucket.
        assert row.tier == MemoryTier.scar
        assert row.fired_count == 1

    def test_a_search_that_matches_nothing_reinforces_nothing(
        self, db_session, floored
    ):
        memory_id, project_id, agent_id = floored
        _open_session(db_session, project_id)

        svc.consult_scars(db_session, agent_id=agent_id, term="nothing matches this")

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert value == SCAR_FLOOR_SCORE

    def test_a_non_matching_sibling_is_not_reinforced(self, db_session, floored):
        """Only the rows that MATCH. A consultation is evidence about the scar
        it found, not about every scar the agent holds."""
        memory_id, project_id, agent_id = floored
        sibling = AgentMemory(
            agent_id=agent_id,
            tier=MemoryTier.scar,
            body="an unrelated lesson",
            created_session_id=_reread(db_session, memory_id).created_session_id,
            fired_count=0,
        )
        db_session.add(sibling)
        db_session.flush()
        _open_session(db_session, project_id)

        svc.consult_scars(db_session, agent_id=agent_id, term=TERM)

        assert _reread(db_session, memory_id).last_reinforced_session_id is not None
        assert _reread(db_session, sibling.id).last_reinforced_session_id is None


class TestNoActiveSession:
    """A consultation with no DWB session open must not DEMOTE the row.

    Writing NULL here would fall back through the COALESCE to
    `created_session_id`, which is older, so the row would come out of a
    consultation scoring LOWER than it went in. The dangerous case and the safe
    case have to answer differently, so the write is conditional on there being
    an origin to write.
    """

    def test_consultation_without_an_open_session_does_not_clear_the_origin(
        self, db_session, floored
    ):
        memory_id, project_id, agent_id = floored
        active = _open_session(db_session, project_id)
        svc.consult_scars(db_session, agent_id=agent_id, term=TERM)
        assert _reread(db_session, memory_id).last_reinforced_session_id == active.id

        # Close it, so there is no active session for the second consultation.
        active.closed_at = datetime.utcnow()
        active.close_method = DwbCloseMethod.regex
        db_session.flush()

        svc.consult_scars(db_session, agent_id=agent_id, term=TERM)

        row = _reread(db_session, memory_id)
        assert row.last_reinforced_session_id == active.id, (
            "a consultation with no open session must leave the existing origin "
            "alone; clearing it would score the row LOWER for having been used"
        )
        assert row.fired_count == 2, "the tally still counts the consultation"


class TestWhatMustNotReinforce:
    """ACCEPTANCE 2 and 3, and the half of this ticket that matters.

    These pass both before and after the fix, deliberately: they are the
    regression guard on the side door, not evidence the defect existed. Each
    drives a real path against a scar at its floor and asserts the floor held.
    """

    def test_spawn_injection_does_not_reinforce(self, db_session, floored):
        memory_id, project_id, agent_id = floored
        _open_session(db_session, project_id)
        project = db_session.get(Project, project_id)
        agent = project.agents[0] if getattr(project, "agents", None) else None

        from app.models.agent import Agent

        agent = db_session.get(Agent, agent_id)
        served = memory_mode.memory_full_for(
            project, "stock content", db=db_session, agent=agent
        )
        # Positive control: the injection really did render this scar, so the
        # assertion below is about a path that ran, not one that no-opped.
        assert TERM in served, served

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert value == SCAR_FLOOR_SCORE

    def test_assembling_session_context_does_not_reinforce(self, db_session, floored):
        memory_id, project_id, agent_id = floored
        _open_session(db_session, project_id)
        from app.models.agent import Agent

        assembled = memory_context.assemble_session_context(
            db_session, db_session.get(Agent, agent_id)
        )
        assert assembled and TERM in assembled, assembled

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert value == SCAR_FLOOR_SCORE

    def test_the_dashboard_read_does_not_reinforce(self, db_session, floored):
        memory_id, project_id, agent_id = floored
        _open_session(db_session, project_id)

        result = memory_score.scored_memory(db_session, agent_id=agent_id)
        assert result["computed"] is True, result
        assert any(e["id"] == memory_id for e in result["entries"]), result

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert value == SCAR_FLOOR_SCORE

    def test_the_consolidation_job_does_not_reinforce(self, db_session, floored):
        memory_id, project_id, agent_id = floored
        _open_session(db_session, project_id)

        memory_consolidate.consolidate_agent(db_session, agent_id=agent_id)

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert row.tier == MemoryTier.scar, "not promoted; fired_count is below 3"
        assert value == SCAR_FLOOR_SCORE

    def test_session_start_does_not_reinforce(self, client, db_session, floored):
        """The real hook endpoint, not a stand-in. SessionStart also runs the
        DWB-609 consolidation job, so this covers the composed path a live
        session actually takes.

        NO COMMIT HERE, DELIBERATELY. conftest's `client` and `db_session`
        share one session through the `get_db` override, so the endpoint
        already sees the fixture's uncommitted rows. An earlier draft committed
        to "make them visible" and thereby committed the harness's OUTER
        transaction, which teardown then could not roll back: rows leaked into
        the test database and the next test hung on them. Committing from a
        test reaches past its layer exactly the way a service calling
        db.rollback() does.
        """
        memory_id, project_id, agent_id = floored
        project = db_session.get(Project, project_id)

        r = client.post(
            "/api/hooks/session-start",
            json={
                "session_id": "dwb621-session-start-probe",
                "cwd": project.repo_path,
                "transcript_path": "",
            },
        )
        assert r.status_code == 200, r.text

        value, row = _score_of(db_session, memory_id)
        assert row.last_reinforced_session_id is None
        assert value == SCAR_FLOOR_SCORE


def _python_sources() -> list[pathlib.Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _is_none_literal(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _writes_of(field: str) -> list[tuple[str, int, bool]]:
    """Every place in app/ that WRITES `field`, as (path, line, clears_only).

    Same three shapes the fired_count guard already uses: attribute assignment,
    attribute augmented-assignment, or `field=` passed as a keyword to any
    call. The third element is the part this ticket needs and fired_count did
    not: whether the written value is the literal None.

    WHY THE EXTRA BIT, AND WHY NOT A TIGHTER COUNT. The first version of this
    guard asserted "exactly one write site" and went red on
    `project.py`'s FK cleanup, which NULLs this column when a project's
    dwb_sessions are deleted. That write is correct and must keep existing, so
    a bare count cannot separate the case the guard exists to prevent from a
    case it must allow. Tightening the count would have refused the legitimate
    write, which looks like rigour and makes the guard unusable; the fix is a
    signal that DIFFERS between the two. Reinforcement SETS an origin,
    cleanup CLEARS one, and a write of None can never move a scar back to full
    strength. So the guarded quantity is non-null writes.
    """
    sites: list[tuple[str, int, bool]] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(APP_DIR.parent))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr == field:
                        sites.append(
                            (rel, node.lineno, _is_none_literal(getattr(node, "value", None)))
                        )
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == field:
                        sites.append((rel, node.lineno, _is_none_literal(kw.value)))
    return sites


# Paths allowed to write this column WITHOUT reinforcing, each with the reason.
# An allowlist of named members beats a class-wide ban with a carve-out: this
# also catches the member someone would object to, where a loosened rule would
# permit the whole class. Entries are checked for staleness below, because an
# excuse naming something that no longer writes the field silently excuses
# nothing and the next thing to take that path inherits it.
CLEAR_ONLY_WRITERS = {
    "app/services/project.py": (
        "project delete NULLs the reference when the dwb_sessions it points at "
        "are deleted with the project. Clears an origin, can never set one."
    ),
}


class TestExactlyOneReinforcementWriteSite:
    """ACCEPTANCE 5, extended to the field this ticket adds. `fired_count`
    already has this guard; reinforcement needs the same one or the next
    well-meaning caller reinstates the side door DWB-612 closed."""

    def test_the_scan_can_see_the_identifier_at_all(self):
        """Positive control. A scanner whose pattern matches nothing passes
        every check it guards, loudly and greenly."""
        sources = _python_sources()
        assert len(sources) > 20, f"only scanned {len(sources)} files"
        mentions = [
            p
            for p in sources
            if "last_reinforced_session_id" in p.read_text(encoding="utf-8")
        ]
        assert len(mentions) >= 2, [str(m) for m in mentions]

    def test_exactly_one_site_can_set_an_origin_and_it_is_memory_consult(self):
        """The guarded quantity: writes that SET a value. Clearing writes are
        allowlisted by path below and cannot reinforce anything."""
        setters = [
            (p, line)
            for p, line, clears in _writes_of("last_reinforced_session_id")
            if not clears
        ]
        assert len(setters) == 1, (
            "exactly one site may SET last_reinforced_session_id, for the same "
            f"reason fired_count has one writer. Found: {setters}"
        )
        assert setters[0][0] == "app/services/memory_consult.py", setters

    def test_every_other_writer_is_allowlisted_and_only_clears(self):
        others = {
            p
            for p, _line, _clears in _writes_of("last_reinforced_session_id")
            if p != "app/services/memory_consult.py"
        }
        unexplained = others - set(CLEAR_ONLY_WRITERS)
        assert unexplained == set(), (
            "a new module writes the reinforcement origin with no recorded "
            f"reason: {sorted(unexplained)}"
        )
        for path, _line, clears in _writes_of("last_reinforced_session_id"):
            if path in CLEAR_ONLY_WRITERS:
                assert clears, (
                    f"{path} is allowlisted as clear-only but now writes a "
                    "non-null value, which would make it a reinforcement path"
                )

    def test_the_allowlist_has_no_stale_entries(self):
        """A guard must reject a STALE entry as well as a missing one. An
        excuse naming a module that no longer writes the field excuses nothing,
        and whatever next occupies that path inherits the exemption."""
        writers = {p for p, _line, _clears in _writes_of("last_reinforced_session_id")}
        stale = set(CLEAR_ONLY_WRITERS) - writers
        assert stale == set(), (
            f"allowlist names modules that no longer write the field: {sorted(stale)}"
        )

    def test_memory_score_module_contains_no_reinforcement_write(self):
        """memory_score.py is what injection and the dashboard both call. It
        must never become a write site again - that is the exact shape of the
        defect Miles ruled on for fired_count."""
        offenders = [
            p
            for p, _line, _clears in _writes_of("last_reinforced_session_id")
            if p == "app/services/memory_score.py"
        ]
        assert offenders == []

    def test_injection_and_dashboard_modules_contain_no_reinforcement_write(self):
        forbidden = {
            "app/services/memory_context.py",
            "app/services/memory_mode.py",
            "app/services/memory_consolidate.py",
        }
        offenders = [
            p
            for p, _line, _clears in _writes_of("last_reinforced_session_id")
            if p in forbidden
        ]
        assert offenders == [], (
            "these are the injection, seal and consolidation paths; "
            f"reinforcement must stay structurally out of reach of them: {offenders}"
        )
