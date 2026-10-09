# Path: tests/test_memory_fired_count_dwb603.py
# File: test_memory_fired_count_dwb603.py
# Created: 2026-09-30 (DWB-603)
# Purpose: Guard the fired_count write site - a scar fires exactly once per
#          MATCHING consultation, a search with no term is refused, a search
#          that finds nothing fires nothing, scored_memory() (injection,
#          dashboard) can never fire anything, and there is exactly one write
#          site in the app.
# Caller: pytest
# Callees: app.services.memory_consult.consult_scars,
#          app.services.memory_score.scored_memory, ast
# Data In: factory agents/projects, agent_memories rows
# Data Out: Assertions on the persisted fired_count and on write sites
# Last Modified: 2026-09-30 (MILES RULING: rewritten. The original version of
#                this file tested firing through GET /memory/scored, which is
#                exactly the mechanism the ruling said was wrong - that
#                endpoint is "give me everything", no question in it, and
#                Miles ruled that is delivery, not a read. Firing moved to
#                memory_consult.consult_scars, a search that requires a term
#                and fires only what matches it.)

"""DWB-603 acceptance, as redesigned by the Miles firing ruling.

MILES, VERBATIM: "Deploy doesn't count as a read. Reading is Oh have I made
this scar producing error before? Outside of normal startup." The generating
rule Archie adopted from this thread: a read is injection-shaped when it can
be satisfied with no question in it. `scored_memory()` always could - "give
me everything", no filter - which is why `TestScoredMemoryNeverFires` exists
and is the half of this file that did not exist before the ruling. The other
half, `TestConsultScars`, proves the replacement: a search that REQUIRES a
term and fires only the rows that match it, same discipline
`journal.search_entries` already enforces for an unrelated reason that turns
out to be the same reason.

Every behavioural assertion here re-fetches the row from the database after
the call, not from the return value or the in-memory object the test is still
holding - the same discipline the original version of this file used, kept
because the underlying acceptance ("proven by a test that... asserts the
stored value, not just that some increment code path exists") did not change
when the mechanism did.
"""

import ast
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from app.services import memory_consult as svc
from app.services import memory_score

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


# DWB-644: THE SCAR IS FOUND BY ITS OWN KEYWORDS, NOT BY QUOTING ITS BODY.
# Before this ticket every test here fired a scar with term="migration",
# matched as a literal substring of the body. That relation was backwards: it
# could only fire when the prompt was a verbatim slice of the lesson, and it
# fired on ordinary English that happened to sit inside one. These fixtures
# describe a SITUATION, and the lesson's author-supplied keywords are tested
# against it.
#
# THE KEYWORDS AND THE BODY DELIBERATELY SHARE NO WORDING. If the situation
# below were also a substring of the body, every test in this file would pass
# under BOTH relations and none of them would distinguish the fix from the bug.
SCAR_KEYWORDS = ["alembic migration", "head revision"]
SITUATION = "editing an alembic migration that is already applied"
NO_MATCH = "pick a colour for the sprint badge"


def _memory(
    db,
    *,
    agent_id,
    tier=MemoryTier.scar,
    body="a lesson about X",
    keywords=None,
    **kw,
):
    row = AgentMemory(
        agent_id=agent_id, tier=tier, body=body, keywords=keywords, **kw
    )
    db.add(row)
    db.flush()
    return row


def _scar(db, *, agent_id, body="hit a race in the migration", **kw):
    """A scar that CAN be recalled - it has keywords. A scar without them is
    unmatchable by construction under the DWB-644 relation, which is its own
    reported state rather than a miss."""
    kw.setdefault("keywords", list(SCAR_KEYWORDS))
    return _memory(db, agent_id=agent_id, body=body, **kw)


def _fired_count_of(db, memory_id):
    """Re-fetch from the database, not the ORM's in-session cache. Forces a
    re-SELECT, proving what is actually STORED rather than an object the test
    itself is still holding a stale reference to."""
    db.expire_all()
    return db.get(AgentMemory, memory_id).fired_count


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


@pytest.fixture
def human_memory_agent(db_session, make_project, make_agent):
    """An agent on a project in human_memory mode - needed for
    scored_memory() to compute anything, not needed by consult_scars itself
    (it has no mode gate; see TestConsultScars note)."""
    project = make_project()
    agent = make_agent(project_id=project["id"])
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    return agent["id"], project["id"]


class TestConsultScars:
    """ACCEPTANCE: a scar's fired_count increases by exactly 1 per MATCHING
    consultation, proven against the stored value."""

    def test_a_match_fires_the_scar(self, db_session, agent):
        scar = _scar(db_session, agent_id=agent["id"])
        assert scar.fired_count == 0

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 1
        assert [m.id for m in result["entries"]] == [scar.id]
        assert _fired_count_of(db_session, scar.id) == 1

    def test_repeated_matching_consultations_accumulate(self, db_session, agent):
        scar = _scar(db_session, agent_id=agent["id"])
        for expected in (1, 2, 3):
            svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)
            assert _fired_count_of(db_session, scar.id) == expected

    def test_a_search_that_finds_nothing_fires_nothing(self, db_session, agent):
        scar = _scar(db_session, agent_id=agent["id"])

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=NO_MATCH
        )

        assert result["count"] == 0
        assert result["entries"] == []
        assert _fired_count_of(db_session, scar.id) == 0

    def test_only_the_matching_scar_fires_not_every_scar(self, db_session, agent):
        matching = _scar(db_session, agent_id=agent["id"])
        other = _scar(
            db_session,
            agent_id=agent["id"],
            body="an unrelated lesson",
            keywords=["sprint badge colour", "css token"],
        )

        svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)

        assert _fired_count_of(db_session, matching.id) == 1
        assert _fired_count_of(db_session, other.id) == 0

    def test_scoped_to_the_given_agent(self, db_session, agent, make_agent):
        other_agent = make_agent(project_id=agent["project_id"])
        _scar(db_session, agent_id=other_agent["id"])

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["entries"] == []

    @pytest.mark.parametrize("situation", ["", "   ", None])
    def test_a_blank_or_missing_situation_is_refused(
        self, db_session, agent, situation
    ):
        """The refusal survived DWB-644's inversion unchanged - only the name
        of what is required moved. A consultation with nothing in it is a list
        wearing a consultation's clothes, whichever direction the match runs."""
        _scar(db_session, agent_id=agent["id"])
        with pytest.raises(svc.ConsultError) as exc_info:
            svc.consult_scars(db_session, agent_id=agent["id"], situation=situation)
        assert exc_info.value.code == "situation_required"

    def test_the_old_keyword_argument_is_a_typeerror_not_a_silent_match(
        self, db_session, agent
    ):
        """DWB-644 renamed `term` to `situation` deliberately. The dangerous
        outcome of an inversion is a call site that still means the old thing
        and still runs, so the old name must fail loudly rather than be
        reinterpreted."""
        _scar(db_session, agent_id=agent["id"])
        with pytest.raises(TypeError):
            svc.consult_scars(db_session, agent_id=agent["id"], term="migration")

    def test_a_scar_with_no_keywords_cannot_fire_and_is_reported_as_such(
        self, db_session, agent
    ):
        """The known hole, asserted rather than left to be discovered: 15 live
        scars predate DWB-657 and carry no keywords, so this relation can never
        recall them. `unmatchable` is why that reads differently from
        searched-and-not-found."""
        scar = _memory(
            db_session,
            agent_id=agent["id"],
            body="hit a race in the alembic migration head revision",
            keywords=None,
        )

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 0
        assert result["unmatchable"] == 1
        assert result["considered"] == 1
        assert _fired_count_of(db_session, scar.id) == 0

    def test_a_common_word_shared_with_one_keyword_does_not_fire(
        self, db_session, agent
    ):
        """THE OTHER HALF OF THE BUG. The old relation fired on an ordinary
        English phrase that happened to sit inside a lesson body; this one must
        not fire on a single ordinary word that happens to be a keyword. One
        shared word is coincidence - the conjunction is the mechanism."""
        scar = _scar(db_session, agent_id=agent["id"], keywords=["migration", "alembic"])

        result = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="should I write a migration for this?",
        )

        assert result["count"] == 0
        assert _fired_count_of(db_session, scar.id) == 0

        # ... and the same scar DOES fire once both of its words are present,
        # so the assertion above is about the rule and not about an
        # unreachable row. An absence assertion paired with the state where it
        # must come back non-zero proves itself on every run.
        result = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="should I write an alembic migration for this?",
        )
        assert result["count"] == 1
        assert _fired_count_of(db_session, scar.id) == 1

    def test_returned_rows_carry_the_post_increment_value(self, db_session, agent):
        """The caller gets the AFTER value, not the before - same discipline
        journal.py's search uses for its own counter, and for the same
        reason: a caller reading a pre-increment value would see a number the
        database has already moved past."""
        scar = _scar(db_session, agent_id=agent["id"])
        svc.consult_scars(db_session, agent_id=agent["id"], situation=SITUATION)

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["entries"][0].fired_count == 2
        assert result["entries"][0].fired_count == _fired_count_of(db_session, scar.id)

    def test_result_shape_matches_journal_searchs_handles(self, db_session, agent):
        """DWB-612's wiring pulls `result["count"]` and
        `[e.id for e in result["entries"]]` off journal.search_entries today;
        this proves consult_scars offers the same two handles rather than a
        shape Freddie has to special-case."""
        scar = _scar(db_session, agent_id=agent["id"])
        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )
        assert result["count"] == len(result["entries"]) == 1
        assert [e.id for e in result["entries"]] == [scar.id]
        assert result["agent_id"] == agent["id"]
        # DWB-644: the response no longer echoes the prompt back as `term`. It
        # carries the KEYWORDS that matched, which the agent wrote - so the
        # measurement surface contains no user text by construction.
        assert result["matched_keywords"] == {scar.id: ["alembic migration"]}
        assert "term" not in result


class TestScoredMemoryNeverFires:
    """THE RULING'S OWN HALF: scored_memory() - called from spawn/SessionStart
    injection and DWB-613's dashboard - must never fire anything, under any
    circumstance, because it is a LIST ("give me everything"), not a
    consultation. This is the regression test for the original DWB-603
    design, which fired here and was ruled wrong."""

    def test_reading_scored_memory_does_not_fire_a_scar(
        self, db_session, human_memory_agent
    ):
        agent_id, _ = human_memory_agent
        scar = _memory(db_session, agent_id=agent_id)

        for _ in range(5):
            memory_score.scored_memory(db_session, agent_id=agent_id)

        assert _fired_count_of(db_session, scar.id) == 0

    def test_scored_memory_contains_no_update_statement(self, db_session, human_memory_agent):
        """Belt-and-braces on the behavioural test above and a preview of the
        structural guard below: the function's own source contains no UPDATE
        at all, not merely "doesn't move fired_count in this fixture shape"."""
        import inspect

        source = inspect.getsource(memory_score.scored_memory)
        assert "update(" not in source, (
            "scored_memory() contains an UPDATE statement; it must remain "
            "pure per the Miles firing ruling"
        )


# ---------------------------------------------------------------------------
# Structural half: exactly one write site, same method the original version
# of this file (and journal.py's own guard) used for the same reason - "one
# writer" is a claim about the whole tree, and only a source scan backs it.
# ---------------------------------------------------------------------------


def _python_sources() -> list[pathlib.Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _fired_count_writes() -> list[tuple[str, int]]:
    """Every place in app/ that WRITES agent_memories.fired_count. Same three
    shapes as journal.py's own guard: an attribute assignment, an attribute
    augmented-assignment, and `fired_count=` passed as a keyword to any call.
    """
    sites: list[tuple[str, int]] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(APP_DIR.parent))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr == "fired_count":
                        sites.append((rel, node.lineno))
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "fired_count":
                        sites.append((rel, node.lineno))
    return sites


class TestExactlyOneWriteSite:
    def test_the_scan_can_see_the_identifier_at_all(self):
        sources = _python_sources()
        assert len(sources) > 20, f"only scanned {len(sources)} files"
        mentions = [
            p for p in sources if "fired_count" in p.read_text(encoding="utf-8")
        ]
        assert len(mentions) >= 3, (
            "expected the model, the service and the schema to mention "
            f"fired_count; found {[str(m) for m in mentions]}"
        )

    def test_exactly_one_write_site_and_it_is_memory_consult(self):
        sites = _fired_count_writes()
        assert len(sites) == 1, (
            "fired_count must have exactly one writer. Found: "
            f"{sites}"
        )
        path, _line = sites[0]
        assert path == "app/services/memory_consult.py", sites

    def test_the_one_write_only_increments(self):
        source = (APP_DIR / "services" / "memory_consult.py").read_text(
            encoding="utf-8"
        )
        assert "fired_count=AgentMemory.fired_count + 1" in source, source
        for forbidden in ("fired_count=0", "fired_count = 0"):
            assert forbidden not in source, f"found a reset: {forbidden}"

    def test_memory_score_module_contains_no_write_site(self):
        """The regression guard for the thing that was actually wrong: not
        just "fired_count has one writer somewhere", but specifically that
        memory_score.py - the module spawn/SessionStart injection and the
        dashboard both call into - is not it."""
        sites = _fired_count_writes()
        offenders = [p for p, _ in sites if p == "app/services/memory_score.py"]
        assert offenders == [], (
            "memory_score.py must never write fired_count again - that is "
            "the exact defect Miles ruled on"
        )
