# Path: tests/test_journal_dwb587.py
# File: test_journal_dwb587.py
# Created: 2026-09-29 (DWB-587)
# Purpose: Guard the journal - that no route returns it whole, that every
#          retrieval is counted and no caller can suppress that, and that the
#          count has exactly one writer and no reader that decays it.
# Caller: pytest
# Callees: POST/GET /api/journal, app.services.journal, ast over app/
# Data In: test DB rows via the factory fixtures; the app source tree
# Data Out: Assertions on responses, on persisted counts, and on write sites
# Last Modified: 2026-09-29 (DWB-587)

"""DWB-587 acceptance, spec section 5.

The three acceptance criteria are structural claims about what the code CANNOT
do, so most of this file asserts over the real source tree rather than over
behaviour. Behavioural tests prove the increment happens on the paths someone
thought to test; the AST guards prove there is no second path.

Every absence assertion here first proves it can see something. A scan that
finds zero write sites because it was pointed at the wrong tree reports exactly
what a correct implementation reports, and that failure family - a check that
tells you it RAN rather than that it LANDED - is the one this sprint keeps
hitting.
"""

import ast
import pathlib

import pytest

from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def journal_agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


def _post(client, agent_id, body, **kwargs):
    r = client.post(
        "/api/journal", json={"agent_id": agent_id, "body": body, **kwargs}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _count_of(db_session, entry_id):
    db_session.expire_all()
    return db_session.get(JournalEntry, entry_id).retrieval_count


class TestNoFullDump:
    """AC3: no endpoint returns the whole journal."""

    def test_get_with_no_filters_is_refused_and_names_the_filters(self, client):
        r = client.get("/api/journal")
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        # Names what to supply, not just "bad request".
        for name in journal_svc.REQUIRED_FILTERS:
            assert name in detail, f"refusal does not name {name!r}: {detail}"

    def test_agent_id_alone_does_not_satisfy_the_filter_requirement(
        self, client, journal_agent
    ):
        """Scoping a dump to one agent is still a dump.

        This is the loophole worth closing explicitly: agent_id is the most
        natural thing for a caller to reach for, it FEELS like a filter, and it
        returns that agent's entire journal.
        """
        r = client.get("/api/journal", params={"agent_id": journal_agent["id"]})
        assert r.status_code == 422, r.text

    def test_a_page_size_does_not_satisfy_the_filter_requirement(self, client):
        """Stated in the AC: "A default page size does not satisfy this."

        Page one of everything is still a read nobody asked a question to get.
        """
        r = client.get("/api/journal", params={"limit": 10})
        assert r.status_code == 422, r.text

    def test_no_route_exposes_the_journal_without_a_filter(self):
        """The refusal above guards ONE route. This guards the route list.

        A second journal route added later - a convenience listing, a debug
        dump, an export - would leave every test above passing while defeating
        the rule they exist to enforce.
        """
        from app.main import app

        journal_routes = {
            (r.path, method)
            for r in app.routes
            if "journal" in getattr(r, "path", "")
            for method in getattr(r, "methods", set())
        }
        assert journal_routes, "no journal routes found; this check saw nothing"
        assert journal_routes == {
            ("/api/journal", "POST"),
            ("/api/journal", "GET"),
        }, (
            "the journal surface changed. A new route must be checked against "
            "spec section 5 (retrieval is never a full read) before this "
            "expectation is widened."
        )


class TestRetrievalIsCounted:
    """AC1: the count moves on every documented filter, and cannot be skipped."""

    # Every non-empty combination of the documented filters. Written as a
    # parametrization over the filter NAMES rather than a hand-listed set of
    # cases, so a filter added to REQUIRED_FILTERS without a matching branch
    # below fails loudly instead of going untested.
    @pytest.mark.parametrize(
        "combo",
        [
            c
            for n in range(1, 5)
            for c in __import__("itertools").combinations(
                journal_svc.REQUIRED_FILTERS, n
            )
        ],
        ids=lambda c: "+".join(c),
    )
    def test_every_filter_combination_increments(
        self, client, db_session, journal_agent, combo
    ):
        entry = _post(
            client,
            journal_agent["id"],
            "the ssh dropped mid-session and the shutdown never ran",
            tags=["ssh", "greg"],
        )
        before = _count_of(db_session, entry["id"])

        params = {"agent_id": journal_agent["id"]}
        for name in combo:
            if name == "tags":
                params["tags"] = ["ssh"]
            elif name == "date_from":
                params["date_from"] = "2000-01-01T00:00:00"
            elif name == "date_to":
                params["date_to"] = "2999-01-01T00:00:00"
            elif name == "term":
                params["term"] = "ssh dropped"
            else:
                pytest.fail(f"no query branch for documented filter {name!r}")

        r = client.get("/api/journal", params=params)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["count"] == 1, payload
        assert _count_of(db_session, entry["id"]) == before + 1

    def test_the_response_carries_the_post_increment_count(
        self, client, db_session, journal_agent
    ):
        """The number in the response is the number in the database.

        Returning the pre-increment value would make the response disagree with
        the row about a figure whose entire job is to be counted, and the
        disagreement would be invisible to anyone reading only the response.
        """
        entry = _post(client, journal_agent["id"], "greg again", tags=["greg"])
        r = client.get("/api/journal", params={"tags": ["greg"]})
        returned = r.json()["entries"][0]
        assert returned["retrieval_count"] == _count_of(db_session, entry["id"])
        assert returned["retrieval_count"] == 1

    def test_no_query_parameter_suppresses_the_increment(
        self, client, db_session, journal_agent
    ):
        """Asserted over the endpoint's ACTUAL parameter list, not a guess.

        Reads the FastAPI route signature and replays the search once per
        declared parameter, so a parameter added later is covered the day it is
        added. A hand-written list of "parameters that must not suppress it"
        would pass forever while a new `count=false` sat beside it.
        """
        from app.main import app
        import inspect

        route = next(
            r
            for r in app.routes
            if getattr(r, "path", "") == "/api/journal" and "GET" in r.methods
        )
        params = [
            name
            for name in inspect.signature(route.endpoint).parameters
            if name != "db"
        ]
        assert params, "read no parameters off the route; this check saw nothing"

        entry = _post(client, journal_agent["id"], "suppression attempt", tags=["s"])
        benign = {
            "agent_id": journal_agent["id"],
            "tags": ["s"],
            "date_from": "2000-01-01T00:00:00",
            "date_to": "2999-01-01T00:00:00",
            "term": "suppression",
            "limit": 50,
        }
        expected = _count_of(db_session, entry["id"])
        for name in params:
            assert name in benign, (
                f"query parameter {name!r} is undocumented by this test. Add it "
                "with a value that still matches the seeded entry, and confirm "
                "it does not suppress the increment."
            )
            # Always carries a real filter as well, so the request is valid;
            # the parameter under test rides alongside it.
            r = client.get(
                "/api/journal", params={"tags": ["s"], name: benign[name]}
            )
            assert r.status_code == 200, (name, r.text)
            expected += 1
            assert _count_of(db_session, entry["id"]) == expected, (
                f"query parameter {name!r} suppressed the retrieval increment"
            )

    def test_rows_beyond_the_limit_are_not_counted(
        self, client, db_session, journal_agent
    ):
        """Only what was HANDED OVER is counted.

        A row that matched but fell outside the limit was not reached for, and
        counting it would inflate the promotion signal with entries nobody read.
        """
        entries = [
            _post(client, journal_agent["id"], f"batch entry {i}", tags=["batch"])
            for i in range(3)
        ]
        r = client.get("/api/journal", params={"tags": ["batch"], "limit": 1})
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["status"] == journal_svc.TRUNCATED
        assert payload["count"] == 1
        assert payload["total_matched"] == 3

        returned_id = payload["entries"][0]["id"]
        counted = [e["id"] for e in entries if _count_of(db_session, e["id"]) == 1]
        assert counted == [returned_id]

    def test_a_search_matching_nothing_is_complete_not_a_failure(
        self, client, journal_agent
    ):
        """An empty result must be distinguishable from a failure.

        Status `complete` plus the filters that ran says "asked this, matched
        nothing". A bare empty list says nothing at all, and that ambiguity is
        what let relevant_lessons return [] for a whole sprint unnoticed.
        """
        _post(client, journal_agent["id"], "something", tags=["present"])
        r = client.get("/api/journal", params={"tags": ["absent"]})
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["entries"] == []
        assert payload["status"] == journal_svc.COMPLETE
        assert payload["total_matched"] == 0
        assert payload["filters_applied"] == ["tags"]

    def test_a_tag_match_is_not_a_substring_match(
        self, client, db_session, journal_agent
    ):
        """`ssh` must not match the tag `ssh-config`, nor a body mentioning ssh.

        A LIKE over the serialized JSON would do both, and every false match
        inflates the retrieval count of an entry nobody reached for - which
        corrupts the promotion signal rather than merely returning noise.
        """
        wrong_tag = _post(
            client, journal_agent["id"], "about config", tags=["ssh-config"]
        )
        body_only = _post(client, journal_agent["id"], "ssh came up here", tags=["x"])
        right = _post(client, journal_agent["id"], "the real one", tags=["ssh"])

        r = client.get("/api/journal", params={"tags": ["ssh"]})
        ids = [e["id"] for e in r.json()["entries"]]
        assert ids == [right["id"]]
        assert _count_of(db_session, wrong_tag["id"]) == 0
        assert _count_of(db_session, body_only["id"]) == 0


class TestPromotionThreshold:
    """Three retrievals turn a story into a rule (spec section 5)."""

    def test_entry_becomes_a_promotion_candidate_at_three(
        self, client, journal_agent
    ):
        entry = _post(client, journal_agent["id"], "reached for often", tags=["p"])
        for expected in (1, 2, 3):
            r = client.get("/api/journal", params={"tags": ["p"]})
            returned = r.json()["entries"][0]
            assert returned["retrieval_count"] == expected
            assert returned["promotion_candidate"] is (
                expected >= journal_svc.PROMOTION_THRESHOLD
            )
        assert entry["promotion_candidate"] is False  # at write time, nothing yet

    def test_promotion_candidates_helper_uses_the_one_threshold(
        self, client, db_session, journal_agent
    ):
        """DWB-585 calls this rather than writing its own `>= 3`.

        Two copies of the threshold is how the system ends up with two numbers
        where the spec ruled there should be one.
        """
        entry = _post(client, journal_agent["id"], "candidate", tags=["c"])
        for _ in range(journal_svc.PROMOTION_THRESHOLD):
            client.get("/api/journal", params={"tags": ["c"]})
        candidates = journal_svc.promotion_candidates(
            db_session, agent_id=journal_agent["id"]
        )
        assert [c.id for c in candidates] == [entry["id"]]

    def test_threshold_is_three(self):
        """Pinned deliberately. Section 5: three is also the existing bit-twice
        threshold for working facts, "so the system has one number, not two".
        Changing it is a spec decision, not a tuning knob."""
        assert journal_svc.PROMOTION_THRESHOLD == 3


# ---------------------------------------------------------------------------
# AC2, the structural half: proved by reading the source, not by waiting.
# ---------------------------------------------------------------------------


def _python_sources() -> list[pathlib.Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _retrieval_count_writes() -> list[tuple[str, int]]:
    """Every place in app/ that WRITES journal_entries.retrieval_count.

    Three shapes count as a write: assigning to a `.retrieval_count` attribute,
    augmenting one, and passing `retrieval_count=` as a keyword to any call
    (which covers both `.values(retrieval_count=...)` and a constructor).

    The column DECLARATION in the model is an annotated assignment to a bare
    name, not to an attribute, so it is not a write site by this definition and
    needs no special-casing - which matters, because a special case is a place a
    real write could later hide.
    """
    sites: list[tuple[str, int]] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(APP_DIR.parent))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr == "retrieval_count":
                        sites.append((rel, node.lineno))
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "retrieval_count":
                        sites.append((rel, node.lineno))
    return sites


def _modules_mentioning(needle: str) -> list[pathlib.Path]:
    return [p for p in _python_sources() if needle in p.read_text(encoding="utf-8")]


class TestTheCountHasOneWriter:
    """AC2, second half: the retrieval path is retrieval_count's ONLY writer."""

    def test_the_scan_can_see_the_identifier_at_all(self):
        """Proves the guard below is not passing because it read nothing.

        An absence assertion over an empty tree reports exactly what a correct
        implementation reports. So before claiming "only one write", assert the
        scan reaches files, parses them, and finds the identifier in more than
        one place.
        """
        sources = _python_sources()
        assert len(sources) > 20, f"only scanned {len(sources)} files"
        mentions = _modules_mentioning("retrieval_count")
        assert len(mentions) >= 3, (
            "expected the model, the service and the schema to mention "
            f"retrieval_count; found {[str(m) for m in mentions]}"
        )

    def test_exactly_one_write_site_and_it_is_the_retrieval_path(self):
        sites = _retrieval_count_writes()
        assert len(sites) == 1, (
            "retrieval_count must have exactly one writer (spec section 5: the "
            f"count is permanent). Found: {sites}"
        )
        path, _line = sites[0]
        assert path == "app/services/journal.py", sites

    def test_the_one_write_only_increments(self):
        """A second guard on the same site, because "one writer" is not enough
        on its own: one writer that RESETS the count makes it decay, which is
        the property section 5 rules out ("the score is transient; the count is
        permanent"). Asserts the write is an increment expression, not an
        assignment of a literal."""
        source = (APP_DIR / "services" / "journal.py").read_text(encoding="utf-8")
        assert "retrieval_count=JournalEntry.retrieval_count + 1" in source, source
        for forbidden in ("retrieval_count=0", "retrieval_count = 0"):
            assert forbidden not in source, f"found a reset: {forbidden}"


class TestTheScoreDoesNotReadTheCount:
    """AC2, first half: no memory-scoring code reads retrieval_count.

    Scoped by what a module MENTIONS rather than by a module name, so DWB-585's
    scoring module is covered on the day it lands without anyone remembering to
    add it here. Section 5: the score is transient, the count is permanent -
    a score derived from the count would make the permanent thing decay.
    """

    def test_no_memory_tier_module_reads_retrieval_count(self):
        tier_modules = _modules_mentioning("MemoryTier")
        assert tier_modules, (
            "found no modules referencing MemoryTier; this check saw nothing and "
            "would pass against a tree with the feature deleted"
        )
        offenders = [
            str(p)
            for p in tier_modules
            if "retrieval_count" in p.read_text(encoding="utf-8")
        ]
        assert offenders == [], (
            "a module that works with memory tiers also reads retrieval_count. "
            "Spec section 5 rules the score transient and the count permanent; "
            "a score derived from the count decays it. Promotion candidates come "
            "from journal.promotion_candidates(), which owns the threshold. "
            f"Offenders: {offenders}"
        )


class TestMomentTagsAreNotOnTheJournal:
    """DWB-584 moved cost / caught_by / surprised onto agent_memories.

    Pinned here so the journal does not grow a second home for them. Spec
    section 7 opens by naming the failure mode as two stores that both look
    authoritative and disagree, and a tag written in both places is exactly
    that.
    """

    def test_journal_entries_does_not_carry_the_moment_tags(self):
        columns = set(JournalEntry.__table__.columns.keys())
        # Prove the introspection sees a real table before asserting absence.
        assert {"id", "agent_id", "tags", "retrieval_count", "body"} <= columns, (
            f"journal_entries did not introspect as expected: {sorted(columns)}"
        )
        assert {"cost", "caught_by", "surprised"}.isdisjoint(columns), sorted(columns)

    def test_the_create_endpoint_does_not_accept_them(self, client, journal_agent):
        """Extra keys must not be silently swallowed into a stored entry.

        Pydantic ignores unknown fields by default, so this asserts the entry
        comes back WITHOUT them rather than asserting a 422 that will not fire.
        """
        r = client.post(
            "/api/journal",
            json={
                "agent_id": journal_agent["id"],
                "body": "an entry",
                "cost": "high",
                "caught_by": "human",
                "surprised": True,
            },
        )
        assert r.status_code == 201, r.text
        returned = r.json()
        assert "cost" not in returned
        assert "caught_by" not in returned
        assert "surprised" not in returned


class TestSectionThreeDecayIsNotBuilt:
    """The scope note on the ticket, pinned so it cannot be quietly widened.

    Section 3's JOURNAL-retrieved curve (10, then 5 to 2 to 0) needs a
    last-retrieved session and the table stores only a count. Asserting the
    negative here is what stops a later reader adding the column under this
    ticket's name rather than minting a migration of its own.
    """

    def test_journal_entries_has_no_last_retrieved_column(self):
        columns = set(JournalEntry.__table__.columns.keys())
        # Prove the introspection sees a real table before asserting absence.
        assert {"id", "agent_id", "retrieval_count", "body", "entered_at"} <= columns, (
            f"journal_entries did not introspect as expected: {sorted(columns)}"
        )
        assert "last_retrieved_session_id" not in columns
        assert "last_retrieved_at" not in columns
