# Path: tests/test_nodes_phase1_gaps_dwb533.py
# File: test_nodes_phase1_gaps_dwb533.py
# Created: 2026-09-15
# Purpose: DWB-533 sprint test ticket for S80 Nodes Phase 1 (DWB-522..527). Fills
#          the gaps the per-ticket suites left: node_registry error paths + prune
#          scope + result counters + noise filter; node_match ordering / isolation
#          / neighbor derivation at the service level; node_touch default providers,
#          provider registry, touch_memory best-effort paths, nodeify resilience;
#          code_pointers deletions / walk caps / bad-sha degradation / provider
#          ticket filter; doc_pointers enumeration rules + degradation; node_retrieval
#          helpers + state filters + breadth-first interleave + grouping; nodes
#          router validation + response shapes.
# Caller: pytest
# Callees: app/services/node_registry, node_match, node_touch, code_pointers,
#          doc_pointers, node_retrieval; app/routers/nodes
# Data In: pytest fixtures (client, db_session, make_project, make_agent,
#          make_ticket, tmp_path, monkeypatch)
# Data Out: assertions
# Last Modified: 2026-09-15 (DWB-545: additive score field, one-per-file code group)

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.node import Node, NodePointer, NodePointerKind
from app.models.project import Project
from app.services import code_pointers as cp
from app.services import doc_pointers as dp
from app.services import node_match
from app.services import node_registry as nr
from app.services import node_retrieval
from app.services import node_touch
from app.services.node_registry import (
    NodeRegistryError,
    RegistrationResult,
    SourceUnit,
    _is_noise_tag,
    node_tokens,
    register_sources,
)


# --- shared helpers -----------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_providers():
    """Snapshot/clear/restore nodeify's provider overrides so the rich DWB-525/526
    providers (registered at import) never leak into or out of these tests."""
    saved = dict(node_touch._PROVIDER_OVERRIDES)
    node_touch._PROVIDER_OVERRIDES.clear()
    yield
    node_touch._PROVIDER_OVERRIDES.clear()
    node_touch._PROVIDER_OVERRIDES.update(saved)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "Tester")
    _git(r, "config", "commit.gpgsign", "false")
    return r


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    fp = repo / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _nodes(db, pid):
    return db.execute(select(Node).where(Node.project_id == pid)).scalars().all()


def _tags(db, pid):
    return {n.tag for n in _nodes(db, pid)}


def _pointers(db, pid, tag=None):
    q = select(NodePointer).where(NodePointer.project_id == pid)
    if tag is not None:
        q = q.where(NodePointer.tag == tag)
    return db.execute(q).scalars().all()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _mem_ref(prefix: str, agent: str) -> str:
    return f".dwb/memory/{prefix}/{agent}/memory.md"


def _ticket(make_ticket, prefix: str, n: int, **overrides):
    """make_ticket with an AGREEING ticket_number/ticket_key pair (DWB-529
    validates the two as one fact; the shared factory's default key disagrees)."""
    return make_ticket(ticket_number=n, ticket_key=f"{prefix}-{n}", **overrides)


# =============================================================================
# node_registry (DWB-522)
# =============================================================================

class TestRegistryErrorsAndCounters:
    def test_invalid_kind_raises_coded_error(self, db_session, make_project):
        p = make_project()
        with pytest.raises(NodeRegistryError) as ei:
            register_sources(db_session, p["id"], [
                SourceUnit(kind="bogus", ref="x", text="tokenizer"),
            ])
        assert ei.value.code == "invalid_kind"
        assert "bogus" in ei.value.detail

    @pytest.mark.parametrize("bad_ref", ["", "   "])
    def test_empty_ref_raises_coded_error(self, db_session, make_project, bad_ref):
        p = make_project()
        with pytest.raises(NodeRegistryError) as ei:
            register_sources(db_session, p["id"], [
                SourceUnit(kind="memory", ref=bad_ref, text="tokenizer"),
            ])
        assert ei.value.code == "invalid_ref"

    def test_prune_scope_only_call_ungrounds_node(self, db_session, make_project):
        """touch_memory's empty-file path: no units, just a prune scope."""
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="memory", ref="mem-1", text="tokenizer"),
            SourceUnit(kind="code", ref="x.py", text="tokenizer", sha="a", line_start=1, line_end=1),
        ])
        assert "tokenizer" in _tags(db_session, p["id"])
        res = register_sources(db_session, p["id"], [], prune_scope={("memory", "mem-1")})
        assert res.scope_refs == 1
        assert "tokenizer" in res.pruned_tags
        assert _tags(db_session, p["id"]) == set()
        assert _pointers(db_session, p["id"]) == []

    def test_pointers_written_counts_only_grounded_batch_pointers(self, db_session, make_project):
        p = make_project()
        res = register_sources(db_session, p["id"], [
            SourceUnit(kind="memory", ref="mem-1", text="tokenizer"),
            SourceUnit(kind="code", ref="x.py", text="tokenizer lonely"),
        ])
        assert res.pointers_written == 2          # tokenizer x2; lonely never grounds
        assert res.grounded_tags == ["tokenizer"]
        assert res.skipped_tags == ["lonely"]
        assert res.scope_refs == 2
        assert res.pruned_tags == [] and res.suppressed_tags == []

    def test_scope_refs_includes_explicit_prune_scope(self, db_session, make_project):
        p = make_project()
        res = register_sources(
            db_session, p["id"],
            [SourceUnit(kind="memory", ref="mem-1", text="tokenizer")],
            prune_scope={("code", "gone.py"), ("memory", "mem-1")},
        )
        assert res.scope_refs == 2  # (memory, mem-1) deduped with the unit's ref

    def test_suppression_prunes_previously_grounded_node(self, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="memory", ref="seed-m", text="tokenizer"),
            SourceUnit(kind="code", ref="seed.py", text="tokenizer"),
        ])
        assert "tokenizer" in _tags(db_session, p["id"])
        # Corpus pass over 20 docs: tokenizer in all 20 (df=20 >= 0.12*20) is
        # generic -> suppressed; each rock sits in exactly one memory + one code
        # doc (df=2 < 2.4) and survives as a node.
        rocks = ["quartz", "basalt", "granite", "marble", "slate",
                 "gneiss", "shale", "pumice", "obsidian", "flint"]
        units = [SourceUnit(kind="memory", ref=f"m{i}", text=f"tokenizer {rocks[i]}") for i in range(10)]
        units += [SourceUnit(kind="code", ref=f"c{i}.py", text=f"tokenizer {rocks[i]}") for i in range(10)]
        res = register_sources(db_session, p["id"], units, suppress_generic=True)
        assert "tokenizer" in res.suppressed_tags
        assert "tokenizer" not in _tags(db_session, p["id"])
        assert _pointers(db_session, p["id"], tag="tokenizer") == []
        assert "quartz" in _tags(db_session, p["id"])

    def test_registration_result_defaults(self):
        r = RegistrationResult()
        assert r.grounded_tags == [] and r.pruned_tags == []
        assert r.pointers_written == 0 and r.scope_refs == 0


class TestRegistryNoiseFilter:
    @pytest.mark.parametrize("tag", ["14m", "60min", "10000m", "2-sec", "ab", "4c8f7a8", "93c5fd"])
    def test_noise_tags(self, tag):
        assert _is_noise_tag(tag) is True

    @pytest.mark.parametrize("tag", ["facade", "decade", "tokenizer", "abc", "2-second"])
    def test_real_tags_survive(self, tag):
        assert _is_noise_tag(tag) is False

    def test_stem_falling_below_min_len_is_dropped(self):
        # axes -> ax (sibilant es rule) -> shorter than MIN_TAG_LEN -> dropped.
        assert node_tokens("axes") == set()

    def test_stem_landing_on_node_stopword_is_dropped(self):
        assert node_tokens("updating resolving") == set()

    def test_hyphenated_measure_survives_when_unit_is_long(self):
        assert "2-second" in node_tokens("a 2-second delay")


# =============================================================================
# node_match (DWB-523) - service level
# =============================================================================

def _seed_neighbor_graph(db, pid):
    """anchor grounds on r1(code)+r2(memory). bravo shares BOTH refs; alpha and
    zeta share only r1 (and ground via r3, which anchor does not touch)."""
    register_sources(db, pid, [
        SourceUnit(kind="code", ref="r1.py", text="anchor bravo alpha zeta", sha="s", line_start=1, line_end=1),
        SourceUnit(kind="memory", ref="r2", text="anchor bravo"),
        SourceUnit(kind="memory", ref="r3", text="alpha zeta"),
    ])
    db.flush()


class TestNodeMatchService:
    def test_list_nodes_invalid_kind_raises_value_error(self, db_session, make_project):
        p = make_project()
        with pytest.raises(ValueError):
            node_match.list_nodes(db_session, p["id"], kind="bogus")

    def test_list_nodes_tie_breaks_on_tag(self, db_session, make_project):
        p = make_project()
        _seed_neighbor_graph(db_session, p["id"])
        nodes = node_match.list_nodes(db_session, p["id"])
        weights = [n.weight for n in nodes]
        assert weights == sorted(weights, reverse=True)
        # Equal-weight runs are tag-ascending.
        for a, b in zip(nodes, nodes[1:]):
            if a.weight == b.weight:
                assert a.tag < b.tag

    def test_list_nodes_kind_filter_service(self, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="session", ref="sess-1", text="anchor"),
            SourceUnit(kind="ticket", ref="T-1", text="anchor bravo"),
            SourceUnit(kind="doc", ref="d.md", text="bravo"),
        ])
        tags = {n.tag for n in node_match.list_nodes(db_session, p["id"], kind="session")}
        assert tags == {"anchor"}

    def test_match_empty_or_stopword_text(self, db_session, make_project):
        p = make_project()
        assert node_match.match_nodes(db_session, p["id"], "") == ([], [])
        assert node_match.match_nodes(db_session, p["id"], "the and of") == ([], [])

    def test_match_no_hits_echoes_query_tags(self, db_session, make_project):
        p = make_project()
        tags, matches = node_match.match_nodes(db_session, p["id"], "Tokenizers Pipelines")
        assert tags == ["pipeline", "tokenizer"]   # sorted + stemmed
        assert matches == []

    def test_match_is_project_isolated(self, db_session, make_project):
        p1, p2 = make_project(), make_project()
        _seed_neighbor_graph(db_session, p2["id"])
        _tags_, matches = node_match.match_nodes(db_session, p1["id"], "anchor")
        assert matches == []

    def test_neighbors_ordered_by_shared_refs_then_weight_then_tag(self, db_session, make_project):
        p = make_project()
        _seed_neighbor_graph(db_session, p["id"])
        _q, matches = node_match.match_nodes(db_session, p["id"], "anchor")
        assert len(matches) == 1
        node, neighbors = matches[0]
        assert node.tag == "anchor"
        order = [(n.node.tag, n.shared_refs) for n in neighbors]
        assert order[0] == ("bravo", ["r1.py", "r2"])
        # alpha and zeta each share one ref, identical df -> identical weight -> tag asc.
        assert [t for t, _ in order[1:]] == ["alpha", "zeta"]
        assert order[1][1] == ["r1.py"] and order[2][1] == ["r1.py"]
        assert all(n.node.id != node.id for n in neighbors)

    def test_neighbor_stub_carries_identity_and_weight(self, db_session, make_project):
        p = make_project()
        _seed_neighbor_graph(db_session, p["id"])
        _q, matches = node_match.match_nodes(db_session, p["id"], "bravo")
        _node, neighbors = matches[0]
        by_tag = {n.node.tag: n for n in neighbors}
        real = next(n for n in _nodes(db_session, p["id"]) if n.tag == "anchor")
        assert by_tag["anchor"].node.id == real.id
        assert by_tag["anchor"].node.weight == real.weight

    def test_match_returns_multiple_nodes_weight_ordered(self, db_session, make_project):
        p = make_project()
        _seed_neighbor_graph(db_session, p["id"])
        _q, matches = node_match.match_nodes(db_session, p["id"], "zeta anchor alpha")
        got = [n.tag for n, _ in matches]
        assert set(got) == {"anchor", "alpha", "zeta"}
        weights = [n.weight for n, _ in matches]
        assert weights == sorted(weights, reverse=True)


# =============================================================================
# node_touch (DWB-527)
# =============================================================================

class TestProviderRegistry:
    def test_register_invalid_kind_raises(self):
        with pytest.raises(node_touch.NodeTouchError) as ei:
            node_touch.register_source_provider("bogus", lambda *a: [])
        assert ei.value.code == "invalid_kind"

    def test_override_wins_and_defaults_remain(self):
        def mine(db, project, repo_path):
            return []
        node_touch.register_source_provider("code", mine)
        merged = node_touch._providers()
        assert merged["code"] is mine
        assert merged["memory"] is node_touch.memory_provider
        assert merged["doc"] is node_touch.doc_provider
        assert set(merged) == {"code", "doc", "memory"}


class TestDefaultProviders:
    def test_memory_provider_missing_dir_is_empty(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        project = db_session.get(Project, p["id"])
        assert node_touch.memory_provider(db_session, project, str(tmp_path)) == []

    def test_memory_provider_skips_empty_and_uses_relative_ref(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        project = db_session.get(Project, p["id"])
        prefix = project.prefix
        _write(tmp_path / _mem_ref(prefix, "Zed"), "## 2026-09-15T00:00:00+00:00\nwidget lesson\n")
        _write(tmp_path / _mem_ref(prefix, "Amy"), "   \n")
        units = node_touch.memory_provider(db_session, project, str(tmp_path))
        assert [(u.kind, u.ref) for u in units] == [("memory", _mem_ref(prefix, "Zed"))]
        assert "widget lesson" in units[0].text
        assert units[0].sha is None and units[0].line_start is None

    def test_doc_provider_light_sweeps_root_and_nested_docs(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        project = db_session.get(Project, p["id"])
        _write(tmp_path / "README.md", "widget readme\n")
        _write(tmp_path / "docs" / "a.md", "alpha doc\n")
        _write(tmp_path / "docs" / "sub" / "b.md", "beta doc\n")
        _write(tmp_path / "docs" / "empty.md", "\n\n")
        units = node_touch.doc_provider(db_session, project, str(tmp_path))
        refs = {u.ref for u in units}
        assert refs == {"README.md", "docs/a.md", "docs/sub/b.md"}
        assert all(u.kind == "doc" and u.sha is None and u.line_start is None for u in units)

    def test_code_provider_light_uses_commit_messages(self, db_session, make_project, repo):
        p = make_project(repo_path=str(repo))
        project = db_session.get(Project, p["id"])
        sha1 = _commit(repo, "a.py", "x = 1\n", "first widget thing")
        sha2 = _commit(repo, "b.py", "y = 2\n", "second gadget thing")
        units = node_touch.code_provider(db_session, project, str(repo))
        by_sha = {u.ref: u for u in units}
        assert set(by_sha) == {sha1, sha2}
        assert by_sha[sha1].sha == sha1 and "first widget thing" in by_sha[sha1].text
        assert by_sha[sha2].kind == "code"

    def test_code_provider_light_non_git_is_empty(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        project = db_session.get(Project, p["id"])
        assert node_touch.code_provider(db_session, project, str(tmp_path)) == []

    def test_git_log_limit_and_multiline_body(self, repo):
        _commit(repo, "a.py", "1\n", "one")
        _commit(repo, "b.py", "2\n", "two\n\nbody line here")
        all_commits = node_touch._git_log(str(repo), limit=10)
        assert len(all_commits) == 2
        assert "body line here" in all_commits[0][1]
        assert len(node_touch._git_log(str(repo), limit=1)) == 1
        assert node_touch._git_log(str(repo / "nope"), limit=5) == []

    def test_relref_and_read_text_safe(self, tmp_path):
        f = _write(tmp_path / "sub" / "m.md", "hi")
        assert node_touch._relref(f, str(tmp_path)) == "sub/m.md"
        assert node_touch._read_text_safe(f) == "hi"
        assert node_touch._read_text_safe(tmp_path / "missing.md") == ""
        (tmp_path / "bin.md").write_bytes(b"\xff\xfe\x00\xff")
        assert node_touch._read_text_safe(tmp_path / "bin.md") == ""


class TestNodeifyResilience:
    def test_failing_provider_is_skipped_not_fatal(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        prefix = p["prefix"]
        _write(tmp_path / "README.md", "widget subsystem\n")
        _write(tmp_path / _mem_ref(prefix, "Zed"), "## 2026-09-15T00:00:00+00:00\nwidget lesson\n")

        def boom(db, project, repo_path):
            raise RuntimeError("provider exploded")
        node_touch.register_source_provider("code", boom)

        res = node_touch.nodeify_project(db_session, p["id"])
        assert res.source_counts["code"] == 0
        assert res.source_counts["memory"] == 1 and res.source_counts["doc"] >= 1
        assert "widget" in _tags(db_session, p["id"])

    def test_repo_dir_missing_raises_repo_missing(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path / "does-not-exist"))
        with pytest.raises(node_touch.NodeTouchError) as ei:
            node_touch.nodeify_project(db_session, p["id"])
        assert ei.value.code == "repo_missing"

    def test_unswept_domains_survive_and_keep_grounding(self, db_session, make_project, tmp_path):
        """ticket/session pointers are outside every provider's domain: nodeify
        leaves them intact and they still count toward the 2-domain rule."""
        p = make_project(repo_path=str(tmp_path))
        prefix = p["prefix"]
        register_sources(db_session, p["id"], [
            SourceUnit(kind="session", ref="sess-1", text="widget"),
            SourceUnit(kind="ticket", ref="T-1", text="widget"),
        ])
        _write(tmp_path / _mem_ref(prefix, "Zed"), "## 2026-09-15T00:00:00+00:00\nwidget lesson\n")
        node_touch.nodeify_project(db_session, p["id"])
        kinds = {pt.kind.value for pt in _pointers(db_session, p["id"], tag="widget")}
        assert kinds == {"session", "ticket", "memory"}


class TestTouchMemory:
    def _seed(self, db, pid, mem_ref):
        register_sources(db, pid, [
            SourceUnit(kind="memory", ref=mem_ref, text="widget"),
            SourceUnit(kind="code", ref="w.py", text="widget", sha="a", line_start=1, line_end=1),
        ])
        db.flush()

    def test_no_repo_path_is_noop(self, db_session, make_project, tmp_path):
        p = make_project()
        ref = _mem_ref(p["prefix"], "Zed")
        self._seed(db_session, p["id"], ref)
        f = _write(tmp_path / ref, "")
        node_touch.touch_memory(db_session, project_id=p["id"], repo_path=None, memory_file=f)
        assert "widget" in _tags(db_session, p["id"])

    def test_missing_file_is_noop(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        ref = _mem_ref(p["prefix"], "Zed")
        self._seed(db_session, p["id"], ref)
        node_touch.touch_memory(
            db_session, project_id=p["id"], repo_path=str(tmp_path), memory_file=tmp_path / ref,
        )
        assert "widget" in _tags(db_session, p["id"])

    def test_empty_file_prunes_memory_pointers(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        ref = _mem_ref(p["prefix"], "Zed")
        self._seed(db_session, p["id"], ref)
        f = _write(tmp_path / ref, "\n")
        node_touch.touch_memory(db_session, project_id=p["id"], repo_path=str(tmp_path), memory_file=f)
        # memory pointer gone -> code alone is one domain -> node pruned.
        assert "widget" not in _tags(db_session, p["id"])

    def test_non_empty_file_adds_memory_domain(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="w.py", text="widget"),
            SourceUnit(kind="doc", ref="d.md", text="widget"),
        ])
        ref = _mem_ref(p["prefix"], "Zed")
        f = _write(tmp_path / ref, "## 2026-09-15T00:00:00+00:00\nwidget lesson\n")
        node_touch.touch_memory(db_session, project_id=p["id"], repo_path=str(tmp_path), memory_file=f)
        kinds = {pt.kind.value for pt in _pointers(db_session, p["id"], tag="widget")}
        assert kinds == {"code", "doc", "memory"}
        mem = [pt for pt in _pointers(db_session, p["id"], tag="widget") if pt.kind == NodePointerKind.memory]
        assert mem[0].ref == ref

    def test_registry_failure_never_raises(self, db_session, make_project, tmp_path, monkeypatch):
        p = make_project(repo_path=str(tmp_path))
        ref = _mem_ref(p["prefix"], "Zed")
        f = _write(tmp_path / ref, "widget lesson\n")

        def boom(*a, **k):
            raise RuntimeError("registry down")
        monkeypatch.setattr(node_touch, "register_sources", boom)
        node_touch.touch_memory(db_session, project_id=p["id"], repo_path=str(tmp_path), memory_file=f)


# =============================================================================
# code_pointers (DWB-525)
# =============================================================================

class TestCodePointersGaps:
    def test_key_pattern_boundaries(self):
        pat = cp._key_pattern("DWB")
        assert pat.search("fix DWB-12 thing").group(1) == "12"
        assert pat.search("XDWB-12") is None
        assert pat.search("DWB-12a") is None
        assert pat.search("D2J-12") is None

    def test_deleted_files_reported_and_excluded_from_commit_files(self, repo):
        _commit(repo, "a.py", "x = 1\n", "add a")
        _git(repo, "rm", "-q", "a.py")
        _git(repo, "commit", "-q", "-m", "drop a")
        sha = _git(repo, "rev-parse", "HEAD")
        assert cp.deleted_files(str(repo), sha) == ["a.py"]
        assert cp.commit_files(str(repo), sha) == []
        assert cp.deleted_files(str(repo / "nope"), sha) == []

    def test_file_lines_at_worktree_and_sha(self, repo):
        sha = _commit(repo, "a.py", "one\ntwo\n", "add a")
        (repo / "a.py").write_text("changed\n")
        assert cp._file_lines_at(str(repo), "a.py", None) == ["changed"]
        assert cp._file_lines_at(str(repo), "a.py", sha) == ["one", "two"]
        assert cp._file_lines_at(str(repo), "missing.py", None) is None
        assert cp._file_lines_at(str(repo), "missing.py", sha) is None

    def test_walk_commits_shape_and_max_commits(self, repo):
        s1 = _commit(repo, "a.py", "1\n", "ZZ-1 first")
        s2 = _commit(repo, "b.py", "2\n", "ZZ-2 second")
        s3 = _commit(repo, "c.py", "3\n", "ZZ-3 third")
        walked = cp.walk_commits_for_tickets(str(repo), "ZZ")
        assert [w["sha"] for w in walked] == [s3, s2, s1]
        assert set(walked[0]) == {"sha", "short_sha", "ticket_keys", "files", "line_ranges"}
        assert walked[0]["short_sha"] == s3[:8]
        assert walked[0]["ticket_keys"] == ["ZZ-3"]
        assert walked[0]["files"] == ["c.py"]
        assert walked[0]["line_ranges"] == {"c.py": [(1, 1)]}
        capped = cp.walk_commits_for_tickets(str(repo), "ZZ", max_commits=1)
        assert [w["sha"] for w in capped] == [s3]

    def test_ground_commit_degrades_on_bad_repo_and_bad_sha(self, db_session, make_project, repo):
        p = make_project()
        r = cp.ground_commit(db_session, p["id"], str(repo / "nope"), "deadbeef")
        assert r.pointers_written == 0 and r.grounded_tags == []
        _commit(repo, "a.py", "widget\n", "ZZ-1 a")
        r2 = cp.ground_commit(db_session, p["id"], str(repo), "0000000000000000000000000000000000000000")
        assert r2.pointers_written == 0 and r2.scope_refs == 0
        assert _pointers(db_session, p["id"]) == []

    def test_code_provider_requires_prefix_and_repo(self, db_session, repo, tmp_path):
        _commit(repo, "a.py", "widget\n", "ZZ-1 a")
        assert cp.code_provider(db_session, SimpleNamespace(prefix=None), str(repo)) == []
        assert cp.code_provider(db_session, SimpleNamespace(prefix="ZZ"), str(tmp_path / "nope")) == []

    def test_code_provider_is_ticket_filtered_to_own_prefix(self, db_session, repo):
        _commit(repo, "a.py", "widget\n", "OTHER-1 foreign key only")
        assert cp.code_provider(db_session, SimpleNamespace(prefix="ZZ"), str(repo)) == []
        _commit(repo, "b.py", "gadget\n", "ZZ-1 own key")
        units = cp.code_provider(db_session, SimpleNamespace(prefix="ZZ"), str(repo))
        assert {u.ref for u in units} == {"b.py"}

    def test_code_provider_grounds_each_file_once_at_newest_sha(self, db_session, repo):
        _commit(repo, "a.py", "old widget\n", "ZZ-1 v1")
        s2 = _commit(repo, "a.py", "new widget\nsecond line\n", "ZZ-2 v2")
        units = cp.code_provider(db_session, SimpleNamespace(prefix="ZZ"), str(repo))
        a_units = [u for u in units if u.ref == "a.py"]
        assert len(a_units) == 2
        assert {u.sha for u in a_units} == {s2}
        assert [u.text for u in a_units] == ["new widget", "second line"]
        assert [(u.line_start, u.line_end) for u in a_units] == [(1, 1), (2, 2)]


# =============================================================================
# doc_pointers (DWB-526)
# =============================================================================

class TestDocPointersGaps:
    def test_enumerate_order_and_filters(self, tmp_path):
        _write(tmp_path / "README.md", "r\n")
        _write(tmp_path / "ARCHITECTURE.md", "a\n")
        _write(tmp_path / "docs" / "zeta.md", "z\n")
        _write(tmp_path / "docs" / "alpha.md", "a\n")
        _write(tmp_path / "docs" / "notes.txt", "not md\n")
        _write(tmp_path / "docs" / "sub" / "nested.md", "nested is excluded\n")
        _write(tmp_path / "OTHER.md", "not a root doc target\n")
        targets = dp.enumerate_doc_targets(str(tmp_path))
        assert targets == ["ARCHITECTURE.md", "README.md", "docs/alpha.md", "docs/zeta.md"]

    def test_build_units_line_numbers_skip_blanks_no_sha(self, tmp_path):
        _write(tmp_path / "README.md", "widget one\n\n   \nwidget four\n")
        units, prune = dp.build_doc_units(str(tmp_path))
        assert prune == {("doc", "README.md")}
        assert [(u.line_start, u.line_end, u.text) for u in units] == [
            (1, 1, "widget one"), (4, 4, "widget four"),
        ]
        assert all(u.sha is None and u.kind == "doc" for u in units)

    def test_ground_docs_degrades_without_corpus(self, db_session, make_project, tmp_path):
        p = make_project()
        r = dp.ground_docs(db_session, p["id"], None)
        assert r.pointers_written == 0 and r.scope_refs == 0
        r2 = dp.ground_docs(db_session, p["id"], str(tmp_path))   # exists, no docs
        assert r2.pointers_written == 0 and r2.scope_refs == 0
        assert _pointers(db_session, p["id"]) == []

    def test_doc_provider_mirrors_build_units_and_degrades(self, db_session, tmp_path):
        _write(tmp_path / "README.md", "widget\n")
        units = dp.doc_provider(db_session, SimpleNamespace(prefix="X"), str(tmp_path))
        expected, _ = dp.build_doc_units(str(tmp_path))
        assert [(u.ref, u.line_start, u.text) for u in units] == [(u.ref, u.line_start, u.text) for u in expected]
        assert dp.doc_provider(db_session, SimpleNamespace(prefix="X"), str(tmp_path / "nope")) == []

    def test_ground_docs_refreshes_moved_line(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        # Live 2-domain seed on refs outside the doc scope so the doc pointer
        # has a grounded node to attach to (a code-only tag never persists).
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="w.py", text="widget"),
            SourceUnit(kind="memory", ref="m", text="widget"),
        ])
        _write(tmp_path / "README.md", "widget\n")
        dp.ground_docs(db_session, p["id"], str(tmp_path))
        ptr = [pt for pt in _pointers(db_session, p["id"], tag="widget") if pt.kind == NodePointerKind.doc]
        assert [(x.ref, x.line_start) for x in ptr] == [("README.md", 1)]
        _write(tmp_path / "README.md", "intro\n\nwidget moved\n")
        dp.ground_docs(db_session, p["id"], str(tmp_path))
        ptr = [pt for pt in _pointers(db_session, p["id"], tag="widget") if pt.kind == NodePointerKind.doc]
        assert [(x.ref, x.line_start) for x in ptr] == [("README.md", 3)]


# =============================================================================
# node_retrieval (DWB-524)
# =============================================================================

class TestRetrievalHelpers:
    def test_agent_from_memory_ref(self):
        assert node_retrieval._agent_from_memory_ref(".dwb/memory/DWB/Stan/memory.md") == "Stan"
        assert node_retrieval._agent_from_memory_ref("memory.md") is None
        assert node_retrieval._agent_from_memory_ref("") is None

    def test_tag_matcher_identifier_boundaries(self):
        m = node_retrieval._tag_matcher("widget")
        assert m.search("widget_pipeline")
        assert m.search("the WIDGET.")
        assert m.search("(widget)")
        assert m.search("widgets") is None
        assert m.search("widget2") is None
        assert m.search("mywidget") is None

    def test_resolve_memory_entry_paths(self, tmp_path):
        ref = "mem/memory.md"
        # No heading above the hit.
        _write(tmp_path / ref, "widget first\n## 2026-09-15T01:00:00+00:00\nlater\n")
        assert node_retrieval._resolve_memory_entry(str(tmp_path), ref, "widget") == (None, None)
        # Heading without an ISO date.
        _write(tmp_path / ref, "## plain notes\nwidget here\n")
        assert node_retrieval._resolve_memory_entry(str(tmp_path), ref, "widget") == ("plain notes", None)
        # Session-suffixed heading: full heading returned, date extracted.
        _write(tmp_path / ref, "## 2026-09-15T01:00:00+00:00 - session abc\nwidget here\n")
        heading, date = node_retrieval._resolve_memory_entry(str(tmp_path), ref, "widget")
        assert heading == "2026-09-15T01:00:00+00:00 - session abc"
        assert date == "2026-09-15T01:00:00+00:00"
        # Nearest heading above the FIRST hit wins.
        _write(tmp_path / ref, "## 2026-01-01T00:00:00+00:00\nnothing\n## 2026-02-02T00:00:00+00:00\nwidget\n## 2026-03-03T00:00:00+00:00\nwidget again\n")
        assert node_retrieval._resolve_memory_entry(str(tmp_path), ref, "widget")[1] == "2026-02-02T00:00:00+00:00"
        # Degradations.
        assert node_retrieval._resolve_memory_entry(None, ref, "widget") == (None, None)
        assert node_retrieval._resolve_memory_entry(str(tmp_path), "missing.md", "widget") == (None, None)
        assert node_retrieval._resolve_memory_entry(str(tmp_path), ref, "absenttag") == (None, None)


def _seed_memory_lesson(db, pid, mem_ref, text, code_ref="handler.py"):
    register_sources(db, pid, [
        SourceUnit(kind="memory", ref=mem_ref, text=text),
        SourceUnit(kind="code", ref=code_ref, text=text, sha="c0", line_start=1, line_end=1),
    ])
    db.flush()


class TestRelevantLessonsGaps:
    def _objs(self, db, pid, agent_id):
        return db.get(Project, pid), db.get(Agent, agent_id)

    def test_closed_states_do_not_seed_query(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        ref = _mem_ref(prefix, "Barry")
        _write(tmp_path / ref, "## 2026-09-14T10:00:00+00:00\nwidget notes\n")
        _seed_memory_lesson(db_session, pid, ref, "widget")
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 901, project_id=pid, title="widget subsystem", assigned_agent_id=stan["id"], status="in_review")
        project, agent = self._objs(db_session, pid, stan["id"])
        assert node_retrieval.relevant_lessons(db_session, project, agent) == []

    def test_other_agents_tickets_do_not_seed_query(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        ref = _mem_ref(prefix, "Barry")
        _write(tmp_path / ref, "## 2026-09-14T10:00:00+00:00\nwidget notes\n")
        _seed_memory_lesson(db_session, pid, ref, "widget")
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        other = make_agent(project_id=pid, name="Other", role="backend-worker")
        _ticket(make_ticket, prefix, 902, project_id=pid, title="widget subsystem", assigned_agent_id=other["id"], status="todo")
        project, agent = self._objs(db_session, pid, stan["id"])
        assert node_retrieval.relevant_lessons(db_session, project, agent) == []

    def test_breadth_first_interleave_across_tags(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        barry, carol = _mem_ref(prefix, "Barry"), _mem_ref(prefix, "Carol")
        _write(tmp_path / barry, "## 2026-09-14T10:00:00+00:00\nwidget gadget notes\n")
        _write(tmp_path / carol, "## 2026-09-14T11:00:00+00:00\nwidget gadget notes\n")
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref=barry, text="widget gadget"),
            SourceUnit(kind="memory", ref=carol, text="widget gadget"),
            SourceUnit(kind="code", ref="h.py", text="widget gadget", sha="c0", line_start=1, line_end=1),
        ])
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 903, project_id=pid, title="widget and gadget work", assigned_agent_id=stan["id"], status="todo")
        project, agent = self._objs(db_session, pid, stan["id"])
        top2 = node_retrieval.relevant_lessons(db_session, project, agent, top_n=2)
        assert [l["tag"] for l in top2] == ["gadget", "widget"]   # one per tag, tag-asc on equal weight
        all4 = node_retrieval.relevant_lessons(db_session, project, agent, top_n=10)
        assert len(all4) == 4
        assert {(l["tag"], l["source_agent"]) for l in all4} == {
            ("gadget", "Barry"), ("gadget", "Carol"), ("widget", "Barry"), ("widget", "Carol"),
        }
        assert all(l["date"] for l in all4)

    def test_duplicate_memory_pointers_dedupe_per_tag_and_ref(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid, prefix = p["id"], p["prefix"]
        ref = _mem_ref(prefix, "Barry")
        _write(tmp_path / ref, "## 2026-09-14T10:00:00+00:00\nwidget\n")
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref=ref, text="widget", line_start=1, line_end=1),
            SourceUnit(kind="memory", ref=ref, text="widget", line_start=2, line_end=2),
            SourceUnit(kind="code", ref="h.py", text="widget"),
        ])
        assert len([pt for pt in _pointers(db_session, pid, tag="widget") if pt.kind == NodePointerKind.memory]) == 2
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        _ticket(make_ticket, prefix, 904, project_id=pid, title="widget", assigned_agent_id=stan["id"], status="todo")
        project, agent = self._objs(db_session, pid, stan["id"])
        lessons = node_retrieval.relevant_lessons(db_session, project, agent)
        assert len(lessons) == 1
        # DWB-545 added an additive "score" field to every entry.
        assert set(lessons[0]) == {
            "tag", "weight", "score", "source_agent", "memory_ref",
            "entry_heading", "date",
        }


class TestRelatedNodesGaps:
    def test_groups_by_domain_and_truncates(self, db_session, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path))
        pid = p["id"]
        register_sources(db_session, pid, [
            SourceUnit(kind="code", ref="a.py", text="widget", sha="s1", line_start=3, line_end=3),
            SourceUnit(kind="code", ref="b.py", text="widget", sha="s2", line_start=7, line_end=7),
            SourceUnit(kind="doc", ref="README.md", text="widget", line_start=2, line_end=2),
            SourceUnit(kind="session", ref="sess-9", text="widget"),
        ])
        project = db_session.get(Project, pid)
        out = node_retrieval.related_nodes(db_session, project, "Widgets please")
        assert out["query_tags"] == ["please", "widget"]
        assert out["lessons"] == []
        assert len(out["sessions"]) == 1
        session = out["sessions"][0]
        assert session["tag"] == "widget" and session["ref"] == "sess-9"
        assert session["score"] is not None      # DWB-545 additive field
        kinds = {c["kind"] for c in out["code"]}
        assert kinds == {"code", "doc"}          # doc pointers ride the code group (documented)
        doc = next(c for c in out["code"] if c["kind"] == "doc")
        assert doc["ref"] == "README.md" and doc["sha"] is None and doc["line_start"] == 2
        code = next(c for c in out["code"] if c["ref"] == "a.py")
        assert code["sha"] == "s1" and code["line_start"] == 3 and code["line_end"] == 3
        # DWB-545: one entry per file, so three files -> three entries.
        assert len(out["code"]) == len({c["ref"] for c in out["code"]}) == 3
        assert len(node_retrieval.related_nodes(db_session, project, "widget", top_n=1)["code"]) == 1

    def test_lessons_without_repo_path_keep_pointer_but_no_heading(self, db_session, make_project):
        p = make_project()
        pid = p["id"]
        ref = _mem_ref(p["prefix"], "Barry")
        _seed_memory_lesson(db_session, pid, ref, "widget")
        project = db_session.get(Project, pid)
        out = node_retrieval.related_nodes(db_session, project, "widget")
        assert len(out["lessons"]) == 1
        lesson = out["lessons"][0]
        assert lesson["source_agent"] == "Barry" and lesson["memory_ref"] == ref
        assert lesson["entry_heading"] is None and lesson["date"] is None

    def test_empty_text_yields_empty_groups(self, db_session, make_project):
        p = make_project()
        project = db_session.get(Project, p["id"])
        out = node_retrieval.related_nodes(db_session, project, "the of and")
        assert out == {"query_tags": [], "lessons": [], "sessions": [], "code": []}


# =============================================================================
# nodes router (DWB-523 / DWB-527)
# =============================================================================

class TestNodesRouterGaps:
    def test_match_requires_text(self, client, make_project):
        p = make_project()
        assert client.get(f"/api/projects/{p['id']}/nodes/match").status_code == 422

    def test_list_empty_project_is_empty_list(self, client, make_project):
        p = make_project()
        r = client.get(f"/api/projects/{p['id']}/nodes")
        assert r.status_code == 200 and r.json() == []

    def test_list_kind_filter_session(self, client, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="session", ref="sess-1", text="anchor"),
            SourceUnit(kind="ticket", ref="T-1", text="anchor bravo"),
            SourceUnit(kind="doc", ref="d.md", text="bravo"),
        ])
        db_session.flush()
        r = client.get(f"/api/projects/{p['id']}/nodes?kind=session")
        assert r.status_code == 200
        assert [n["tag"] for n in r.json()] == ["anchor"]
        ptr_kinds = {pt["kind"] for pt in r.json()[0]["pointers"]}
        assert ptr_kinds == {"session", "ticket"}     # kind serializes as the plain value

    def test_match_echoes_query_and_pointer_shape(self, client, db_session, make_project):
        p = make_project()
        register_sources(db_session, p["id"], [
            SourceUnit(kind="code", ref="x.py", text="anchor", sha="abc", line_start=4, line_end=4),
            SourceUnit(kind="memory", ref="m", text="anchor"),
        ])
        db_session.flush()
        r = client.get(f"/api/projects/{p['id']}/nodes/match?text=Anchors ahoy")
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "Anchors ahoy"
        assert body["query_tags"] == ["ahoy", "anchor"]
        node = body["nodes"][0]
        assert set(node) == {"id", "project_id", "tag", "weight", "pointers", "neighbors"}
        code_ptr = next(pt for pt in node["pointers"] if pt["kind"] == "code")
        assert set(code_ptr) == {"id", "kind", "ref", "sha", "line_start", "line_end"}
        assert code_ptr["ref"] == "x.py" and code_ptr["sha"] == "abc" and code_ptr["line_start"] == 4
        assert node["neighbors"] == []

    def test_nodeify_nonexistent_repo_dir_400(self, client, make_project, tmp_path):
        p = make_project(repo_path=str(tmp_path / "gone"))
        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"]

    def test_nodeify_response_shape(self, client, make_project, tmp_path):
        _write(tmp_path / "README.md", "widget subsystem\n")
        p = make_project(repo_path=str(tmp_path))
        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {
            "project_id", "nodeified_at", "source_counts", "grounded", "pruned",
            "suppressed", "pointers_written",
        }
        assert body["project_id"] == p["id"]
        assert body["nodeified_at"].startswith("20") and "T" in body["nodeified_at"]
        assert set(body["source_counts"]) == {"code", "doc", "memory"}
        assert body["source_counts"]["doc"] == 1 and body["source_counts"]["memory"] == 0
        assert body["grounded"] == 0    # a single-domain corpus grounds nothing
