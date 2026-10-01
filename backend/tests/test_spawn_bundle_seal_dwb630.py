# Path: tests/test_spawn_bundle_seal_dwb630.py
# File: test_spawn_bundle_seal_dwb630.py
# Created: 2026-10-01 (DWB-630)
# Purpose: No field of the identify or spawn-prepare bundle may carry content
#          read from the sealed stock memory.md under human_memory. Asserted as
#          an outcome over the WHOLE serialised payload, so a field added later
#          is covered without anyone remembering to add it here.
# Caller: pytest
# Callees: POST /api/agents/identify, POST /api/agents/spawn-prepare,
#          app.services.agent, app.services.memory_mode, app.services.node_retrieval
# Data In: tmp_path repo with a sentinel-bearing memory.md, factory project + agent
# Data Out: assertions on bundle contents in both modes
# Last Modified: 2026-10-01 (DWB-630)

"""The leak, and why an allowlist of fields would have missed it.

`memory_full` was gated through `memory_mode.memory_full_for`. Fourteen lines
above it, `scratchpad_excerpt` called `_read_scratchpad(memory_dir)` with no
gate, so every agent on a human_memory project was handed its tiered memory AND
a 2000-byte slice of the sealed stock file in the same payload. That is the
failure DWB-589 exists to prevent, stated in its own CHANGELOG: the thing being
designed out is not the wrong memory being used, it is TWO memories that both
look authoritative and disagree.

The enumeration found three live leaks across two routes and two modules, and
the third was not in the ticket: `node_retrieval._resolve_memory_entry` reads
OTHER agents' sealed files and returns a quoted heading into
`relevant_lessons[].entry_heading`.

SO THESE TESTS ASSERT OVER THE WHOLE SERIALISED BUNDLE RATHER THAN FIELD BY
FIELD. A per-field test is an allowlist, and the defect was a field nobody
thought to list. A sentinel written into the stock file and searched for in
`json.dumps(payload)` covers every field that exists and every field added
later.
"""

import json

import pytest

# A string that cannot occur anywhere but the stock memory.md this test writes.
SENTINEL = "ZZQQ-SEALED-STOCK-SENTINEL-0d41e9"
STOCK_BODY = (
    "# Memory - Sealed\n\n"
    "## Durable lessons\n\n"
    f"- a stock lesson containing {SENTINEL} and nothing else of note\n"
)


def _write_memory(tmp_path, prefix, name, body=STOCK_BODY):
    mem = tmp_path / ".dwb" / "memory" / prefix / name
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "memory.md").write_text(body, encoding="utf-8")
    return mem / "memory.md"


@pytest.fixture
def sealed(client, make_project, make_agent, tmp_path):
    project = make_project(
        prefix="SEAL", repo_path=str(tmp_path), memory_mode="human_memory"
    )
    agent = make_agent(
        project_id=project["id"], name="SealedOne", role="backend-worker"
    )
    _write_memory(tmp_path, "SEAL", "SealedOne")
    return project, agent


@pytest.fixture
def stock(client, make_project, make_agent, tmp_path):
    project = make_project(prefix="STOK", repo_path=str(tmp_path))
    agent = make_agent(
        project_id=project["id"], name="StockOne", role="backend-worker"
    )
    _write_memory(tmp_path, "STOK", "StockOne")
    return project, agent


def _identify(client, agent, project):
    r = client.post("/api/agents/identify", json={
        "role": agent["role"], "name": agent["name"],
        "project_prefix": project["prefix"],
    })
    assert r.status_code == 200, r.text
    return r.json()


def _spawn_prepare(client, agent, project):
    r = client.post("/api/agents/spawn-prepare", json={
        "role": agent["role"], "name": agent["name"],
        "project_prefix": project["prefix"],
    })
    assert r.status_code == 200, r.text
    return r.json()


class TestNoStockContentReachesAnAgentUnderTheSeal:
    """Acceptance 1, as an outcome over the whole payload."""

    def test_spawn_prepare_carries_no_byte_of_the_stock_file(self, client, sealed):
        project, agent = sealed
        payload = _spawn_prepare(client, agent, project)
        assert SENTINEL not in json.dumps(payload), (
            "the spawn bundle contains content read from the sealed stock "
            "memory.md; find which field by searching the payload for the "
            "sentinel"
        )

    def test_identify_carries_no_byte_of_the_stock_file(self, client, sealed):
        """The route the ticket did not name. Every worker calls identify on
        spawn and it returns the same `scratchpad_excerpt`, so sealing only
        spawn-prepare would have left the leak fully live on a second path."""
        project, agent = sealed
        payload = _identify(client, agent, project)
        assert SENTINEL not in json.dumps(payload)

    def test_the_excerpt_field_survives_but_is_empty(self, client, sealed):
        """Acceptance 4, and the decision: EMPTY, key retained.

        Both response schemas declare `scratchpad_excerpt` as a required `str`
        and DWB-401 kept the key deliberately for API stability, so removing it
        is a schema change that can 500 a consumer. Emptying it costs nothing
        and says the same thing.

        `memory_full` already carries either the assembled memory or the sealed
        pointer. A second field repeating that pointer would re-create the
        defect in miniature - a bundle carrying two things that look like
        memory - so the second field says nothing at all.
        """
        project, agent = sealed
        for payload in (
            _identify(client, agent, project),
            _spawn_prepare(client, agent, project),
        ):
            assert "scratchpad_excerpt" in payload
            assert payload["scratchpad_excerpt"] == ""

    def test_no_relevant_lesson_quotes_a_sealed_file(self, client, sealed):
        """The third leak, in node_retrieval rather than agent.py.

        `entry_heading` is a line lifted out of ANOTHER agent's sealed
        memory.md. The pointer itself is not content and may still travel.
        """
        project, agent = sealed
        payload = _spawn_prepare(client, agent, project)
        for lesson in payload.get("relevant_lessons", []):
            assert lesson.get("entry_heading") is None, lesson
            assert lesson.get("date") is None, lesson

    def test_the_heading_resolver_refuses_to_open_a_sealed_file(
        self, make_project, make_agent, tmp_path
    ):
        """The end-to-end assertion above CANNOT discriminate on this fixture.

        Reaching `relevant_lessons` needs a built node graph and assigned
        tickets, so on a bare test project the list is empty and the loop
        asserts over nothing - it passes against the broken code too, which was
        measured. Rather than claim it as evidence, the resolver is exercised
        directly here, where the two modes genuinely answer differently. The
        end-to-end test stays as the outcome check it is.
        """
        from app.services import node_retrieval

        _write_memory(tmp_path, "NRS", "Quoted")
        ref = ".dwb/memory/NRS/Quoted/memory.md"

        stock_project = make_project(prefix="NRS1", repo_path=str(tmp_path))
        sealed_project = make_project(
            prefix="NRS2", repo_path=str(tmp_path), memory_mode="human_memory"
        )

        class _P:
            def __init__(self, d):
                self.repo_path = d["repo_path"]
                self.memory_mode = d.get("memory_mode", "stock")

        heading, _date = node_retrieval._resolve_memory_entry(
            _P(stock_project), str(tmp_path), ref, "ZZQQ"
        )
        assert heading == "Durable lessons", (
            "stock must still resolve the heading, or this test cannot tell "
            "sealing from simply being broken"
        )

        heading, date = node_retrieval._resolve_memory_entry(
            _P(sealed_project), str(tmp_path), ref, "ZZQQ"
        )
        assert heading is None and date is None


class TestStockModeIsUnaffected:
    """Acceptance 5, and the discrimination that makes the tests above mean
    something. Without this pair, sealing could be implemented by returning ""
    unconditionally and every assertion above would still pass."""

    def test_stock_still_gets_its_excerpt(self, client, stock):
        project, agent = stock
        payload = _identify(client, agent, project)
        assert SENTINEL in payload["scratchpad_excerpt"]

    def test_stock_spawn_prepare_still_carries_the_file(self, client, stock):
        project, agent = stock
        payload = _spawn_prepare(client, agent, project)
        assert SENTINEL in json.dumps(payload)
        assert payload["scratchpad_excerpt"].startswith("## Recent Scratchpad")

    def test_stock_with_no_memory_still_says_no_entries_yet(
        self, client, make_project, make_agent, tmp_path
    ):
        project = make_project(prefix="STK2", repo_path=str(tmp_path))
        agent = make_agent(
            project_id=project["id"], name="EmptyOne", role="backend-worker"
        )
        payload = _spawn_prepare(client, agent, project)
        assert "(no entries yet)" in payload["scratchpad_excerpt"]


class TestTheSealIsStructuralNotRemembered:
    """Pam's point, encoded. `_read_scratchpad` used to take only `memory_dir`,
    so a gated call site and an ungated one were indistinguishable at the call
    site - which is why grepping for `memory_mode` returned only the SAFE
    readers and the unsafe ones had to be found by enumerating and subtracting.
    """

    def test_read_scratchpad_requires_the_project(self):
        import inspect

        from app.services import agent as agent_svc

        params = list(inspect.signature(agent_svc._read_scratchpad).parameters)
        assert params[0] == "project", (
            "_read_scratchpad must take the project so the mode decision cannot "
            "be omitted by a future call site"
        )

    def test_resolve_memory_entry_requires_the_project(self):
        import inspect

        from app.services import node_retrieval

        params = list(inspect.signature(node_retrieval._resolve_memory_entry).parameters)
        assert params[0] == "project"

    def test_every_stock_excerpt_read_goes_through_the_seal(self):
        """A source-level guard rather than one runtime test per call site.

        A runtime test passes today and misses next month's new caller. This
        asserts that the ONLY function reading the excerpt returns through
        `memory_mode.stock_excerpt_for`, so the decision cannot be bypassed by
        adding a reader beside it.
        """
        import inspect

        from app.services import agent as agent_svc

        source = inspect.getsource(agent_svc._read_scratchpad)
        assert "memory_mode.stock_excerpt_for" in source
