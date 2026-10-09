# Path: tests/test_keyword_reachability_dwb667.py
# File: test_keyword_reachability_dwb667.py
# Created: 2026-10-09 (DWB-667)
# Purpose: Guard the write-time reachability contract and the rekey route. The
#          gate must be the SAME comparison retrieval makes, the matcher must
#          stay untouched, and rekey must repair an index without ever revising
#          a lesson.
# Caller: pytest
# Callees: app.services.keyword_reachability, app.services.memory_consult,
#          app.services.memory_fill, POST /api/agents/{id}/memories,
#          POST /api/agents/{id}/memories/{mid}/rekey
# Data In: test DB rows via the factory fixtures
# Data Out: assertions on refusals, on the persisted row, and on the AST
# Last Modified: 2026-10-09 (DWB-667)

"""DWB-667: the gate is only worth anything if it IS retrieval.

288 live scars were stored with keywords nobody would type. They passed
DWB-657's gate, which asks whether the field was SUPPLIED, and nothing asked
whether it could ever be reached. Supplied-but-dead and blank are the same
outcome - a lesson correctly stored and never served - and only one was refused.

THE LOAD-BEARING TEST IN THIS FILE IS `TestTheGateIsRetrieval`. Everything else
checks that particular refusals fire. That class checks the property the whole
design rests on: a write that CLEARS the gate is afterwards RECALLED by the
situation it cleared it with, measured by calling `match_scars` - production's
own matcher, on the real row, through the real endpoint. A gate that refused
all the right payloads and still admitted rows the matcher cannot find would
pass every other test here and be worthless.

AND THE MIRROR OF IT, WHICH IS THE PART A PASSING TEST USUALLY HIDES: the same
class takes a payload that DIFFERS ONLY IN THE KEYWORDS, confirms the gate
refuses it, and confirms that the one the gate accepted and the one it refused
answer differently under the matcher. A test that only exercised the happy path
would pass against a gate that accepted everything.

`TestTheMatcherIsUntouched` is a tripwire rather than a test of this ticket.
`_MATCH_TOKENS_REQUIRED = 2` is the entire false-fire defence - zero junk fired
across 30 live probes - and the tempting way to make any recall number look
better is to lower it. A false fire can reach CORE at the promotion threshold,
and DWB-665 establishes that CORE has no demotion path, so that mistake is
permanent. Anyone lowering it has to delete this test and say why.
"""

import ast
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from app.services import keyword_reachability, memory_consult

SERVICE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "keyword_reachability.py"
)

# A payload that clears the gate. Keywords 'git checkout' and 'shared tree'
# contribute four tokens, every one of which is in the situation line.
REACHABLE = {
    "body": "reverting a file with git on an uncommitted tree destroys other "
    "people's work, because git's undo is relative to the last COMMIT",
    "condensed": "copy the file aside and restore from the copy, never git checkout",
    "keywords": ["git checkout", "shared tree"],
    "situation": "I want to undo my edit with git checkout on a shared tree "
    "nobody has committed today",
}

# The same lesson, filed rather than described. These are the shapes the live
# store is full of.
FILING_LABELS = ["revert-semantics", "uncommitted-loss"]


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


def _count(db_session, agent_id) -> int:
    db_session.expire_all()
    return (
        db_session.query(AgentMemory).filter(AgentMemory.agent_id == agent_id).count()
    )


class TestTheGateIsRetrieval:
    """The property the design rests on, and its mirror."""

    def test_a_write_that_clears_the_gate_is_recalled_by_its_own_situation(
        self, client, db_session, make_project, make_agent
    ):
        """Not "the gate accepted it" - "the matcher finds it afterwards".

        Measured by calling `match_scars`, which is the function the live
        consultation calls, against the row the endpoint actually stored. If
        this ever fails while the refusal tests still pass, the gate has drifted
        away from the comparison it is supposed to be.
        """
        agent_id = _writer(client, db_session, make_project, make_agent)
        r = client.post(
            f"/api/agents/{agent_id}/memories",
            json={**REACHABLE, "cost": "high"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["tier"] == MemoryTier.scar.value, r.text
        assert r.json()["situation"] == REACHABLE["situation"]

        db_session.expire_all()
        result = memory_consult.match_scars(
            db_session, agent_id=agent_id, situation=REACHABLE["situation"]
        )
        assert result["count"] == 1, result
        assert result["unmatchable"] == 0, result
        assert result["entries"][0].id == r.json()["id"]

    def test_the_refused_payload_differs_only_in_the_keywords(
        self, client, db_session, make_project, make_agent
    ):
        """The discrimination. Same body, same condensed, same situation.

        Without this, every refusal test in the file is compatible with a gate
        that refuses everything, and the happy-path test above is compatible
        with a gate that accepts everything. The pair is what distinguishes the
        correct implementation from both plausible wrong ones.
        """
        agent_id = _writer(client, db_session, make_project, make_agent)
        refused = client.post(
            f"/api/agents/{agent_id}/memories",
            json={**REACHABLE, "keywords": FILING_LABELS},
        )
        assert refused.status_code == 400, refused.text
        assert _count(db_session, agent_id) == 0

        accepted = client.post(f"/api/agents/{agent_id}/memories", json=REACHABLE)
        assert accepted.status_code == 201, accepted.text
        assert _count(db_session, agent_id) == 1

    def test_the_label_set_would_not_have_been_recalled_either(self, db_session):
        """The gate's refusal and the matcher's silence are the same fact.

        Asserted directly against `match_scars`' predicate rather than inferred
        from the refusal, so this still holds if the gate's message changes.
        """
        tokens = memory_consult._tokenize(REACHABLE["situation"])
        probe = keyword_reachability._KeywordsOnly(FILING_LABELS)
        assert memory_consult.matching_keywords(probe, tokens) == []


class TestTheMatcherIsUntouched:
    """A tripwire. DWB-667 forbids buying recall by loosening the comparison."""

    def test_two_distinct_tokens_are_still_required(self):
        assert memory_consult._MATCH_TOKENS_REQUIRED == 2, (
            "_MATCH_TOKENS_REQUIRED was lowered. That is the entire false-fire "
            "defence: zero junk fired across 30 live probes with it at 2, and a "
            "false fire reaches CORE at the promotion threshold, which DWB-665 "
            "proves has no way back. Raising a recall number by loosening this "
            "is the one fix DWB-667 rules out in advance."
        )

    def test_the_gate_owns_no_tokenizer_stopword_list_or_match_rule(self):
        """Structural. The gate must BE the matcher, not resemble it.

        A second definition of "what counts as a token" would drift, and the
        drift would be invisible: both copies keep returning a plausible answer,
        and the only symptom is a lesson that silently never fires. So the
        module may not define these names at all - it imports them.
        """
        tree = ast.parse(SERVICE_PATH.read_text())
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assigned = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for forbidden in (
            "_tokenize",
            "_keyword_tokens",
            "_SITUATION_STOPWORDS",
            "_MATCH_TOKENS_REQUIRED",
            "matching_keywords",
            "keyword_token_set",
        ):
            assert forbidden not in defined | assigned, (
                f"keyword_reachability defines its own {forbidden}. It must "
                "import the matcher's, so the write gate and retrieval cannot "
                "answer differently."
            )

    def test_the_stand_in_is_not_an_orm_row(self):
        """It carries `keywords` and nothing else, so it cannot be persisted and
        cannot be read as a write site by DWB-637's writer guard."""
        probe = keyword_reachability._KeywordsOnly(["a b"])
        assert probe.keywords == ["a b"]
        assert not isinstance(probe, AgentMemory)
        with pytest.raises(AttributeError):
            probe.tier = MemoryTier.scar


class TestEachRefusalIsItsOwnClaim:
    """Four different things can be wrong and they are different answers."""

    def test_a_missing_situation_is_refused_and_names_what_the_line_is_for(
        self, client, db_session, make_project, make_agent
    ):
        agent_id = _writer(client, db_session, make_project, make_agent)
        payload = {k: v for k, v in REACHABLE.items() if k != "situation"}
        r = client.post(f"/api/agents/{agent_id}/memories", json=payload)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "situation is required" in detail, detail
        assert "git checkout" in detail, detail
        assert "self-exempt" in detail, detail
        assert _count(db_session, agent_id) == 0

    def test_a_blank_situation_is_refused_like_a_missing_one(
        self, client, db_session, make_project, make_agent
    ):
        agent_id = _writer(client, db_session, make_project, make_agent)
        r = client.post(
            f"/api/agents/{agent_id}/memories", json={**REACHABLE, "situation": "   "}
        )
        assert r.status_code == 400, r.text
        assert "situation is required" in r.json()["detail"]
        assert _count(db_session, agent_id) == 0

    def test_a_filing_label_names_the_keyword_and_the_tokens_it_needed(
        self, client, db_session, make_project, make_agent
    ):
        """The refusal has to be actionable. "unreachable" with no subject
        tells an author nothing it can act on."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        r = client.post(
            f"/api/agents/{agent_id}/memories",
            json={**REACHABLE, "keywords": ["git checkout", "revert-semantics"]},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "revert-semantics" in detail, detail
        assert "'revert'" in detail and "'semantics'" in detail, detail
        # The keyword that DID match is not blamed.
        assert "'git checkout' needs" not in detail, detail
        assert _count(db_session, agent_id) == 0

    def test_a_set_under_the_token_floor_is_refused_as_impossible_not_as_a_miss(
        self, client, db_session, make_project, make_agent
    ):
        """One token can never reach the floor however the situation is
        phrased, so the refusal says so rather than blaming this situation."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        r = client.post(
            f"/api/agents/{agent_id}/memories",
            json={**REACHABLE, "keywords": ["collation"],
                  "situation": "the collation is making this comparison "
                               "case-insensitive"},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "could never be recalled by any situation" in detail, detail
        assert _count(db_session, agent_id) == 0

    def test_an_all_stopword_keyword_is_refused_before_the_situation_is_consulted(
        self, client, db_session, make_project, make_agent
    ):
        agent_id = _writer(client, db_session, make_project, make_agent)
        r = client.post(
            f"/api/agents/{agent_id}/memories",
            json={**REACHABLE, "keywords": ["is not the", "git checkout"]},
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "carries no matchable token" in detail, detail
        assert "index 0" in detail, detail
        assert _count(db_session, agent_id) == 0

    def test_dwb657_still_answers_first_when_both_are_wrong(
        self, client, db_session, make_project, make_agent
    ):
        """A request with no keywords at all is told about the keywords, not
        about reachability. Ordering is the deciding rule from DWB-657: tell the
        caller the thing it can fix, and tell it the simpler thing first."""
        agent_id = _writer(client, db_session, make_project, make_agent)
        payload = {k: v for k, v in REACHABLE.items() if k != "keywords"}
        r = client.post(
            f"/api/agents/{agent_id}/memories", json={**payload, "situation": ""}
        )
        assert r.status_code == 400, r.text
        assert "keywords is required" in r.json()["detail"], r.text


class TestRekeyRepairsAnIndexAndNeverRevisesALesson:
    """The route criterion 3 needs, and the constraints that make it safe."""

    def _dead_row(self, client, db_session, make_project, make_agent):
        """A scar carrying filing-label keywords, written straight to the DB.

        Not through the API, because the API now refuses exactly this shape -
        which is the point. These rows exist; they cannot be created any more.
        """
        project = make_project()
        db_session.get(Project, project["id"]).memory_mode = MemoryMode.human_memory
        db_session.flush()
        agent = make_agent(project_id=project["id"])
        row = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.scar,
            body="git's undo is relative to the last commit",
            condensed="copy the file aside and restore from the copy",
            keywords=list(FILING_LABELS),
            fired_count=4,
            source_journal_id=None,
        )
        db_session.add(row)
        db_session.flush()
        return agent["id"], row.id

    def test_an_owner_replaces_dead_keywords_and_the_row_becomes_reachable(
        self, client, db_session, make_project, make_agent
    ):
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        before = memory_consult.match_scars(
            db_session, agent_id=agent_id, situation=REACHABLE["situation"]
        )
        assert before["count"] == 0, before

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["previous_keywords"] == FILING_LABELS
        assert r.json()["keywords"] == REACHABLE["keywords"]

        db_session.expire_all()
        after = memory_consult.match_scars(
            db_session, agent_id=agent_id, situation=REACHABLE["situation"]
        )
        assert after["count"] == 1, after
        assert after["entries"][0].id == memory_id

    def test_the_lesson_and_its_history_survive(
        self, client, db_session, make_project, make_agent
    ):
        """A whole-row diff, not a field list - DWB-664's rule, because the
        columns this must not touch include ones added next month."""
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        db_session.expire_all()
        row = db_session.get(AgentMemory, memory_id)
        before = {c.name: getattr(row, c.name) for c in AgentMemory.__table__.columns}

        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 200, r.text

        db_session.expire_all()
        row = db_session.get(AgentMemory, memory_id)
        after = {c.name: getattr(row, c.name) for c in AgentMemory.__table__.columns}
        changed = {k for k in before if before[k] != after[k]}
        assert changed <= {"keywords", "situation", "updated_at"}, (
            f"rekey changed {sorted(changed)}. It may replace `keywords`, set "
            "`situation`, and move `updated_at` (the model's onupdate). "
            "Anything else - and `condensed` above all - is a lesson being "
            "revised by a route that exists to repair an index."
        )
        assert after["condensed"] == before["condensed"]
        assert after["fired_count"] == 4
        assert after["tier"] == MemoryTier.scar

    def test_a_stranger_cannot_rekey_someone_elses_row(
        self, client, db_session, make_project, make_agent
    ):
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        stranger = make_agent()
        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(stranger["id"])},
        )
        assert r.status_code == 403, r.text
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id).keywords == FILING_LABELS

    def test_rekey_refuses_a_replacement_that_is_also_unreachable(
        self, client, db_session, make_project, make_agent
    ):
        """There would be no sense repairing 288 dead pointers through a route
        that could store a dead one."""
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": ["another-coinage", "third-label"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 400, r.text
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id).keywords == FILING_LABELS

    def test_resending_the_same_keywords_is_refused_rather_than_answering_200(
        self, client, db_session, make_project, make_agent
    ):
        """Over a 288-row pass, "I repaired this" and "nothing happened" must
        not be the same response."""
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        ok = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert ok.status_code == 200, ok.text
        again = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert again.status_code == 409, again.text
        assert "already carries exactly these keywords" in again.json()["detail"]

    def test_condensed_is_not_a_field_on_this_route(
        self, client, db_session, make_project, make_agent
    ):
        """422, not a silently dropped key. A dropped `condensed` would be
        indistinguishable from an honoured one at the call site."""
        agent_id, memory_id = self._dead_row(
            client, db_session, make_project, make_agent
        )
        r = client.post(
            f"/api/agents/{agent_id}/memories/{memory_id}/rekey",
            json={
                "keywords": REACHABLE["keywords"],
                "situation": REACHABLE["situation"],
                "condensed": "a revision smuggled in through the index route",
            },
            headers={"X-Agent-ID": str(agent_id)},
        )
        assert r.status_code == 422, r.text
        assert any(
            e["type"] == "extra_forbidden" for e in r.json()["detail"]
        ), r.text
