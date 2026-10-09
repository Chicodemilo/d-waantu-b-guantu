# Path: tests/test_keyword_subject_rule_dwb669.py
# File: test_keyword_subject_rule_dwb669.py
# Created: 2026-10-09 (DWB-669)
# Purpose: Guard the subject rule - that it refuses every keyword demonstrated
#          firing on an unrelated sentence, spares every keyword that carries a
#          subject, and cuts at the exact pair that decides whether it is too
#          wide or too narrow.
# Caller: pytest
# Callees: app.services.keyword_reachability, app.services.memory_consult,
#          POST /api/agents/{id}/memories
# Data In: the handed-over known-positive and known-negative sets
# Data Out: assertions on the rule and on the live refusal
# Last Modified: 2026-10-09 (DWB-669)

"""DWB-669: a rule that cannot find a known positive passes its own sweep.

THE KNOWN POSITIVES BELOW WERE HANDED OVER BY TWO AGENTS WHO DELIBERATELY DID
NOT FIX ANYTHING WITH THEM. That is the whole reason they are worth having: a
denylist built from whichever controls happened to trip reads as complete to
whoever holds it, and three people produced one before anyone produced a rule.
Each entry here was demonstrated firing on a real unrelated sentence.

THE DISCRIMINATOR IS `new column` AGAINST `new file`, and it is the only test in
this file that can fail in BOTH directions. `new` carries no subject and is in
the list; `column` names a thing and is not. A rule that refuses `new column` has
become too wide. One that spares `what is left` and `right now` is too narrow.
`before i edit` is the same test on the other axis: it clears the floor alone,
two of its three tokens are in the list, and it must PASS because `edit` names
the thing.
"""

import pytest

from app.services import memory_consult
from app.services.keyword_reachability import (
    KeywordUnreachable,
    fires_without_subject,
    require_subject_bearing_keywords,
)

# Every one demonstrated firing on a real unrelated sentence.
KNOWN_POSITIVES = [
    "before i", "show me", "every agent", "all agents", "what is left",
    "right now", "same file", "both files", "every write", "writing up",
    "hand over", "line range", "new file", "on its own", "two of us",
    "double check", "same result", "read the code", "what gets served",
    "one line", "one shot", "found nothing", "second scan", "ran twice",
    "common case", "never taken", "same answer", "sign off", "ground truth",
    "current shape", "already correct", "write it down", "read the output",
    "new prose", "how many", "go and look", "still true",
]

MUST_PASS = [
    "git checkout", "shared tree", "sprint close", "alembic downgrade",
    "working tree", "mutation test", "code review", "row lock",
    # The two discriminators. See the module docstring.
    "before i edit", "new column",
]


class TestTheRuleFindsEveryKnownPositive:
    @pytest.mark.parametrize("keyword", KNOWN_POSITIVES)
    def test_refused(self, keyword):
        assert fires_without_subject(keyword), (
            f"{keyword!r} was demonstrated firing on an unrelated sentence and "
            "the rule does not catch it. A rule that cannot find a known "
            "positive passes its own sweep perfectly."
        )


class TestTheRuleSparesEveryKeywordThatCarriesASubject:
    @pytest.mark.parametrize("keyword", MUST_PASS)
    def test_passes(self, keyword):
        assert not fires_without_subject(keyword), (
            f"{keyword!r} carries a subject word and must pass. If the rule "
            "refuses it the rule is too wide, not the keyword."
        )

    def test_the_discriminating_pair(self):
        """`new file` refuses and `new column` passes, on the same `new`."""
        assert fires_without_subject("new file")
        assert not fires_without_subject("new column")


class TestBothConditionsAreLoadBearing:
    def test_a_single_token_keyword_is_not_refused_however_ordinary(self):
        """Condition 1. A keyword below the floor cannot fire without a second
        keyword agreeing, so it is a different defect and is not this rule's."""
        for ordinary in ("check", "gate", "test", "report", "file"):
            assert not fires_without_subject(ordinary)

    def test_condition_one_alone_would_delete_the_working_corpus(self):
        """Why the list is needed. EVERY two-word keyword clears the floor
        alone, including every one that has ever fired correctly here, so the
        'fires unaided' frame on its own refuses the entire corpus."""
        for good in ("git checkout", "shared tree", "sprint close"):
            tokens = memory_consult._keyword_tokens(good)
            assert len(tokens) >= memory_consult._MATCH_TOKENS_REQUIRED
            assert not fires_without_subject(good)

    def test_the_floor_itself_is_untouched(self):
        """DWB-669 removes a route; it does not retune a measurement. DWB-644
        settled that raising the floor narrows coincidence and real recall
        identically."""
        assert memory_consult._MATCH_TOKENS_REQUIRED == 2


class TestTheRefusalTeaches:
    def test_it_names_the_keyword_and_shows_a_passing_one(self):
        with pytest.raises(KeywordUnreachable) as e:
            require_subject_bearing_keywords(["git checkout", "before i"])
        detail = e.value.detail
        assert e.value.code == "keyword_fires_without_subject"
        assert "'before i'" in detail
        assert "index 1" in detail
        assert "before i edit" in detail and "new column" in detail
        assert "not narrowing" in detail

    def test_a_clean_set_raises_nothing(self):
        assert require_subject_bearing_keywords(["git checkout", "shared tree"]) is None


class TestTheGateRefusesItOnTheRealEndpoint:
    def test_a_write_carrying_a_subjectless_keyword_is_refused(
        self, client, db_session, make_project, make_agent
    ):
        from app.models.agent_memory import AgentMemory
        from app.models.project import MemoryMode, Project

        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()
        agent = make_agent(project_id=project["id"])
        opened = client.post(
            "/api/sessions/open",
            json={"project_id": project["id"], "open_method": "slash"},
        )
        assert opened.status_code in (200, 201), opened.text

        r = client.post(
            f"/api/agents/{agent['id']}/memories",
            json={
                "body": "ping the owner before you edit a file they are in",
                "condensed": "announce an edit before you make it",
                # The junk keyword APPEARS IN THE SITUATION, which is the point:
                # DWB-667's check would pass it, because an author who writes
                # `before i` writes "before I" in the sentence beside it.
                "keywords": ["before i", "their file"],
                "situation": "before i edit their file I should say something",
            },
        )
        assert r.status_code == 400, r.text
        assert "fires on ANY sentence" in r.json()["detail"], r.text
        db_session.expire_all()
        assert (
            db_session.query(AgentMemory)
            .filter(AgentMemory.agent_id == agent["id"])
            .count()
            == 0
        )
