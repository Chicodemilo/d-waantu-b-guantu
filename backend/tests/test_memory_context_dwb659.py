# Path: tests/test_memory_context_dwb659.py
# File: test_memory_context_dwb659.py
# Created: 2026-10-08 (DWB-659)
# Purpose: Guard the 2-4 and 1 bands rendering each row's keywords instead of
#          a bare aggregate count: that an agent can tell what it is about to
#          lose, that a NULL-keywords row is distinguishable from a row whose
#          keywords are genuinely uninformative, and that the section stays
#          bounded however large the buckets get.
# Caller: pytest
# Callees: app/services/memory_context
# Data In: factory projects/agents, agent_memories rows, dwb/hook sessions
# Data Out: assertions
# Last Modified: 2026-10-08 (DWB-659)

"""DWB-659: the bottom bands stop being a number.

The bands stay ABBREVIATED - no bodies, no condensed lines - because they are
abbreviated on purpose: 2-4 is flagged for demotion and 1 is the last pass
before eviction, and the budget is the whole reason they are not carried in
full. What changes is that a count becomes inspectable.

THE ASSERTION THAT CARRIES THIS FILE IS THE DISTINGUISHABILITY ONE. A blank
entry and a NULL entry both render as "nothing here" under any naive
implementation, and those are two different facts: one memory has keywords
that say little, the other was written before anyone was asked for keywords at
all. A display that answers identically for both is the defect this whole lane
has been finding. So the tests check that the two states produce DIFFERENT
strings, not merely that each produces something.
"""

import itertools
from datetime import datetime, timedelta

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.services import memory_context

# WORKING at this many closed sessions past its origin scores 4 (bucket 15-30)
# -> band demotion_candidate, and at this many scores 1 (the open 90+ bucket)
# -> band last_consolidation. Named so a curve change surfaces as one edit.
_SESSIONS_FOR_DEMOTE_BAND = 20
_SESSIONS_FOR_EVICT_BAND = 91


def _closed_session(db, project_id, *, hours_ago=1000):
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


# `session_id` is uniquely indexed on hook_sessions, and one test calls
# `_elapse` twice for the same agent to build two bands at once. A template
# keyed only on (agent_id, i) collides on the second call - caught by an
# IntegrityError rather than by review, which is the only reason it is
# written down here.
_ELAPSE_CALLS = itertools.count()


def _elapse(db, *, project_id, agent_id, n):
    batch = next(_ELAPSE_CALLS)
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
                session_id=f"dwb659-{agent_id}-{batch}-{i}",
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


def _setup(db, make_project, make_agent):
    project = make_project(memory_mode="human_memory")
    agent_row = make_agent(project_id=project["id"])
    agent = db.get(Agent, agent_row["id"])
    origin = _closed_session(db, project["id"])
    return project, agent, origin


def _memory(db, *, agent_id, origin_id, body, keywords):
    row = AgentMemory(
        agent_id=agent_id,
        tier=MemoryTier.working,
        body=body,
        keywords=keywords,
        created_session_id=origin_id,
    )
    db.add(row)
    db.flush()
    return row


class TestFlaggedBandsAreInspectable:
    def test_demotion_candidate_keywords_reach_the_agent(
        self, db_session, make_project, make_agent
    ):
        """ACCEPTANCE 1. An agent with demotion candidates can see what they
        are about."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="BODY-MUST-NOT-APPEAR-d41a a long lesson about shared trees",
            keywords=["checkout", "shared-tree", "uncommitted"],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "Demotion candidates (score 2-4)" in context
        assert "checkout" in context
        assert "shared-tree" in context
        # The band stays abbreviated. Keywords, never the body.
        assert "BODY-MUST-NOT-APPEAR-d41a" not in context

    def test_eviction_row_keywords_reach_the_agent(
        self, db_session, make_project, make_agent
    ):
        """The band for memories actually about to go. Same requirement, and
        the more urgent one."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="BODY-MUST-NOT-APPEAR-9c02",
            keywords=["alias", "cmp", "tracked-files"],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_EVICT_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "Last pass before eviction (score 1)" in context
        assert "alias" in context
        assert "BODY-MUST-NOT-APPEAR-9c02" not in context

    def test_row_ids_are_rendered_so_a_row_can_be_looked_up(
        self, db_session, make_project, make_agent
    ):
        """Keywords say what a memory is about; the id is what makes it
        actionable against /memory/scored."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        row = _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="something",
            keywords=["one", "two"],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert f"#{row.id}" in context
        assert "/memory/scored" in context


class TestTheTwoEmptyStatesAreDistinguishable:
    """ACCEPTANCE 2, and the reason this file exists.

    NULL means nobody was ever asked. An empty list means somebody was asked
    and supplied nothing. Rendering both as blank collapses two realities into
    one answer.
    """

    def test_null_keywords_say_nobody_was_asked(
        self, db_session, make_project, make_agent
    ):
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="an old lesson",
            keywords=None,
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert memory_context._KEYWORDS_NEVER_ASKED in context

    def test_null_and_empty_render_differently(
        self, db_session, make_project, make_agent
    ):
        """THE DECISIVE ASSERTION. Both rows are in the same band and neither
        has anything useful to say; the output must still tell them apart.

        Asserting each renders 'something' would pass against an
        implementation that printed the same placeholder for both, which is
        the plausible wrong version of this feature.
        """
        project, agent, origin = _setup(db_session, make_project, make_agent)
        never_asked = _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="predates the field",
            keywords=None,
        )
        asked_and_empty = _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="author supplied nothing",
            keywords=[],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        lines = {
            line.split("  ", 1)[0]: line
            for line in context.splitlines()
            if line.startswith("- #")
        }
        null_line = lines[f"- #{never_asked.id}"]
        empty_line = lines[f"- #{asked_and_empty.id}"]
        assert null_line != empty_line
        assert memory_context._KEYWORDS_NEVER_ASKED in null_line
        assert memory_context._KEYWORDS_RECORDED_EMPTY in empty_line

    def test_a_weak_keyword_set_is_still_shown_as_the_authors(
        self, db_session, make_project, make_agent
    ):
        """A genuinely uninformative keyword set is the author's answer and is
        rendered as such. It must not be rewritten into either sentinel - that
        would hide the fact that somebody did answer, badly."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="something",
            keywords=["thing", "stuff"],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "thing, stuff" in context
        assert memory_context._KEYWORDS_NEVER_ASKED not in context
        assert memory_context._KEYWORDS_RECORDED_EMPTY not in context


class TestTheSectionStaysBounded:
    def test_many_candidates_do_not_grow_the_section_without_limit(
        self, db_session, make_project, make_agent
    ):
        """ACCEPTANCE 3. Thirty demotion candidates must not put thirty lines
        into every spawn prompt."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        for i in range(30):
            _memory(
                db_session,
                agent_id=agent.id,
                origin_id=origin.id,
                body=f"lesson {i}",
                keywords=[f"kw{i}a", f"kw{i}b"],
            )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        rows = [line for line in context.splitlines() if line.startswith("- #")]
        assert len(rows) <= memory_context._FLAGGED_ROWS_PER_BAND
        # Bounded, but it must not UNDERSTATE what is at stake: the heading
        # carries the true total and the overflow is named.
        assert "Demotion candidates (score 2-4) - 30:" in context
        assert "26 more not shown" in context

    def test_each_band_gets_its_own_budget(
        self, db_session, make_project, make_agent
    ):
        """A shared pool would let a large demotion bucket crowd out the
        eviction rows entirely, and the eviction rows are the ones actually
        about to be lost. Each band is capped separately so neither can starve
        the other."""
        project, agent, origin = _setup(db_session, make_project, make_agent)

        # BOTH BANDS HAVE TO BE POPULATED AT ONCE OR THIS TEST IS NAMED FOR A
        # CASE IT DOES NOT CONSTRUCT. The first version called `_elapse`
        # twice, which is CUMULATIVE - the agent ended up with 111 closed
        # sessions, every memory was past the 90+ boundary, and all 21 rows
        # landed in band 1 with the demotion band empty. It still failed on
        # its keyword assertion, so it looked like it was doing its job.
        #
        # The gap is per-memory: closed sessions with id > that memory's
        # origin. So one batch of sessions is created, and the two memories
        # are anchored at different points inside it - 95 sessions after the
        # eviction row's origin (band 1), 20 after the demotion rows' (2-4).
        sessions = _elapse(
            db_session, project_id=project["id"], agent_id=agent.id, n=95
        )
        mid_origin = sessions[74]  # 20 sessions follow it -> score 4

        for i in range(20):
            _memory(
                db_session,
                agent_id=agent.id,
                origin_id=mid_origin.id,
                body=f"demote {i}",
                keywords=["demote-kw"],
            )
        evicting = _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="about to go",
            keywords=["EVICT-KEYWORD-MUST-SURVIVE"],
        )

        context = memory_context.assemble_session_context(db_session, agent)

        # PRECONDITION, asserted in the test rather than assumed: both bands
        # are actually present. Without this the crowding-out question is
        # never posed and the test passes for the wrong reason.
        assert context is not None
        assert "Demotion candidates (score 2-4) - 20:" in context
        assert "Last pass before eviction (score 1) - 1:" in context

        # The whole point: twenty demotion rows did not consume the budget the
        # eviction band needed.
        assert "EVICT-KEYWORD-MUST-SURVIVE" in context
        assert f"#{evicting.id}" in context

    def test_a_pathological_keyword_list_cannot_blow_the_budget(
        self, db_session, make_project, make_agent
    ):
        """`keywords` is a JSON column and nothing constrains its contents
        until DWB-656, so a raw write can put anything in it. One bad row must
        not be able to flood a spawn prompt."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="something",
            keywords=["x" * 5000] + [f"kw{i}" for i in range(200)],
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        row = next(
            line for line in context.splitlines() if line.startswith("- #")
        )
        assert len(row) < 400
        assert "more" in row


class TestNonListKeywordsDoNotCrash:
    def test_a_bare_string_renders_rather_than_exploding(
        self, db_session, make_project, make_agent
    ):
        """Reachable by raw write until DWB-656. Iterating it would render one
        character per keyword, which looks like data rather than a mistake."""
        project, agent, origin = _setup(db_session, make_project, make_agent)
        _memory(
            db_session,
            agent_id=agent.id,
            origin_id=origin.id,
            body="something",
            keywords="not-a-list",
        )
        _elapse(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            n=_SESSIONS_FOR_DEMOTE_BAND,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "not-a-list" in context
        assert "n, o, t, -, a" not in context
