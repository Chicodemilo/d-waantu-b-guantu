# Path: tests/test_keyword_repair_suggestion_dwb689.py
# File: test_keyword_repair_suggestion_dwb689.py
# Created: 2026-10-28 (DWB-689)
# Purpose: Guard the repair the refusal offers. The suggestion must be the
#          KEYWORD-side one and never the situation-side one, must be re-gated
#          before it is offered, and must stay subordinate to widening the
#          situation.
# Caller: pytest
# Callees: app.services.keyword_reachability, app.services.memory_consult,
#          POST /api/agents/{id}/memories
# Data In: test DB rows via the factory fixtures
# Data Out: assertions on the refusal text, on the suggested set, and on what
#           the production matcher recalls afterwards
# Last Modified: 2026-10-28 (DWB-689)

"""DWB-689: two amendments pass this gate and only one survives retrieval.

The refusal already computes the missing tokens, so it is one step from naming
an amendment that would pass. There are two, and THE GATE CANNOT TELL THEM
APART: splice the missing tokens into the SITUATION, or drop them from the
KEYWORD. Both clear every predicate in `keyword_reachability`.

THE LOAD-BEARING TEST IN THIS FILE IS `TestTheTwoRepairsAreOppositeInEffect`.
Everything else checks that the suggestion appears, or does not, in the right
cases. That class checks the property the decision rests on - that the repair
being offered is recalled later and the one being withheld is not - measured
with `matching_keywords`, production's own predicate, against situations written
from the other end. A test that only asserted "a suggestion is present" would
pass just as happily against a version that suggested the situation amendment,
which is the exact change this ticket exists to refuse.

WHY THAT MIRROR MATTERS MORE THAN USUAL HERE. The thing being prevented is
invisible at write time: an amended-situation row PASSES, stores cleanly, and
reports nothing wrong. It fails only later, as silence, at a moment nobody is
watching. So the only test that can distinguish the correct implementation from
the tempting one is the pair that asks what each stored row recalls afterwards.
Asserting the gate's verdict cannot do it, because the verdicts are identical.

`TestAnIllegalSuggestionIsNeverEmitted` is the second-round-trip guard. The
mechanical repair is not always legal - it can fall below
`_MATCH_TOKENS_REQUIRED` or empty the set - and an unchecked suggestion in those
cases costs a second refusal, which is worse than the single round trip the
feature exists to save. Anyone removing the re-gate has to delete that class.
"""

import pytest

from app.models.agent_memory import AgentMemory
from app.models.project import MemoryMode, Project
from app.services import keyword_reachability, memory_consult

SUGGESTION_MARKER = "ONE SET THAT WOULD PASS"

# The inflection case, which is the failure class the module docstring names as
# THE LIMIT it cannot catch. Every keyword is concrete and situational; the
# author simply wrote `edit` where their own sentence says `edited`.
INFLECTED_KEYWORDS = ["ORM model edit", "alembic downgrade"]
AUTHOR_SITUATION = "I edited an ORM model and ran alembic autogenerate"

# Situations written from the other end - what someone else would type later,
# without having seen the keywords or the situation above.
LATER_SITUATIONS = [
    "I added a column to an ORM model and need a migration",
    "alembic autogenerate produced a drop_index I did not ask for",
    "editing the ORM model broke the test",
]


def _writer(client, db_session, make_project, make_agent):
    """An agent on a human_memory project with an open DWB session."""
    project = make_project()
    db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
    db_session.flush()
    agent = make_agent(project_id=project["id"])
    opened = client.post(
        "/api/sessions/open",
        json={"project_id": project["id"], "open_method": "slash"},
    )
    assert opened.status_code in (200, 201), opened.text
    return agent["id"]


def _refuse(client, agent_id, keywords, situation):
    """POST a write expected to be refused; return the refusal detail."""
    r = client.post(
        f"/api/agents/{agent_id}/memories",
        json={
            "body": "a lesson whose keywords this situation does not reach",
            "condensed": "the shape of the write is irrelevant to this gate",
            "keywords": keywords,
            "situation": situation,
        },
    )
    assert r.status_code == 400, r.text
    return r.json()["detail"]


def _recalls(keywords, situation):
    """What production's matcher finds, for a row carrying these keywords."""
    probe = keyword_reachability._KeywordsOnly(list(keywords))
    tokens = memory_consult._tokenize(situation)
    return memory_consult.matching_keywords(probe, tokens)


class TestTheTwoRepairsAreOppositeInEffect:
    """The property the whole ruling rests on, and the reason for the asymmetry.

    Both repairs satisfy the gate. Only one is recalled. If this class ever goes
    red while the suggestion tests below stay green, the thing being offered has
    drifted to the amendment that silently destroys recall.
    """

    SITUATION_AMENDED = AUTHOR_SITUATION + " edit downgrade"
    KEYWORD_REPAIRED = ["ORM model", "alembic"]

    def test_the_gate_cannot_tell_the_two_repairs_apart(self):
        """Both pass. This is why the gate's verdict cannot decide the question."""
        for keywords, situation in (
            (INFLECTED_KEYWORDS, self.SITUATION_AMENDED),
            (self.KEYWORD_REPAIRED, AUTHOR_SITUATION),
        ):
            keyword_reachability.require_subject_bearing_keywords(keywords)
            keyword_reachability.require_reachable_keywords(keywords, situation)

    @pytest.mark.parametrize("later", LATER_SITUATIONS)
    def test_the_offered_repair_is_recalled_and_the_withheld_one_is_not(self, later):
        """Measured on sentences written from the other end, not on the gate.

        The amended-situation row keeps the inflected keywords, so it matches
        nothing a later author would write. The keyword-repaired row matches.
        Same verdict above, opposite outcome here.
        """
        assert _recalls(INFLECTED_KEYWORDS, later) == [], (
            "the amended-situation repair must stay unreachable; if this passes, "
            "the inflection case has changed and the asymmetry needs re-measuring"
        )
        assert _recalls(self.KEYWORD_REPAIRED, later), (
            "the repair being offered must be the one that is recalled later"
        )

    def test_the_suggestion_is_the_keyword_repair_and_not_the_situation(
        self, client, db_session, make_project, make_agent
    ):
        """What the author is actually handed, through the real endpoint."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(client, agent_id, INFLECTED_KEYWORDS, AUTHOR_SITUATION)
        assert SUGGESTION_MARKER in detail, detail
        assert str(self.KEYWORD_REPAIRED) in detail, detail


class TestTheSuggestionNeverPutsWordsInTheAuthorsMouth:
    """The invariant, asserted on the suggestion rather than on its wording.

    Stated as a property so it survives every rewording of the message: a
    suggested keyword may only DELETE words the author wrote. It can never
    contain a token the author's own situation does not already supply, which is
    exactly what a situation amendment would require.
    """

    def test_every_suggested_token_is_already_in_the_authors_situation(self):
        repair = keyword_reachability._keyword_side_repair(
            INFLECTED_KEYWORDS, AUTHOR_SITUATION, INFLECTED_KEYWORDS
        )
        assert repair is not None
        situation_tokens = memory_consult._tokenize(AUTHOR_SITUATION)
        for keyword in repair:
            missing = memory_consult._keyword_tokens(keyword) - situation_tokens
            assert not missing, (
                f"suggested keyword {keyword!r} needs {sorted(missing)}, which "
                "the author never wrote - that is a situation amendment wearing "
                "a keyword's clothes"
            )

    def test_a_suggested_word_is_always_one_the_author_wrote(self):
        """No invention and no rewriting, only deletion."""
        repair = keyword_reachability._keyword_side_repair(
            INFLECTED_KEYWORDS, AUTHOR_SITUATION, INFLECTED_KEYWORDS
        )
        original_words = {w for k in INFLECTED_KEYWORDS for w in k.split()}
        for keyword in repair:
            for word in keyword.split():
                assert word in original_words, word

    def test_a_hyphenated_term_is_dropped_whole_rather_than_cut_to_a_fragment(self):
        """`self-exempt` must never be offered back as `self`."""
        keywords = ["self-exempt", "sprint close"]
        situation = "I am closing the sprint and wondering if the rule is self"
        repair = keyword_reachability._keyword_side_repair(
            keywords, situation, ["self-exempt"]
        )
        if repair is not None:
            assert "self" not in repair, repair


class TestAnIllegalSuggestionIsNeverEmitted:
    """The re-gate. A suggestion that would itself be refused costs a second
    round trip, which is worse than the one this feature exists to save."""

    def test_no_suggestion_when_the_repair_falls_below_the_token_floor(
        self, client, db_session, make_project, make_agent
    ):
        """`sprint close` + `gate status report` reduces to `['sprint']`."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(
            client,
            agent_id,
            ["sprint close", "gate status report"],
            "I am closing the sprint and the gates are failing",
        )
        assert SUGGESTION_MARKER not in detail, detail

    def test_no_suggestion_when_the_repair_empties_the_set(
        self, client, db_session, make_project, make_agent
    ):
        """Nothing the author wrote survives, so there is nothing to offer."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(
            client,
            agent_id,
            ["commit", "staged diff"],
            "I want to land this work on master",
        )
        assert SUGGESTION_MARKER not in detail, detail

    def test_any_suggestion_that_is_offered_actually_passes_the_gate(self):
        """The guarantee, asserted directly rather than through the message.

        Whatever `_keyword_side_repair` returns must survive BOTH predicates. A
        future edit that widens the repair without re-gating it fails here.
        """
        cases = [
            (INFLECTED_KEYWORDS, AUTHOR_SITUATION),
            (["sprint close", "gate status report"],
             "I am closing the sprint and the gates are failing"),
            (["commit", "staged diff"], "I want to land this work on master"),
            (["ORM model edit"], "I edited an ORM model"),
        ]
        offered = 0
        for keywords, situation in cases:
            tokens = memory_consult._tokenize(situation)
            probe = keyword_reachability._KeywordsOnly(keywords)
            matched = set(memory_consult.matching_keywords(probe, tokens))
            unreachable = [k for k in keywords if k not in matched]
            repair = keyword_reachability._keyword_side_repair(
                keywords, situation, unreachable
            )
            if repair is None:
                continue
            offered += 1
            keyword_reachability.require_subject_bearing_keywords(repair)
            keyword_reachability.require_reachable_keywords(repair, situation)
        assert offered, "no case offered a repair; the cases no longer test this"

    def test_the_inner_re_gate_cannot_recurse(self):
        """`_suggest=False` is what stops a suggestion for a suggestion."""
        with pytest.raises(keyword_reachability.KeywordUnreachable) as exc:
            keyword_reachability.require_reachable_keywords(
                INFLECTED_KEYWORDS, AUTHOR_SITUATION, _suggest=False
            )
        assert SUGGESTION_MARKER not in exc.value.detail


class TestTheSuggestionStaysSubordinate:
    """One option, not the fix. Widening the situation is still on the table."""

    def test_both_original_repair_routes_survive_alongside_the_suggestion(
        self, client, db_session, make_project, make_agent
    ):
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(client, agent_id, INFLECTED_KEYWORDS, AUTHOR_SITUATION)
        assert SUGGESTION_MARKER in detail
        assert "rewrite the keyword in the words you actually used" in detail
        assert "widen the situation if it was too narrow" in detail
        assert "offered as an option rather than as the answer" in detail

    def test_the_refusal_still_names_the_keyword_and_its_missing_tokens(
        self, client, db_session, make_project, make_agent
    ):
        """The suggestion is additive; it replaces nothing that was there."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(client, agent_id, INFLECTED_KEYWORDS, AUTHOR_SITUATION)
        assert "'ORM model edit' needs ['edit']" in detail, detail
        assert "'alembic downgrade' needs ['downgrade']" in detail, detail

    def test_the_other_refusals_carry_no_suggestion(
        self, client, db_session, make_project, make_agent
    ):
        """Only `keyword_unreachable` has a repair to offer.

        The subject rule runs first and is about a keyword that fires too
        widely; there is no smaller set that fixes it. The token floor is a
        structural impossibility. Neither has an amendment to name.
        """
        agent_id = _writer(client, db_session, make_project, make_agent)
        subject = _refuse(
            client,
            agent_id,
            ["before i", "handoff file"],
            "before i open the handoff file i want to know what changed",
        )
        assert SUGGESTION_MARKER not in subject, subject
        floor = _refuse(client, agent_id, ["the"], "I am looking at the file")
        assert SUGGESTION_MARKER not in floor, floor


class TestNothingIsStoredByARefusedWrite:
    """The suggestion path runs extra code inside the refusal; it must not
    acquire a side effect on the way."""

    def test_a_refusal_that_carries_a_suggestion_still_writes_no_row(
        self, client, db_session, make_project, make_agent
    ):
        agent_id = _writer(client, db_session, make_project, make_agent)
        detail = _refuse(client, agent_id, INFLECTED_KEYWORDS, AUTHOR_SITUATION)
        assert SUGGESTION_MARKER in detail
        db_session.expire_all()
        assert (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent_id)
            .count()
            == 0
        )
