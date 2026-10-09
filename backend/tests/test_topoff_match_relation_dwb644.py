# Path: tests/test_topoff_match_relation_dwb644.py
# File: test_topoff_match_relation_dwb644.py
# Created: 2026-10-08 (DWB-644)
# Purpose: Guard the INVERTED match relation. A scar is recalled by its own
#          author-supplied keywords landing in the situation, not by the
#          situation being a verbatim substring of the lesson body. Both
#          directions of the original defect are pinned here with the real
#          phrases that demonstrated them, each paired with a positive control
#          proving the fixture is the dangerous case rather than an inert one.
# Caller: pytest
# Callees: app.services.memory_consult (match_scars, consult_scars,
#          matching_keywords, keyword_token_set), app.models.agent_memory, ast
# Data In: factory agents/projects, agent_memories rows with keywords
# Data Out: Assertions on matches, on the stored fired_count, and on the
#           structure of the pure half
# Last Modified: 2026-10-08 (DWB-644)

"""The relation was backwards, and it was wrong in BOTH directions.

`_topoff_search_term` sliced the user's prompt and `consult_scars` asked
whether that slice was a substring of a lesson body. Two consequences, both
measured against the live store before this ticket:

  - IT COULD NOT FIRE WHEN IT SHOULD. `fired_count` was 0 on all 877 rows
    across both human_memory projects and `last_reinforced_session_id` was NULL
    on every one. A scar could only match when the user was RECITING THE LESSON
    BACK, which is exactly when a consultation is unnecessary.
  - IT COULD FIRE WHEN NOTHING HAPPENED. 'one at a time', 'the same thing' and
    'the next person' are substrings of real lesson bodies, so typing one as a
    whole prompt fired scars nobody recalled. Three firings promote a scar to
    CORE, which never decays and has no demotion path (DWB-665).

EVERY TEST HERE CARRIES ITS POSITIVE CONTROL, and that is the point of the
file rather than decoration. An assertion that a phrase does NOT match is
satisfied just as well by a fixture nothing could ever match, which is the
vacuous shape this codebase keeps producing. So each absence assertion is
paired, in the same test, with the state where the count must come back
non-zero: either the old relation's own predicate run against the same row, or
the same row fired by a situation that does name it.
"""

import ast
import inspect
import pathlib

import pytest
from sqlalchemy import select

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_consult as svc

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# The lesson. Its BODY and its KEYWORDS deliberately share no wording with the
# situations below, so a test that passes here cannot also pass under the old
# substring relation.
BODY = (
    "Reverting a file through the version control system on a tree nobody has "
    "committed today discards every uncommitted change in it, including work "
    "from tickets that are not yours. Copy it aside and restore from the copy."
)
KEYWORDS = ["git checkout", "shared tree"]
SITUATION = "can I git checkout this file to undo my edit on the shared tree"

# Every one of these is a plausible complete user message, and every one of
# them matched a real live scar under the old relation. Verbatim from the
# ticket, because a regression guard written in paraphrase stops being about
# the thing that happened.
COINCIDENCE_PHRASES = [
    "is not the",
    "that is the",
    "this is the",
    "one at a time",
    "the same thing",
    "is not the same",
    "the next person",
]
# A body that contains every one of them, so the OLD relation would fire on
# all seven. That is what makes the zero below a finding.
COINCIDENCE_BODY = (
    "A guard that passes because the dangerous case answers the same thing as "
    "the safe one is not the same check you meant to write. That is the shape "
    "this defect keeps taking, and this is the part the next person inherits. "
    "Take them one at a time."
)


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


def _scar(db, *, agent_id, body=BODY, keywords=KEYWORDS, **kw):
    row = AgentMemory(
        agent_id=agent_id,
        tier=MemoryTier.scar,
        body=body,
        keywords=list(keywords) if keywords is not None else None,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _old_relation_matches(db, *, agent_id, term):
    """THE OLD PREDICATE, RUN AS PRODUCTION RAN IT.

    `AgentMemory.body.like('%term%')` through the ORM against the real engine,
    not a Python `in`. The column collation is `utf8mb4_0900_ai_ci`, so LIKE is
    case- and accent-insensitive where Python `in` is not, and three people
    measuring this with `in` all undercounted in the same direction - so
    cross-checking each other caught nothing. A control reimplemented in
    another language is not a control of the thing it claims to measure.
    """
    return list(
        db.execute(
            select(AgentMemory).where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.tier.in_((MemoryTier.scar,)),
                AgentMemory.body.like(f"%{term}%"),
            )
        )
        .scalars()
        .all()
    )


def _fired_count_of(db, memory_id):
    db.expire_all()
    return db.get(AgentMemory, memory_id).fired_count


class TestItFiresWhenTheAgentHitsTheSituation:
    """The direction that had never once worked in production."""

    def test_a_situation_that_names_the_lesson_fires_it(self, db_session, agent):
        scar = _scar(db_session, agent_id=agent["id"])

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 1
        assert [m.id for m in result["entries"]] == [scar.id]
        assert _fired_count_of(db_session, scar.id) == 1

    def test_the_same_situation_found_nothing_under_the_old_relation(
        self, db_session, agent
    ):
        """THE POSITIVE CONTROL FOR THE TEST ABOVE, and the reason this file
        exists rather than a single green assertion.

        If the situation were also a substring of the body, the test above
        would pass under the broken code too and would be evidence of nothing.
        This runs the OLD predicate against the SAME row and asserts it finds
        nothing, which is what makes the match above attributable to the
        inversion.
        """
        _scar(db_session, agent_id=agent["id"])

        assert _old_relation_matches(
            db_session, agent_id=agent["id"], term=SITUATION
        ) == []

        # ... and the old predicate is not simply broken in this fixture: hand
        # it the one input it COULD match - a verbatim slice of the body - and
        # it finds the row. An absence assertion that cannot see what is there
        # is not a measurement.
        recital = BODY[:60]
        assert len(_old_relation_matches(
            db_session, agent_id=agent["id"], term=recital
        )) == 1


class TestRecitingTheLessonIsNotRecall:
    """The old relation's ONLY firing case is no longer sufficient on its own.

    This is not a cosmetic reversal. 'The user quoted my lesson back at me' is
    the moment the lesson is least needed, and it was the only moment the
    feature could fire.
    """

    def test_a_verbatim_slice_of_the_body_does_not_fire_by_itself(
        self, db_session, agent
    ):
        scar = _scar(db_session, agent_id=agent["id"])
        recital = "discards every uncommitted change in it, including work"
        assert recital in BODY
        # The old relation fires on exactly this input...
        assert len(_old_relation_matches(
            db_session, agent_id=agent["id"], term=recital
        )) == 1

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=recital
        )

        # ... and the new one does not, because the recital names neither
        # keyword.
        assert result["count"] == 0
        assert _fired_count_of(db_session, scar.id) == 0


class TestTheCoincidenceChannelIsClosed:
    """The other half of the defect: firing when nothing happened."""

    @pytest.mark.parametrize("phrase", COINCIDENCE_PHRASES)
    def test_an_ordinary_english_phrase_does_not_fire(
        self, db_session, agent, phrase
    ):
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            body=COINCIDENCE_BODY,
            keywords=["guard design", "dangerous case"],
        )

        # POSITIVE CONTROL FIRST: the old predicate DOES match this phrase
        # against this row, so the fixture really is the dangerous case.
        assert len(_old_relation_matches(
            db_session, agent_id=agent["id"], term=phrase
        )) == 1, f"fixture is inert for {phrase!r} - the zero below proves nothing"

        try:
            result = svc.consult_scars(
                db_session, agent_id=agent["id"], situation=phrase
            )
        except svc.ConsultError as exc:
            # A phrase below the caller's length floor never reaches the
            # service at all. Refusal is also "did not fire"; what must not
            # happen is a match.
            assert exc.code == "situation_required"
        else:
            assert result["count"] == 0

        assert _fired_count_of(db_session, scar.id) == 0

    def test_one_shared_ordinary_word_is_not_enough(self, db_session, agent):
        """Measured over one agent's 109 live scars, the bare keyword 'tests'
        was hit by 7 unrelated lessons and 'verification' by 9. One shared word
        is coincidence; the conjunction is the mechanism."""
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            keywords=["migration", "alembic"],
        )

        one_word = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="should I write a migration for this change?",
        )
        assert one_word["count"] == 0
        assert _fired_count_of(db_session, scar.id) == 0

        # THE PAIRED STATE WHERE IT MUST COME BACK NON-ZERO. Without this the
        # assertion above is satisfied by the row being unreachable.
        both = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="should I write an alembic migration for this change?",
        )
        assert both["count"] == 1
        assert _fired_count_of(db_session, scar.id) == 1


class TestTheHolesAreReportedRatherThanSilent:
    """A row that CANNOT match and a row that DID NOT match are different
    facts, and only one of them is about the situation."""

    def test_a_scar_with_no_keywords_is_counted_as_unmatchable(
        self, db_session, agent
    ):
        scar = _scar(db_session, agent_id=agent["id"], keywords=None)

        result = svc.consult_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 0
        assert result["considered"] == 1
        assert result["unmatchable"] == 1
        assert _fired_count_of(db_session, scar.id) == 0

    def test_a_keyword_of_nothing_but_stopwords_never_matches(
        self, db_session, agent
    ):
        """THE ONE PLACE THIS DESIGN COULD HAVE REINTRODUCED A BLANKET MATCH.

        A keyword whose tokens are all stopwords reduces to an empty
        requirement, and an empty requirement is a subset of every situation -
        it would fire the row on any prompt at all. Empty must mean NO MATCH,
        never trivially satisfied.
        """
        scar = _scar(
            db_session, agent_id=agent["id"], keywords=["the", "of the", "a"]
        )

        assert svc.keyword_token_set(scar) == frozenset()
        result = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="the thing of the other thing and a third",
        )
        assert result["count"] == 0
        assert result["unmatchable"] == 1
        assert _fired_count_of(db_session, scar.id) == 0

    def test_a_partially_present_keyword_does_not_count(self, db_session, agent):
        """'stale inbox file' matching on 'file' alone is the single-common-word
        rule one level down. EVERY token of a keyword has to be there."""
        scar = _scar(
            db_session,
            agent_id=agent["id"],
            keywords=["stale inbox file", "teammate name"],
        )

        partial = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="open the file and tell me the name of it",
        )
        assert partial["count"] == 0

        whole = svc.consult_scars(
            db_session,
            agent_id=agent["id"],
            situation="the stale inbox file has the wrong teammate name in it",
        )
        assert whole["count"] == 1


class TestMatchScarsCannotFire:
    """The measurement half must be structurally incapable of promoting
    anything, not merely trusted not to.

    Same ruling that moved firing out of `scored_memory()`: a flag is a thing a
    future caller gets wrong by omission, where a function with no write in it
    cannot be gotten wrong at all. A forward instrument pointed at the live
    store runs this, and a false fire at SCAR_FIRED_THRESHOLD promotes a scar
    to CORE, which has no demotion path.
    """

    def test_matching_writes_nothing(self, db_session, agent):
        scar = _scar(db_session, agent_id=agent["id"])

        result = svc.match_scars(
            db_session, agent_id=agent["id"], situation=SITUATION
        )

        assert result["count"] == 1, "the probe must still be measuring something"
        assert _fired_count_of(db_session, scar.id) == 0
        assert db_session.get(AgentMemory, scar.id).last_reinforced_session_id is None

    def test_match_scars_contains_no_call_to_the_write_site(self):
        """Structural, because the behavioural test above passes for a
        `match_scars` that fires and then rolls back, and a future edit could
        add the call without any test noticing."""
        tree = ast.parse(inspect.getsource(svc))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "match_scars"
        )
        called = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_fire" not in called, called

        # POSITIVE CONTROL: the same walk over `consult_scars` MUST find it.
        # Without this the assertion above passes against a parser that found
        # no calls at all.
        consult = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "consult_scars"
        )
        consult_calls = {
            n.func.id
            for n in ast.walk(consult)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_fire" in consult_calls, consult_calls


class TestTheBodyIsNoLongerSearched:
    """A guard on the property rather than on today's implementation: nothing
    in the consultation path may read `AgentMemory.body`.

    It is worth pinning because the old relation is the obvious thing to reach
    for when recall feels low, and reinstating it as a fallback would reopen
    the coincidence channel while every test above stayed green.
    """

    def test_no_like_against_body_in_memory_consult(self):
        source = (APP_DIR / "services" / "memory_consult.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"like", "ilike", "contains"}:
                    target = node.func.value
                    assert not (
                        isinstance(target, ast.Attribute) and target.attr == "body"
                    ), (
                        f"memory_consult.py matches against AgentMemory.body at "
                        f"line {node.lineno} - that is the relation DWB-644 "
                        f"inverted"
                    )


class TestFiredThreeTimesIsNowReachable:
    """DWB-644 CRITERION 4, SETTLED AS A TEST RATHER THAN AS A SENTENCE.

    `memory_promote.maybe_promote_scar` sends a scar to CORE at
    `SCAR_FIRED_THRESHOLD` firings. Before this ticket that trigger had never
    run anywhere, and it could not: `consult_scars` was the only writer of
    `fired_count`, and its match could only be satisfied by a user reciting a
    lesson verbatim. The journal-to-CORE path was the only automatic route into
    CORE that had ever executed.

    The chain is live and ungated apart from the mode: `consolidate_agent` runs
    `maybe_promote_scar` over every scar-family candidate as its first
    movement, and `hook_tracking.handle_session_start` calls
    `consolidate_agent` for every human_memory project with a resolved agent.
    So this test drives the two halves it owns - firing through the
    consultation, then the consolidation pass - and asserts the promotion lands
    for the fired-three-times reason specifically rather than for the
    context-liveness one that shares the function.
    """

    def test_three_consultations_promote_the_scar_to_core(self, db_session, agent):
        from app.services import memory_consolidate, memory_promote

        scar = _scar(db_session, agent_id=agent["id"])
        assert memory_promote.SCAR_FIRED_THRESHOLD == 3

        for expected in (1, 2, 3):
            svc.consult_scars(
                db_session, agent_id=agent["id"], situation=SITUATION
            )
            assert _fired_count_of(db_session, scar.id) == expected

        # Before the pass it is still a scar: promotion is consolidation's
        # decision, not the consultation's.
        assert db_session.get(AgentMemory, scar.id).tier == MemoryTier.scar

        result = memory_consolidate.consolidate_agent(
            db_session, agent_id=agent["id"]
        )

        assert (scar.id, "fired_three_times") in result.promoted_scars, (
            result.promoted_scars
        )
        db_session.expire_all()
        assert db_session.get(AgentMemory, scar.id).tier == MemoryTier.core

    def test_two_consultations_do_not_promote(self, db_session, agent):
        """The paired state. Without it the test above is satisfied by a
        consolidation pass that promotes everything it is handed."""
        from app.services import memory_consolidate

        scar = _scar(db_session, agent_id=agent["id"], context_key="DWB-644")
        for _ in range(2):
            svc.consult_scars(
                db_session, agent_id=agent["id"], situation=SITUATION
            )
        assert _fired_count_of(db_session, scar.id) == 2

        memory_consolidate.consolidate_agent(db_session, agent_id=agent["id"])

        db_session.expire_all()
        assert db_session.get(AgentMemory, scar.id).tier == MemoryTier.scar
