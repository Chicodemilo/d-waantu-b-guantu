# Path: tests/test_memory_context_dwb658.py
# File: test_memory_context_dwb658.py
# Created: 2026-10-08 (DWB-658)
# Purpose: Guard the 5-7 band carrying the AUTHOR'S stored `condensed` line
#          rather than a truncation of the body's first line, and guard the
#          NULL rows that must keep serving until DWB-655 backfills them.
# Caller: pytest
# Callees: app/services/memory_context, POST /api/agents/spawn-prepare
# Data In: factory projects/agents, agent_memories rows, dwb/hook sessions
# Data Out: assertions
# Last Modified: 2026-10-08 (DWB-658)

"""DWB-658: the compressed band stops guessing at the lesson.

THE TEST THAT MATTERS IS `test_stored_condensed_renders_instead_of_the_body`
AND THE REASON IS THE SECOND ASSERTION, NOT THE FIRST.

Asserting the condensed line is present proves almost nothing on its own. For
any memory whose body opens with the lesson, a correct implementation and the
old truncation produce overlapping output, so "the author's words appear"
answers the same way whether `condensed` is being read or ignored. That is the
same defect this project keeps shipping: a check whose dangerous case and safe
case give the same answer.

So every body here is built so that the first line and the condensed line are
DIFFERENT STRINGS with no shared marker, and the test asserts the body's first
line is ABSENT. That is the signal that differs: the old truncation renders the
first line and cannot render `condensed`; the new path renders `condensed` and
must not render the first line. One assertion distinguishes them, the other
merely exercises the feature.

This file is deliberately separate from test_memory_context_dwb610.py. That
file's `test_compressed_band_gets_one_line_not_the_full_body` is still correct
and still passes, because its row has a NULL `condensed` and therefore takes
the legacy fallback - which is the pre-658 behaviour by design. Leaving it
untouched is the point: it now covers the fallback, and this file covers the
stored path.
"""

from datetime import datetime, timedelta

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession
from app.services import memory_context

# A WORKING memory this many closed sessions past its origin scores 6, which
# is band 5-7 (memory_score._CURVE / BAND_COMPRESSED). Named rather than
# inlined so a curve change surfaces here as one edit, not as four mysteries.
_SESSIONS_FOR_COMPRESSED_BAND = 8


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


def _elapse(db, *, project_id, agent_id, n):
    """`n` closed DWB sessions this agent lived through, each with a linked
    HookSession - the shape sessions_since_reinforced's join requires.
    Mirrors tests/test_memory_context_dwb610.py::_elapse."""
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
                session_id=f"dwb658-{agent_id}-{i}",
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


def _compressed_memory(db, *, project_id, agent_id, body, condensed):
    """One WORKING memory sitting in band 5-7, with `condensed` set or NULL."""
    origin = _closed_session(db, project_id)
    row = AgentMemory(
        agent_id=agent_id,
        tier=MemoryTier.working,
        body=body,
        condensed=condensed,
        created_session_id=origin.id,
    )
    db.add(row)
    db.flush()
    _elapse(
        db,
        project_id=project_id,
        agent_id=agent_id,
        n=_SESSIONS_FOR_COMPRESSED_BAND,
    )
    return row


class TestCondensedDrivesTheCompressedBand:
    def test_stored_condensed_renders_instead_of_the_body(
        self, db_session, make_project, make_agent
    ):
        """ACCEPTANCE 1. A stored `condensed` renders as the AUTHOR'S line.

        The body here is the shape that motivated the whole ticket: three
        sentences of setup, with the lesson last. The old truncation would
        carry SETUP-MARKER and drop the point entirely.
        """
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        setup_marker = "SETUP-FIRST-LINE-MUST-NOT-SURVIVE-3a91"
        lesson_marker = "LESSON-AUTHOR-WROTE-THIS-7f2b"
        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body=(
                f"{setup_marker}: we were mid-migration on a shared tree.\n"
                "Two people were editing the same router.\n"
                "The suite was green the whole time."
            ),
            condensed=f"{lesson_marker}: a green suite cannot see a missing commit",
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "compressed (score 5-7)" in context
        # Merely exercises the feature.
        assert lesson_marker in context
        # THE DECISIVE ONE. The old truncation renders this and cannot render
        # the line above; the new path renders the line above and must not
        # render this. Without it, a body whose first line happens to be the
        # lesson would pass under either implementation.
        assert setup_marker not in context

    def test_stored_condensed_is_not_marked_as_an_excerpt(
        self, db_session, make_project, make_agent
    ):
        """An author's line must not wear the legacy marker, or the marker
        stops distinguishing anything and the band is back to one answer for
        two realities."""
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body="SETUP-LINE-b44c\nmore body",
            condensed="the author's own one-liner",
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "the author's own one-liner" in context
        assert memory_context._LEGACY_EXCERPT_NOTE not in context


class TestNullCondensedRowsStillServe:
    def test_null_condensed_row_still_appears_in_the_band(
        self, db_session, make_project, make_agent
    ):
        """ACCEPTANCE 2. All 832 rows that existed when DWB-658 landed have
        NULL `condensed`. They must not vanish from the band and must not
        crash it."""
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        legacy_marker = "LEGACY-FIRST-LINE-MUST-SURVIVE-5d07"
        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body=f"- {legacy_marker}\n  a second line that should not be carried",
            condensed=None,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert "compressed (score 5-7)" in context
        assert legacy_marker in context
        assert "a second line that should not be carried" not in context

    def test_null_condensed_row_is_marked_as_an_excerpt(
        self, db_session, make_project, make_agent
    ):
        """The fallback is a machine's guess at the lesson, not the author's
        line, and the reader has to be able to tell. An unmarked fallback
        reproduces the exact bug DWB-658 exists to fix, on every pre-backfill
        row, silently."""
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body="some old lesson nobody condensed",
            condensed=None,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert memory_context._LEGACY_EXCERPT_NOTE in context

    def test_blank_condensed_is_treated_as_absent_not_as_an_empty_line(
        self, db_session, make_project, make_agent
    ):
        """A whitespace-only `condensed` is reachable by raw SQL until
        DWB-656's NOT NULL flip, and rendering it verbatim would put an empty
        bullet in the band - a row that looks like it has no lesson rather
        than one nobody condensed. Falls back, and is marked."""
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        body_marker = "BLANK-CONDENSED-FALLS-BACK-9e31"
        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body=f"{body_marker}: the lesson",
            condensed="   \n  ",
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert body_marker in context
        assert memory_context._LEGACY_EXCERPT_NOTE in context


class TestOneLineIsGone:
    def test_one_line_helper_no_longer_exists(self):
        """ACCEPTANCE 3, the cheap half. The thorough half is the AST walk
        over app/, scripts/ and tests/ - a grep matches `_one_line` inside
        human_memory_exerciser.py's comment saying it deliberately does NOT
        import it, so a grep-based check reports a hit that means nothing.

        This assertion only covers the module that owned the function. It is
        here because it localizes a regression instantly; it does not replace
        the walk.
        """
        assert not hasattr(memory_context, "_one_line")
        assert not hasattr(memory_context, "_ONE_LINE_CHARS")


class TestRenderedLineIsBoundedForDisplay:
    """The write gate (DWB-657) applies NO character cap, by ruling: a count is
    a proxy for "carries the lesson not the setup" and is wrong in both
    directions. That leaves an author free to paste an entire body into
    `condensed` and defeat the only reason the 5-7 band is abbreviated, so the
    bound lives here instead.

    This is NOT the truncation DWB-658 deleted, and the difference is testable:
    a bound applied AFTER the lesson has been chosen can shorten a line but can
    never swap the setup in for the point.
    """

    def test_an_enormous_condensed_line_cannot_blow_the_band(
        self, db_session, make_project, make_agent
    ):
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body="irrelevant",
            condensed="PASTED-BODY-HEAD " + ("x" * 5000),
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        line = next(
            ln for ln in context.splitlines() if ln.startswith("- ")
        )
        assert len(line) <= memory_context._RENDERED_LINE_CHARS + 4
        # Bounded, but the author's line still LEADS - the bound took the tail,
        # not the point. This is the assertion that separates a display bound
        # from the body truncation this ticket removed.
        assert "PASTED-BODY-HEAD" in line
        assert line.endswith("…")

    def test_an_ordinary_one_liner_is_not_touched(
        self, db_session, make_project, make_agent
    ):
        """400 is deliberately generous so nothing honest is altered. A bound
        that routinely fires would be a truncation policy by another name."""
        project = make_project(memory_mode="human_memory")
        agent_row = make_agent(project_id=project["id"])
        agent = db_session.get(Agent, agent_row["id"])

        lesson = (
            "a green suite cannot see a missing commit, because the fixture "
            "hands the test and the API one session inside a rolled-back "
            "transaction"
        )
        _compressed_memory(
            db_session,
            project_id=project["id"],
            agent_id=agent.id,
            body="irrelevant",
            condensed=lesson,
        )

        context = memory_context.assemble_session_context(db_session, agent)

        assert context is not None
        assert lesson in context
        assert "…" not in context


class TestTheScoredEndpointServesBothFields:
    """THE SECOND CONSUMER, VERIFIED THROUGH ITS OWN PATH.

    `memory_score._entry` feeds BOTH context assembly and
    GET /api/agents/{id}/memory/scored. Verifying one does not license a
    conclusion about the other, and it fails in both directions: the context
    path can pass while the endpoint strips the fields, because
    `ScoredMemoryEntry` is a response_model and pydantic's default `extra` is
    `ignore`; and the endpoint can fail while `_entry` is already correct.

    So this asserts on the RETURNED KEY SET rather than on the service dict.
    A test that reached into `_entry` would be asking the first question again
    in different words.
    """

    def test_scored_response_declares_condensed_and_keywords(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path), memory_mode="human_memory")
        agent = make_agent(project_id=project["id"], name="Scorey", role="backend-worker")
        origin = _closed_session(db_session, project["id"], hours_ago=1)
        row = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.working,
            body="a body",
            condensed="ENDPOINT-CONDENSED-LINE",
            keywords=["endpoint", "projection"],
            created_session_id=origin.id,
        )
        db_session.add(row)
        db_session.commit()

        r = client.get(f"/api/agents/{agent['id']}/memory/scored")

        assert r.status_code == 200
        entry = next(e for e in r.json()["entries"] if e["id"] == row.id)
        # The key set is the thing under test: a stripped field is ABSENT, not
        # null, so `.get()` returning None would not distinguish "declared and
        # empty" from "never declared".
        assert "condensed" in entry
        assert "keywords" in entry
        assert entry["condensed"] == "ENDPOINT-CONDENSED-LINE"
        assert entry["keywords"] == ["endpoint", "projection"]
