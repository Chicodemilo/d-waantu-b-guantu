# Path: backend/tests/test_condensed_keywords_gate_dwb657.py
# File: test_condensed_keywords_gate_dwb657.py
# Created: 2026-10-08
# Purpose: DWB-657 - POST /api/agents/{id}/memories refuses a write that omits
#          or blanks `condensed` or `keywords`, and the REFUSAL TEACHES. The
#          error text is the deliverable on this ticket, so it is asserted here
#          rather than left to drift.
# Caller: pytest
# Callees: POST /api/agents/{id}/memories, app.services.raw_memory
# Data In: factory-created project/agent/session via conftest fixtures
# Data Out: assertions on status codes, refusal text, and the persisted row
# Last Modified: 2026-10-08 (DWB-657: created)

"""DWB-657: the condensed + keywords write gate.

WHY THE ERROR TEXT IS UNDER TEST AND NOT JUST THE STATUS CODE.

The ticket's deliverable is the sentence, not the check - a refusal that teaches
lives next to the code, where it cannot drift away from the rule it describes.
But "lives next to the code" is only true while someone keeps it there. A later
edit that trims the message to "condensed is required" would leave every
status-code assertion green while destroying the thing the ticket was for. So
the properties the message must have are asserted: it names the field, it says
what the field is FOR, and it shows a body that would be accepted.

ON THE BLANK PREDICATE, which is where the interesting bug lives.

`len(keywords) > 0` is the obvious check and it passes `[""]` - a payload that
means exactly what `[]` means, nobody supplied keywords, while answering the
check the same way a real list does. The dangerous case answering identically to
the safe one is the defect family this lane keeps producing, so every blank
shape is enumerated below and each one is asserted to be refused.
"""

import json

import pytest

from app.models.agent_memory import AgentMemory

GOOD = {
    "body": "the full lesson in your own words",
    "condensed": "verify against a source you did not produce",
    "keywords": ["verification", "false-green"],
    "cost": "low",
    "caught_by": "me",
}


def _without(key):
    return {k: v for k, v in GOOD.items() if k != key}


@pytest.fixture
def writer(client, make_project, make_agent):
    """An agent on a project with an OPEN DWB session.

    The session is a precondition of any write here (DWB-637), so without it
    every case below would 400 for the WRONG reason and the suite would be
    green while testing nothing. Asserted, not assumed - see the happy-path
    test, which is what proves this fixture actually permits a write.
    """
    # BORN in human_memory rather than switched into it: this endpoint IS the
    # human_memory store, so a stock project is the wrong substrate. Creating
    # with the mode is allowed; SWITCHING one later needs confirmation
    # (DWB-588) and would be a heavier fixture for no gain.
    #
    # This is load-bearing and was found by a positive control, not by reading:
    # `GET /memory/scored` on a stock project returns 200 with
    # `computed: false, reason: project_not_in_human_memory_mode` and an EMPTY
    # entries list, so a bare status assertion there passes while measuring
    # nothing.
    project = make_project(memory_mode="human_memory")
    agent = make_agent(project_id=project["id"])
    r = client.post(
        "/api/sessions/open",
        json={"project_id": project["id"], "open_method": "slash"},
    )
    assert r.status_code in (200, 201), r.text
    return agent


class TestTheHappyPathStillWorks:
    """The positive control for every refusal below.

    Without this, a gate that refused EVERYTHING would pass the whole refusal
    suite. This is what makes the 400s mean "refused for the stated reason"
    rather than "this endpoint is broken".
    """

    def test_a_complete_write_is_accepted_and_both_fields_persist(
        self, client, db_session, writer
    ):
        r = client.post(f"/api/agents/{writer['id']}/memories", json=GOOD)
        assert r.status_code == 201, r.text

        # RE-READ THE ROW. The response is not the evidence: this whole lane
        # exists because a 200 can describe a write that did not happen, and
        # `priority` rode three tickets into nothing on exactly that trust.
        db_session.expire_all()
        row = db_session.get(AgentMemory, r.json()["id"])
        assert row.condensed == GOOD["condensed"]
        assert row.keywords == GOOD["keywords"]

    def test_the_response_echoes_what_was_stored(self, client, writer):
        """A write response that omitted two columns it had just stored would be
        a quiet version of the defect this gate exists to prevent."""
        r = client.post(f"/api/agents/{writer['id']}/memories", json=GOOD)
        assert r.status_code == 201, r.text
        assert r.json()["condensed"] == GOOD["condensed"]
        assert r.json()["keywords"] == GOOD["keywords"]


class TestCondensedIsRequired:
    @pytest.mark.parametrize(
        "payload,label",
        [
            (_without("condensed"), "omitted"),
            ({**GOOD, "condensed": None}, "null"),
            ({**GOOD, "condensed": ""}, "empty string"),
            ({**GOOD, "condensed": "   \t  "}, "whitespace only"),
        ],
        ids=["omitted", "null", "empty", "whitespace"],
    )
    def test_refused_with_400(self, client, writer, payload, label):
        r = client.post(f"/api/agents/{writer['id']}/memories", json=payload)
        assert r.status_code == 400, f"{label}: {r.text}"

    def test_the_refusal_teaches(self, client, writer):
        """The three properties the ticket asks for, asserted separately so a
        trimmed message fails on the specific thing it lost."""
        r = client.post(f"/api/agents/{writer['id']}/memories", json=_without("condensed"))
        detail = r.json()["detail"]
        assert "condensed" in detail, detail                      # names the field
        assert "NOT THE SETUP" in detail, detail                  # says what it is FOR
        assert '"condensed":' in detail, detail                   # shows a correct body
        assert '"keywords": ["verification"' in detail, detail

    def test_nothing_is_stored_on_a_refusal(self, client, db_session, writer):
        """Paired with its own positive control, because 'count == 0' cannot
        distinguish 'nothing was written' from 'this query matches nothing'."""
        before = db_session.query(AgentMemory).filter_by(agent_id=writer["id"]).count()
        r = client.post(f"/api/agents/{writer['id']}/memories", json=_without("condensed"))
        assert r.status_code == 400, r.text
        db_session.expire_all()
        after = db_session.query(AgentMemory).filter_by(agent_id=writer["id"]).count()
        assert after == before

        # POSITIVE CONTROL: the same query DOES move when a write lands, so the
        # equality above is a measured absence rather than a blind query.
        assert client.post(
            f"/api/agents/{writer['id']}/memories", json=GOOD
        ).status_code == 201
        db_session.expire_all()
        assert (
            db_session.query(AgentMemory).filter_by(agent_id=writer["id"]).count()
            == before + 1
        ), "the count used to prove nothing was stored does not move when something is"


class TestKeywordsIsRequired:
    @pytest.mark.parametrize(
        "payload,label",
        [
            (_without("keywords"), "omitted"),
            ({**GOOD, "keywords": None}, "null"),
            ({**GOOD, "keywords": []}, "empty list"),
            ({**GOOD, "keywords": [""]}, "single blank"),
            ({**GOOD, "keywords": ["   "]}, "single whitespace"),
            ({**GOOD, "keywords": ["", "  "]}, "all blank"),
        ],
        ids=["omitted", "null", "empty_list", "blank", "whitespace", "all_blank"],
    )
    def test_refused_with_400(self, client, writer, payload, label):
        """`[""]` is the case that matters: it has len 1, so the obvious
        non-empty check would pass it while it means exactly what `[]` means."""
        r = client.post(f"/api/agents/{writer['id']}/memories", json=payload)
        assert r.status_code == 400, f"{label}: {r.text}"

    def test_a_mixed_list_is_refused_and_names_the_blank_index(self, client, writer):
        """Dropping the blank and keeping the rest would store a shorter list
        than the author wrote without saying so - the silent-drop shape."""
        r = client.post(
            f"/api/agents/{writer['id']}/memories",
            json={**GOOD, "keywords": ["real", "", "also real"]},
        )
        assert r.status_code == 400, r.text
        assert "index [1]" in r.json()["detail"], r.text

    def test_the_refusal_teaches(self, client, writer):
        r = client.post(f"/api/agents/{writer['id']}/memories", json=_without("keywords"))
        detail = r.json()["detail"]
        assert "keywords" in detail, detail
        assert "JSON ARRAY" in detail, detail          # array, not a comma string
        assert "MATCH ON" in detail, detail            # says what they are FOR
        assert '"keywords": ["verification"' in detail, detail


class TestCountIsGuidanceNotALimit:
    """Stated explicitly so the decision is inherited rather than rediscovered.

    The acceptance criteria refuse missing or blank and say nothing about a
    range; "two or three" is carried in the message as guidance. If that is ever
    made a limit, these two tests are what must change, and they are named so
    the next reader finds them."""

    @pytest.mark.parametrize("kws", [["one"], ["a", "b", "c", "d"]], ids=["one", "four"])
    def test_accepted(self, client, writer, kws):
        r = client.post(f"/api/agents/{writer['id']}/memories", json={**GOOD, "keywords": kws})
        assert r.status_code == 201, r.text

    def test_the_guidance_is_still_in_the_message(self, client, writer):
        detail = client.post(
            f"/api/agents/{writer['id']}/memories", json=_without("keywords")
        ).json()["detail"]
        assert "Two or three" in detail, detail


class TestAMalformedRequestAnswersDifferentlyFromAnIncompleteOne:
    """422 and 400 are different answers on purpose and both must keep working.

    A misspelled key is a MALFORMED request and pydantic refuses it as an
    undeclared key (DWB-651) before the service runs. An omitted key is a
    COMPLETE request that did not do the work, and that is the one that earns
    the teaching 400. Documented for agents, so asserted here.
    """

    def test_a_misspelled_field_is_422_not_400(self, client, writer):
        r = client.post(
            f"/api/agents/{writer['id']}/memories",
            json={**_without("condensed"), "condense": "typo"},
        )
        assert r.status_code == 422, r.text
        assert any(e["type"] == "extra_forbidden" for e in r.json()["detail"]), r.text

    def test_keywords_as_a_string_is_422_not_400(self, client, writer):
        r = client.post(
            f"/api/agents/{writer['id']}/memories", json={**GOOD, "keywords": "a,b"}
        )
        assert r.status_code == 422, r.text


class TestExistingNullRowsAreUnaffected:
    """AC4: the gate is on WRITES. The 831 rows that predate the columns, and
    anything else carrying NULL, must keep reading."""

    def _legacy_row(self, client, db_session, writer):
        """A row carrying NULL in both new columns.

        Built by writing through the REAL endpoint and then clearing the two
        columns, rather than by constructing an AgentMemory directly. Direct
        construction has to invent `tier`, which is NOT NULL and is normally
        DERIVED at insert, so a hand-built row is not the shape a pre-gate row
        actually has - it would be testing a fixture rather than the thing.
        """
        r = client.post(f"/api/agents/{writer['id']}/memories", json=GOOD)
        assert r.status_code == 201, r.text
        row = db_session.get(AgentMemory, r.json()["id"])
        row.condensed = None
        row.keywords = None
        db_session.flush()
        return row

    def test_a_null_carrying_row_still_reads_back(self, client, db_session, writer):
        legacy = self._legacy_row(client, db_session, writer)
        legacy_id = legacy.id

        db_session.expire_all()
        again = db_session.get(AgentMemory, legacy_id)
        assert again is not None, "the legacy row vanished"
        assert again.condensed is None
        assert again.keywords is None
        # It is a real row, not an empty one: the gate is on WRITES and must not
        # have touched what was already stored.
        assert again.body == GOOD["body"]
        assert again.tier is not None

    def test_the_scored_read_tolerates_null_rows(self, client, db_session, writer):
        self._legacy_row(client, db_session, writer)
        r = client.get(f"/api/agents/{writer['id']}/memory/scored")
        assert r.status_code == 200, r.text
        # Positive control: the read returned something, so a tolerant 200 is
        # not a 200 over an empty result that would pass however broken it was.
        assert r.json()["entries"], r.text
