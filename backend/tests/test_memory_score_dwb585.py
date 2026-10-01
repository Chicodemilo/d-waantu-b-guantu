# Path: tests/test_memory_score_dwb585.py
# File: test_memory_score_dwb585.py
# Created: 2026-09-29 (DWB-585)
# Purpose: Guard the DERIVED memory score - the whole section 3 table, both
#          floors, the load-bearing COALESCE on the session gap, the candidate
#          lists coming from the endpoint, and the score never being stored.
# Caller: pytest
# Callees: app/services/memory_score, app/routers/agents, ast
# Data In: factory agents/projects, agent_memories rows, dwb/hook sessions
# Data Out: Assertions on scores, bands, lists and write sites
# Last Modified: 2026-09-29 (DWB-585)

"""Tests for the derived memory score.

Four groups, and each guards a different way this ticket can be built wrong.

`TestScoreCurve` walks the whole spec section 3 table. It is exhaustive rather
than sampled because the curve is transcribed data, and a transcription error
is exactly the kind of bug a spot-check misses.

`TestFloors` isolates the two floors that are NOT functions of sessions. The
decay function must never return 0: WORKING bottoms at 1 and context-bound
scars bottom at 6, and 0 is set by consolidation or the SCAN. Implementing the
decay to 0 is the single easiest way to get this ticket wrong, and it would
pass tests written from the same misreading, so these assert the negative.

`TestSessionGap` guards the COALESCE. Its central test uses a memory that has
NEVER been reinforced, which is the fixture shape under which the bug is
invisible, and it fails if the COALESCE is removed.

`TestEndpoint` proves the candidate lists come from code and that "no
candidates" is distinguishable from "not computed".
"""

import ast
import inspect
import textwrap

import pytest
from sqlalchemy import text

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_score as svc

# The spec section 3 table, transcribed a SECOND time, independently of the
# service's own copy. A test that imports the table it is checking proves only
# that the code equals itself. Columns: this session | 1-5 | 6-14 | 15-30 |
# 31-90 | 90+.
SPEC_TABLE = {
    "core": (10, 10, 10, 10, 10, 10),
    # DWB-611: scar_context_bound collapsed into scar - it carried the
    # identical tuple even before the collapse, so there is nothing left to
    # transcribe a second time.
    "scar": (10, 9, 8, 7, 6, 6),
    "working": (10, 8, 6, 4, 2, 1),
}

# One representative session count from inside each bucket, plus the boundary
# on each side, so an off-by-one in the bucket edges fails rather than hiding
# between the samples.
BUCKET_SAMPLES = (
    (0, 0),
    (1, 1), (3, 1), (5, 1),
    (6, 2), (10, 2), (14, 2),
    (15, 3), (22, 3), (30, 3),
    (31, 4), (60, 4), (90, 4),
    (91, 5), (200, 5), (10_000, 5),
)


class TestScoreCurve:
    """The whole of spec section 3, for every tier and every bucket."""

    @pytest.mark.parametrize("sessions,bucket", BUCKET_SAMPLES)
    @pytest.mark.parametrize("tier_name", sorted(SPEC_TABLE))
    def test_curve_matches_the_spec_table(self, tier_name, sessions, bucket):
        tier = MemoryTier(tier_name)
        assert svc.score(tier, sessions) == SPEC_TABLE[tier_name][bucket]

    def test_core_never_moves_even_after_200_sessions(self):
        """Acceptance 1, named explicitly because CORE is the tier whose whole
        point is that it does not decay. 10 forever."""
        for sessions in (0, 1, 5, 14, 30, 90, 91, 200, 5_000):
            assert svc.score(MemoryTier.core, sessions) == 10

    def test_raw_has_no_score_and_says_so(self):
        """`raw` is untiered (spec section 4). It raises rather than returning
        a default, so a caller has to handle it instead of silently scoring an
        unjudged row."""
        with pytest.raises(ValueError, match="untiered"):
            svc.score(MemoryTier.raw, 0)

    def test_negative_sessions_are_rejected(self):
        with pytest.raises(ValueError):
            svc.score(MemoryTier.working, -1)

    def test_bucket_90_belongs_to_the_lower_bucket(self):
        """90 appears in BOTH '31-90' and '90+' in the spec table. Read as: 90
        closes the lower bucket, 91 opens the upper. It only changes an answer
        for WORKING, which is why it is asserted rather than assumed."""
        assert svc.score(MemoryTier.working, 90) == 2
        assert svc.score(MemoryTier.working, 91) == 1

    def test_curve_is_monotonically_non_increasing(self):
        """A score may never climb with more elapsed sessions. Reinforcement is
        the only thing that raises a score, and it does so by moving the
        ORIGIN, not by bending this curve."""
        for tier_name in SPEC_TABLE:
            tier = MemoryTier(tier_name)
            values = [svc.score(tier, n) for n in range(0, 200)]
            assert all(b <= a for a, b in zip(values, values[1:])), tier_name


class TestFloors:
    """The two floors that are NOT functions of sessions."""

    def test_decay_never_returns_zero_for_any_tier(self):
        """Per the spec amendment: 'The arithmetic floors at 1. Zero is not a
        computed score, it is an eviction state.' Nothing this function returns
        may be 0, at any session count, for any tier."""
        for tier_name in SPEC_TABLE:
            tier = MemoryTier(tier_name)
            for sessions in range(0, 500):
                assert svc.score(tier, sessions) >= svc.MIN_DERIVED_SCORE

    def test_working_bottoms_at_one_not_zero(self):
        assert svc.score(MemoryTier.working, 10_000) == 1

    def test_scar_bottoms_at_six_by_decay(self):
        """It reaches 0 only by STEP, when the SCAN finds the context dead
        (spec section 2's context-bound case - DWB-611 collapsed the tier
        that used to name this separately, but every scar is context-bound
        now, so the same resting behaviour applies to the one tier there is).
        Decay alone must never take it below its resting place."""
        for sessions in (90, 91, 500, 10_000):
            assert svc.score(MemoryTier.scar, sessions) == 6

    def test_scar_rests_at_six(self):
        assert svc.score(MemoryTier.scar, 10_000) == 6


class TestBands:
    """Spec section 3, 'What the score does'. Without this the number is
    decoration; with it, consolidation is sorting rather than judgement."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (10, svc.BAND_FULL_TEXT),
            (9, svc.BAND_FULL_TEXT),
            (8, svc.BAND_FULL_TEXT),
            (7, svc.BAND_COMPRESSED),
            (6, svc.BAND_COMPRESSED),
            (5, svc.BAND_COMPRESSED),
            (4, svc.BAND_DEMOTION_CANDIDATE),
            (3, svc.BAND_DEMOTION_CANDIDATE),
            (2, svc.BAND_DEMOTION_CANDIDATE),
            (1, svc.BAND_LAST_CONSOLIDATION),
        ],
    )
    def test_band_boundaries(self, value, expected):
        assert svc.band(value) == expected


class TestScoreIsNeverStored:
    """Acceptance 3, both halves: the column does not exist, and nothing
    anywhere tries to write one."""

    def test_no_score_or_band_column_on_the_model(self):
        present = {"score", "band"} & set(AgentMemory.__table__.columns.keys())
        assert present == set(), (
            f"agent_memories has grown {sorted(present)}. The score is DERIVED "
            "at read time from (tier, sessions_since_reinforced) and must never "
            "be persisted."
        )

    def test_nothing_assigns_a_score_attribute_on_a_memory(self):
        """AST rather than grep, copying the DWB-581 pattern, for the reason
        that ticket found: a source-string search breaks the moment a COMMENT
        quotes the thing it is looking for, and this module's comments discuss
        `score` constantly.

        Walks every assignment in the scoring service and the raw-memory
        writer, the two modules that touch AgentMemory rows, and fails if any
        of them assigns `.score` or `.band` on anything.
        """
        from app.services import raw_memory

        for module in (svc, raw_memory):
            tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in ("score", "band"), (
                            f"{module.__name__} assigns .{target.attr}; the score "
                            "is derived and must not be written"
                        )

    def test_no_score_keyword_passed_to_the_memory_constructor(self):
        """The other shape the same bug takes: AgentMemory(score=...) rather
        than row.score = ... . Both are writes; only one is an attribute
        assignment, so the test above would miss this one entirely.
        """
        from app.services import raw_memory

        for module in (svc, raw_memory):
            tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func_name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if func_name != "AgentMemory":
                    continue
                passed = {kw.arg for kw in node.keywords}
                assert not (passed & {"score", "band"}), (
                    f"{module.__name__} passes a score/band to AgentMemory()"
                )


# ---------------------------------------------------------------------------
# DB-backed helpers.
# ---------------------------------------------------------------------------

def _closed_session(db, project_id, *, hours_ago=1):
    """A CLOSED DWB session. Only closed sessions tick the decay clock: an open
    session is the one currently happening, and it becomes experience when it
    ends."""
    from datetime import datetime, timedelta

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


def _open_session(db, project_id):
    from datetime import datetime

    from app.models.dwb_session import DwbOpenMethod, DwbSession

    s = DwbSession(
        project_id=project_id, opened_at=datetime.utcnow(), open_method=DwbOpenMethod.regex
    )
    db.add(s)
    db.flush()
    return s


def _hook_session(db, *, agent_id, project_id, dwb_session_id, tag):
    from app.models.hook_session import HookSession

    h = HookSession(
        session_id=f"dwb585-{tag}",
        agent_id=agent_id,
        project_id=project_id,
        dwb_session_id=dwb_session_id,
        total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _memory(db, *, agent_id, tier=MemoryTier.working, **kw):
    row = AgentMemory(agent_id=agent_id, tier=tier, body="a lesson", **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def human_memory_agent(db_session, make_project, make_agent):
    """An agent on a project in human_memory mode, with the project row already
    switched. Returns (agent_id, project_id)."""
    from app.models.project import MemoryMode, Project

    project = make_project()
    agent = make_agent(project_id=project["id"])
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    return agent["id"], project["id"]


class TestSessionGap:
    """Acceptance 2: the COALESCE, which is the whole reason this is an
    acceptance criterion rather than a review note."""

    def test_never_reinforced_memory_counts_from_its_creating_session(
        self, db_session, human_memory_agent
    ):
        """THE TEST THE TICKET ASKS FOR, and the fixture shape matters as much
        as the assertion.

        This memory has NEVER been reinforced, so last_reinforced_session_id is
        NULL. That is the state of most memories and it is the state under
        which the bug is invisible: without COALESCE the comparison becomes
        `id > NULL`, which is UNKNOWN rather than true, matches nothing, and
        returns 0 sessions. Zero reads as "reinforced this session", so the
        memory scores 10 forever.

        Remove the COALESCE from the service and this test goes from 3 to 0.
        """
        agent_id, project_id = human_memory_agent

        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(
            db_session,
            agent_id=agent_id,
            created_session_id=origin.id,
            last_reinforced_session_id=None,
        )

        for n in range(3):
            later = _closed_session(db_session, project_id, hours_ago=5 - n)
            _hook_session(
                db_session,
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=later.id,
                tag=f"later{n}",
            )

        assert memory.last_reinforced_session_id is None
        assert svc.sessions_since_reinforced(db_session, memory) == 3

    def test_the_missing_coalesce_bug_demonstrated_both_ways(
        self, db_session, human_memory_agent
    ):
        """ACCEPTANCE 2's second half, made executable, plus a correction to
        the ticket's description of the failure.

        The criterion asks for a test that fails if the COALESCE is removed.
        Proving that by editing the source and watching it go red turns a
        tripwire into everyone else's mystery in a shared tree, so both broken
        variants are run HERE, side by side with the real one, against one
        fixture whose memory has NEVER been reinforced.

        THE TICKET PREDICTS A SILENT ZERO. That is exactly right for SQL, and
        the second half below demonstrates it: comparing against the raw column
        yields `id > NULL`, which is UNKNOWN rather than true, matches nothing,
        counts 0, reads as "reinforced this session", and scores the memory 10
        forever.

        BUT NOT IN THIS IMPLEMENTATION'S SHAPE, and that difference is worth
        knowing. This service resolves the origin in PYTHON before building the
        query, and SQLAlchemy REFUSES to compile `column > None`, raising
        ArgumentError instead of emitting SQL. So dropping the fallback here
        cannot produce a quietly flattering number; it produces a loud error on
        the first call. That is a property of resolving the origin in Python
        rather than in SQL, and it is a reason to keep doing it that way.
        """
        from sqlalchemy import func, select
        from sqlalchemy.exc import ArgumentError

        from app.models.dwb_session import DwbSession
        from app.models.hook_session import HookSession

        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(
            db_session,
            agent_id=agent_id,
            created_session_id=origin.id,
            last_reinforced_session_id=None,
        )
        for n in range(3):
            later = _closed_session(db_session, project_id, hours_ago=5 - n)
            _hook_session(
                db_session,
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=later.id,
                tag=f"proof{n}",
            )

        # The real implementation. Three sessions have happened since.
        assert svc.sessions_since_reinforced(db_session, memory) == 3
        assert svc.score(MemoryTier.working, 3) == 8

        # Variant 1, this module's shape without the fallback: LOUD.
        with pytest.raises(ArgumentError):
            db_session.execute(
                select(func.count(func.distinct(HookSession.dwb_session_id)))
                .select_from(HookSession)
                .join(DwbSession, DwbSession.id == HookSession.dwb_session_id)
                .where(DwbSession.id > memory.last_reinforced_session_id)
            )

        # Variant 2, the same rule expressed in SQL without COALESCE: SILENT.
        # This is the bug the ticket describes, and it is the one that would
        # have shipped had the origin been resolved in the query.
        silent = db_session.execute(
            text(
                "SELECT COUNT(DISTINCT hs.dwb_session_id) "
                "FROM hook_sessions hs "
                "JOIN dwb_sessions ds ON ds.id = hs.dwb_session_id "
                "JOIN agent_memories am ON am.id = :mid "
                "WHERE hs.agent_id = :aid AND ds.closed_at IS NOT NULL "
                "AND ds.id > am.last_reinforced_session_id"
            ),
            {"mid": memory.id, "aid": agent_id},
        ).scalar_one()

        assert silent == 0, (
            "the no-COALESCE SQL should silently count nothing; if it does "
            "not, this proof has stopped discriminating and needs rewriting"
        )
        # And that zero is what makes it dangerous: it scores a perfect 10.
        assert svc.score(MemoryTier.working, silent) == 10

        # The same SQL WITH the COALESCE agrees with the service.
        fixed = db_session.execute(
            text(
                "SELECT COUNT(DISTINCT hs.dwb_session_id) "
                "FROM hook_sessions hs "
                "JOIN dwb_sessions ds ON ds.id = hs.dwb_session_id "
                "JOIN agent_memories am ON am.id = :mid "
                "WHERE hs.agent_id = :aid AND ds.closed_at IS NOT NULL "
                "AND ds.id > COALESCE(am.last_reinforced_session_id, "
                "am.created_session_id)"
            ),
            {"mid": memory.id, "aid": agent_id},
        ).scalar_one()
        assert fixed == 3

    def test_reinforced_memory_counts_from_the_reinforcing_session(
        self, db_session, human_memory_agent
    ):
        """When last_reinforced_session_id IS set, COALESCE must prefer it over
        created_session_id. The positive case for the same expression: without
        it the count would run from creation and over-report the gap."""
        agent_id, project_id = human_memory_agent

        created = _closed_session(db_session, project_id, hours_ago=20)
        before = _closed_session(db_session, project_id, hours_ago=15)
        _hook_session(
            db_session,
            agent_id=agent_id,
            project_id=project_id,
            dwb_session_id=before.id,
            tag="before",
        )
        reinforced = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(
            db_session,
            agent_id=agent_id,
            created_session_id=created.id,
            last_reinforced_session_id=reinforced.id,
        )
        after = _closed_session(db_session, project_id, hours_ago=5)
        _hook_session(
            db_session,
            agent_id=agent_id,
            project_id=project_id,
            dwb_session_id=after.id,
            tag="after",
        )

        # One session after the reinforcement, not the two after creation.
        assert svc.sessions_since_reinforced(db_session, memory) == 1

    def test_open_sessions_do_not_tick_the_clock(self, db_session, human_memory_agent):
        """An open session is the one currently happening. It becomes
        experience when it closes, which is what makes the tick a session
        open/close rather than a wall-clock event."""
        agent_id, project_id = human_memory_agent

        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        still_open = _open_session(db_session, project_id)
        _hook_session(
            db_session,
            agent_id=agent_id,
            project_id=project_id,
            dwb_session_id=still_open.id,
            tag="open",
        )

        assert svc.sessions_since_reinforced(db_session, memory) == 0

    def test_hook_sessions_with_no_dwb_session_are_skipped(
        self, db_session, human_memory_agent
    ):
        """COUNT(DISTINCT dwb_session_id) skips NULLs and that is INTENDED
        (DWB-584): a hook session never linked to a DWB session is not an
        experience that should tick the decay clock. Asserted so the next
        reader does not 'fix' it."""
        agent_id, project_id = human_memory_agent

        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        _hook_session(
            db_session,
            agent_id=agent_id,
            project_id=project_id,
            dwb_session_id=None,
            tag="orphan",
        )

        assert svc.sessions_since_reinforced(db_session, memory) == 0

    def test_many_hook_sessions_in_one_dwb_session_count_as_one_experience(
        self, db_session, human_memory_agent
    ):
        """COUNT(DISTINCT ...) is not decoration beside the inner join.

        The join alone would already drop unlinked hook sessions, so a reader
        could take the DISTINCT for belt-and-braces and remove it. It is doing
        separate work: a DWB session contains many Claude Code hook sessions,
        and the clock ticks per DWB SESSION, not per hook session. Ruled: "a
        day is an interval bw sleep". Without DISTINCT, one busy day would
        decay a memory as if a week had passed.
        """
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        one_day = _closed_session(db_session, project_id, hours_ago=5)
        for n in range(4):
            _hook_session(
                db_session,
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=one_day.id,
                tag=f"sameday{n}",
            )

        assert svc.sessions_since_reinforced(db_session, memory) == 1

    def test_another_agents_sessions_do_not_count(self, db_session, human_memory_agent, make_agent):
        agent_id, project_id = human_memory_agent
        other = make_agent(project_id=project_id)

        origin = _closed_session(db_session, project_id, hours_ago=10)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        theirs = _closed_session(db_session, project_id, hours_ago=5)
        _hook_session(
            db_session,
            agent_id=other["id"],
            project_id=project_id,
            dwb_session_id=theirs.id,
            tag="theirs",
        )

        assert svc.sessions_since_reinforced(db_session, memory) == 0

    def test_memory_with_no_session_origin_is_unscoreable(
        self, db_session, human_memory_agent
    ):
        """Both references NULL. Reachable: DWB-586 accepts a write when no DWB
        session is open and records created_session_id as NULL.

        Returns None rather than 0. Treating it as zero elapsed would score it
        10 forever, and treating it as infinitely old would evict it; both are
        guesses dressed as arithmetic. The honest answer is that this row has
        no origin on the clock.
        """
        agent_id, _ = human_memory_agent
        memory = _memory(
            db_session,
            agent_id=agent_id,
            created_session_id=None,
            last_reinforced_session_id=None,
        )
        assert svc.sessions_since_reinforced(db_session, memory) is None


def _elapse(db, *, project_id, agent_id, n):
    """Make `n` closed DWB sessions happen to this agent, cheaply.

    Bulk rather than one-at-a-time because the interesting bands need real
    session counts: WORKING does not reach the demotion band until 15 sessions
    and does not reach 1 until 91. Faking the gap by patching the counter would
    test the list logic while leaving the query, which is the part with the
    COALESCE in it, unexercised.
    """
    from datetime import datetime, timedelta

    from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
    from app.models.hook_session import HookSession

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
                session_id=f"dwb585-bulk-{agent_id}-{i}",
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


class TestEndpoint:
    """Acceptance 4 and 5: the lists come from the ENDPOINT, and "no
    candidates" is distinguishable from "not computed"."""

    def test_unknown_agent_is_404(self, client):
        assert client.get("/api/agents/99999999/memory/scored").status_code == 404

    def test_stock_mode_reports_not_computed_with_a_reason(
        self, client, make_project, make_agent
    ):
        """ACCEPTANCE 5, half one. A project that never enabled human_memory
        gets `computed: false` and a reason, NOT three empty lists. Empty lists
        would read as "nothing to do", which is the opposite fact."""
        project = make_project()
        agent = make_agent(project_id=project["id"])

        body = client.get(f"/api/agents/{agent['id']}/memory/scored").json()

        assert body["computed"] is False
        assert body["reason"] == svc.NOT_COMPUTED_STOCK_MODE
        assert body["memory_mode"] == "stock"
        assert body["demote"] == [] and body["evict"] == [] and body["promote"] == []

    def test_human_memory_with_nothing_to_do_reports_computed_true(
        self, client, db_session, human_memory_agent
    ):
        """ACCEPTANCE 5, half two, and the pair is the point. This agent has a
        memory and it is perfectly healthy, so every list is empty AND the run
        happened. Same three empty lists as the test above, opposite meaning,
        and the response distinguishes them."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=10)
        _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.core,
            created_session_id=origin.id,
        )

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        assert body["computed"] is True
        assert body["reason"] is None
        assert body["memory_mode"] == "human_memory"
        assert body["demote"] == [] and body["evict"] == [] and body["promote"] == []
        assert len(body["entries"]) == 1
        assert body["entries"][0]["score"] == 10

    def test_unscoped_agent_is_a_distinct_not_computed_reason(
        self, client, db_session, make_agent
    ):
        """Two different not-computed reasons, distinguishable from each other
        as well as from success. A single `computed: false` with no reason
        would collapse them."""
        from app.models.agent import Agent

        agent = make_agent()
        db_session.get(Agent, agent["id"]).project_id = None
        db_session.flush()

        body = client.get(f"/api/agents/{agent['id']}/memory/scored").json()

        assert body["computed"] is False
        assert body["reason"] == svc.NOT_COMPUTED_AGENT_UNSCOPED
        assert body["reason"] != svc.NOT_COMPUTED_STOCK_MODE

    def test_demote_list_is_produced_by_the_endpoint(
        self, client, db_session, human_memory_agent
    ):
        """ACCEPTANCE 4. A WORKING memory 15 sessions past its origin scores 4,
        which is band 2-4, which is a demotion candidate. Nothing in a playbook
        produced this list."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.working,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=15)

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        assert body["computed"] is True
        assert body["demote"] == [memory.id]
        assert body["evict"] == []
        entry = body["entries"][0]
        assert entry["sessions_since_reinforced"] == 15
        assert entry["score"] == 4
        assert entry["band"] == svc.BAND_DEMOTION_CANDIDATE

    def test_evict_list_is_produced_by_the_endpoint(
        self, client, db_session, human_memory_agent
    ):
        """A WORKING memory past 90 sessions scores 1: the last consolidation
        before it goes. It appears in `evict`, and note what that means -
        nominated, not removed. Eviction is an ACT, and section 7 hard rule 4
        writes it to the journal first."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.working,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        assert body["evict"] == [memory.id]
        assert body["demote"] == []
        assert body["entries"][0]["score"] == 1
        # And it is still 1, not 0: the arithmetic floors at 1 and 0 is an act.
        assert body["entries"][0]["score"] >= svc.MIN_DERIVED_SCORE

    def test_core_is_never_a_candidate_however_long_it_sits(
        self, client, db_session, human_memory_agent
    ):
        """Section 7 hard rule 5: CORE is never touched by automatic
        consolidation. Here that falls out of the curve rather than needing a
        special case, which is the better way for it to be true."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.core,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=120)

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        assert body["demote"] == [] and body["evict"] == []
        assert body["entries"][0]["score"] == 10

    def test_raw_rows_are_reported_unscored_and_excluded(
        self, client, db_session, human_memory_agent
    ):
        """An untiered row is the NORMAL state of a fresh write (spec section
        4), not a defect. It is reported with a reason rather than dropped,
        because a memory that silently vanishes from the list an agent reads is
        worse than one that appears saying why it has no score."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.raw,
            created_session_id=origin.id,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=120)

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        entry = body["entries"][0]
        assert entry["scored"] is False
        assert entry["reason"] == svc.UNSCORED_UNTIERED
        assert entry["score"] is None and entry["band"] is None
        assert body["demote"] == [] and body["evict"] == []

    def test_rows_with_no_session_origin_are_reported_unscored(
        self, client, db_session, human_memory_agent
    ):
        agent_id, project_id = human_memory_agent
        _memory(
            db_session,
            agent_id=agent_id,
            tier=MemoryTier.working,
            created_session_id=None,
            last_reinforced_session_id=None,
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=120)

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        entry = body["entries"][0]
        assert entry["scored"] is False
        assert entry["reason"] == svc.UNSCORED_NO_SESSION_ORIGIN
        assert body["demote"] == [] and body["evict"] == []

    def test_promote_list_comes_from_the_journal(
        self, client, db_session, human_memory_agent
    ):
        """`promote` is JOURNAL entries reached for often enough that section 5
        says they should stop being a story. It delegates to
        journal.promotion_candidates rather than re-implementing the threshold:
        two copies of a number the spec ruled once is how they end up
        disagreeing."""
        from app.models.journal_entry import JournalEntry
        from app.services.journal import PROMOTION_THRESHOLD

        agent_id, _ = human_memory_agent
        hot = JournalEntry(
            agent_id=agent_id, body="reached for often", retrieval_count=PROMOTION_THRESHOLD
        )
        cold = JournalEntry(
            agent_id=agent_id, body="never reached for", retrieval_count=0
        )
        db_session.add_all([hot, cold])
        db_session.flush()

        body = client.get(f"/api/agents/{agent_id}/memory/scored").json()

        assert body["promote"] == [hot.id]

    def test_response_carries_no_stored_score_anywhere(
        self, client, db_session, human_memory_agent
    ):
        """The score is in the RESPONSE and not in the table. Reads the row back
        through raw SQL to prove the database still holds no such column after
        the endpoint has run."""
        agent_id, project_id = human_memory_agent
        origin = _closed_session(db_session, project_id, hours_ago=100)
        _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        client.get(f"/api/agents/{agent_id}/memory/scored")

        columns = {
            row[0]
            for row in db_session.execute(text("SHOW COLUMNS FROM agent_memories"))
        }
        assert "score" not in columns and "band" not in columns
