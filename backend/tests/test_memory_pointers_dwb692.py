# Path: tests/test_memory_pointers_dwb692.py
# File: test_memory_pointers_dwb692.py
# Created: 2026-10-28 (DWB-692)
# Purpose: Guard the mode-aware memory grounding. A human_memory project must
#          be indexed from its LIVE rows; a stock project must still be indexed
#          from its files and must not be touched; and the ref must keep the
#          source agent resolvable.
# Caller: pytest
# Callees: app.services.memory_pointers, app.services.node_touch,
#          app.services.node_retrieval
# Data In: test DB rows via the factory fixtures
# Data Out: assertions on the units produced, the ref shape, and attribution
# Last Modified: 2026-10-28 (DWB-692)

"""DWB-692: the index pointed at frozen files and nothing pointed at the corpus.

Measured on 2026-10-28: 3,479 memory-kind pointers across 15 distinct refs,
every one a `.md` path, ZERO referencing a row, while 1,221 live
`agent_memories` rows were indexed by nothing. The provider ran, succeeded and
returned units the whole time, so nothing ever errored.

THE LOAD-BEARING CLASS IS `TestStockIsNotTouched`. Four projects - CI, D2J, RVP,
GSF - have real, current content in those files, and for them the FILE IS THE
LIVE CORPUS and the old provider is exactly right; CI's were written two days
before this was built. A global swap would have broken four working projects to
fix three. Every other test here passes against an implementation that swaps the
provider unconditionally; that class is the only thing that does not.

`TestTheRefKeepsTheAgent` is the quiet-wrong-answer guard.
`node_retrieval._agent_from_memory_ref` takes the PARENT DIRECTORY of a ref, so
a bare row id would have yielded `source_agent: null` on every lesson - no
error, no empty list, just an unattributed answer that looks like data.
"""

import inspect

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.project import MemoryMode, Project
from app.services import memory_pointers, node_retrieval, node_touch


def _human_memory_project(db_session, make_project, tmp_path):
    project = make_project(repo_path=str(tmp_path))
    row = db_session.get(Project, project["id"])
    row.memory_mode = MemoryMode.human_memory
    db_session.flush()
    return row


def _add_memory(db_session, agent_id, condensed, tier=MemoryTier.scar, body="b"):
    row = AgentMemory(
        agent_id=agent_id, tier=tier, body=body,
        condensed=condensed, keywords=["x y"],
    )
    db_session.add(row)
    db_session.flush()
    return row


class TestHumanMemoryIsGroundedOnRows:

    def test_one_unit_per_row_carrying_the_condensed_line(
        self, db_session, make_project, make_agent, tmp_path
    ):
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        _add_memory(db_session, agent["id"], "always read the whole file first")
        _add_memory(db_session, agent["id"], "a green suite can mean unreachable")

        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert len(units) == 2
        assert {u.text for u in units} == {
            "always read the whole file first",
            "a green suite can mean unreachable",
        }
        assert all(u.kind == "memory" for u in units)

    def test_the_body_is_never_indexed(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """`condensed` only. Indexing bodies is 13x the pointers, not 4x."""
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        _add_memory(db_session, agent["id"], "the condensed line",
                    body="a much longer body with DISTINCTIVEBODYTOKEN in it")
        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert len(units) == 1
        assert "DISTINCTIVEBODYTOKEN" not in units[0].text

    def test_a_row_with_no_condensed_line_is_skipped_not_backfilled(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """Pre-DWB-657 rows. Falling back to `body` would index a different
        field for part of the corpus, undetectably at every later read."""
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        _add_memory(db_session, agent["id"], None, body="has a body only")
        _add_memory(db_session, agent["id"], "   ", body="blank condensed")
        _add_memory(db_session, agent["id"], "a real line")
        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert [u.text for u in units] == ["a real line"]

    def test_raw_rows_are_not_indexed(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """`raw` is the untiered state before consolidation has judged it."""
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        _add_memory(db_session, agent["id"], "untiered", tier=MemoryTier.raw)
        _add_memory(db_session, agent["id"], "tiered", tier=MemoryTier.scar)
        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert [u.text for u in units] == ["tiered"]

    def test_another_projects_rows_are_not_indexed(
        self, db_session, make_project, make_agent, tmp_path
    ):
        p = _human_memory_project(db_session, make_project, tmp_path)
        mine = make_agent(project_id=p.id)
        _add_memory(db_session, mine["id"], "mine")
        other = _human_memory_project(db_session, make_project, tmp_path)
        theirs = make_agent(project_id=other.id)
        _add_memory(db_session, theirs["id"], "theirs")

        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert [u.text for u in units] == ["mine"]


class TestStockIsNotTouched:
    """The constraint the whole change hangs on."""

    def test_a_stock_project_still_reads_its_files(
        self, db_session, make_project, make_agent, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path))
        p = db_session.get(Project, project["id"])
        agent = make_agent(project_id=p.id)
        # A row exists and must be IGNORED: on stock, the file is the corpus.
        _add_memory(db_session, agent["id"], "a row that must not be indexed")

        mem_dir = tmp_path / ".dwb" / "memory" / p.prefix / "Someone"
        mem_dir.mkdir(parents=True)
        (mem_dir / "memory.md").write_text("## A heading\n\nfile content here\n")

        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert len(units) == 1
        assert "file content here" in units[0].text
        assert "a row that must not be indexed" not in units[0].text
        assert units[0].ref.endswith("memory.md")

    def test_stock_delegates_to_the_original_provider(self):
        """Not a reimplementation of the file sweep - the same function."""
        src = inspect.getsource(memory_pointers.memory_provider)
        assert "node_touch.memory_provider(db, project, repo_path)" in src

    def test_a_human_memory_project_with_files_still_uses_rows(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """THE DISCRIMINATING PAIR for mode-awareness. Same files on disk,
        same rows in the table; only `memory_mode` differs."""
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        _add_memory(db_session, agent["id"], "the live row")
        mem_dir = tmp_path / ".dwb" / "memory" / p.prefix / "Someone"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "memory.md").write_text("## H\n\nthe frozen file\n")

        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        assert [u.text for u in units] == ["the live row"]


class TestTheRefKeepsTheAgent:
    """A bare row id would yield source_agent: null on every lesson."""

    def test_the_retrieval_helper_reads_the_agent_out_of_a_row_ref(
        self, db_session, make_project, make_agent, tmp_path
    ):
        p = _human_memory_project(db_session, make_project, tmp_path)
        agent = make_agent(project_id=p.id)
        row = _add_memory(db_session, agent["id"], "a lesson")
        units = memory_pointers.memory_provider(db_session, p, str(tmp_path))
        ref = units[0].ref

        assert node_retrieval._agent_from_memory_ref(ref) == agent["name"], (
            "retrieval could not recover the author from this ref, so every "
            "lesson would be delivered unattributed"
        )
        assert memory_pointers.memory_id_from_ref(ref) == row.id

    def test_a_file_ref_is_not_mistaken_for_a_row_ref(self):
        assert memory_pointers.memory_id_from_ref(
            ".dwb/memory/DWB/Stan/memory.md"
        ) is None
        assert memory_pointers.memory_id_from_ref("") is None

    def test_the_ref_shape_is_stable(self):
        ref = memory_pointers.row_ref("DWB", "Benny", 1732)
        assert ref == "agent_memories/DWB/Benny/1732"
        assert node_retrieval._agent_from_memory_ref(ref) == "Benny"
        assert memory_pointers.memory_id_from_ref(ref) == 1732


class TestTheOverrideIsRegistered:
    """Registration is a best-effort import side effect, so a silent failure
    looks identical in source to success. Assert the effect, not the call."""

    def test_the_memory_domain_resolves_to_this_module(self):
        saved = dict(node_touch._PROVIDER_OVERRIDES)
        try:
            memory_pointers._register_provider()
            resolved = node_touch._providers()["memory"]
            assert resolved is memory_pointers.memory_provider
        finally:
            node_touch._PROVIDER_OVERRIDES.clear()
            node_touch._PROVIDER_OVERRIDES.update(saved)

    def test_app_startup_imports_this_module(self):
        """The import in main.py is the only thing that arms the override."""
        main_src = inspect.getsource(__import__("app.main", fromlist=["x"]))
        assert "memory_pointers" in main_src


class TestFailureIsContained:

    def test_a_provider_failure_returns_empty_rather_than_raising(
        self, db_session, make_project, tmp_path, monkeypatch
    ):
        """Provider contract: best-effort. A grounding failure must not take
        down a nodeify run."""
        p = _human_memory_project(db_session, make_project, tmp_path)

        def boom(*a, **k):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(memory_pointers, "_row_units", boom)
        assert memory_pointers.memory_provider(db_session, p, str(tmp_path)) == []
