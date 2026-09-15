# Path: tests/test_node_registry.py
# File: test_node_registry.py
# Created: 2026-09-14 (DWB-522)
# Purpose: Tests for the LIGHT node registration service - normalization/merge,
#          light stemming, the 2-domain grounding rule (refusal + success),
#          pointer shapes, idempotent re-registration, and prune-on-un-ground.
# Caller: pytest
# Callees: app/services/node_registry, app/models/node
# Data In: pytest fixtures (db_session, make_project)
# Data Out: assertions
# Last Modified: 2026-09-14 (DWB-522)

from sqlalchemy import select

from app.models.node import Node, NodePointer
from app.services.node_registry import (
    SourceUnit,
    light_stem,
    node_tokens,
    register_sources,
)


def _nodes(db, project_id):
    return db.execute(
        select(Node).where(Node.project_id == project_id)
    ).scalars().all()


def _pointers(db, project_id, tag=None):
    q = select(NodePointer).where(NodePointer.project_id == project_id)
    if tag is not None:
        q = q.where(NodePointer.tag == tag)
    return db.execute(q).scalars().all()


def _tag_set(db, project_id):
    return {n.tag for n in _nodes(db, project_id)}


# --- light stemming ---------------------------------------------------------

class TestLightStem:
    def test_plural_s(self):
        assert light_stem("nodes") == "node"
        assert light_stem("pointers") == "pointer"

    def test_gerund_and_past(self):
        assert light_stem("grounding") == "ground"
        assert light_stem("grounded") == "ground"

    def test_ies_to_y(self):
        assert light_stem("registries") == "registry"

    def test_sibilant_es(self):
        assert light_stem("boxes") == "box"
        assert light_stem("matches") == "match"

    def test_guards_no_overstem(self):
        # ss / us / is endings and short words must survive intact
        assert light_stem("status") == "status"
        assert light_stem("class") == "class"
        assert light_stem("analysis") == "analysis"
        assert light_stem("api") == "api"

    def test_node_tokens_merge_after_stem(self):
        # "Nodes" and "node" normalize + stem to the same tag
        toks = node_tokens("Nodes node NODE")
        assert toks == {"node"}

    def test_node_tokens_drops_stopwords_keeps_ticket_keys(self):
        toks = node_tokens("the DWB-522 grounding and the pointers")
        assert "DWB-522" in toks
        assert "ground" in toks
        assert "pointer" in toks
        assert "the" not in toks and "and" not in toks


# --- grounding rule ---------------------------------------------------------

class TestGrounding:
    def test_single_domain_does_not_register(self, db_session, make_project):
        p = make_project()
        res = register_sources(
            db_session,
            p["id"],
            [SourceUnit(kind="memory", ref="mem-1", text="tokenizer pipeline design")],
        )
        # Nothing grounds: only one domain present.
        assert _nodes(db_session, p["id"]) == []
        assert set(res.grounded_tags) == set()
        assert "tokenizer" in res.skipped_tags

    def test_two_domains_registers(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session,
            p["id"],
            [
                SourceUnit(kind="memory", ref="mem-1", text="tokenizer pipeline"),
                SourceUnit(
                    kind="code", ref="app/x.py", text="tokenizer pipeline", sha="abc123",
                    line_start=10, line_end=20,
                ),
            ],
        )
        tags = _tag_set(db_session, p["id"])
        assert "tokenizer" in tags
        assert "pipeline" in tags
        # Each grounded tag has 2 pointers (one per domain).
        ptrs = _pointers(db_session, p["id"], tag="tokenizer")
        assert {pt.kind.value for pt in ptrs} == {"memory", "code"}

    def test_pointer_shape_preserved(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session,
            p["id"],
            [
                SourceUnit(kind="doc", ref="README.md", text="grounding"),
                SourceUnit(
                    kind="code", ref="app/x.py", text="grounding",
                    sha="deadbeef", line_start=5, line_end=8,
                ),
            ],
        )
        code_ptr = [
            pt for pt in _pointers(db_session, p["id"], tag="ground")
            if pt.kind.value == "code"
        ][0]
        assert code_ptr.sha == "deadbeef"
        assert code_ptr.line_start == 5
        assert code_ptr.line_end == 8
        assert code_ptr.ref == "app/x.py"

    def test_weight_is_distinct_source_count(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session,
            p["id"],
            [
                SourceUnit(kind="memory", ref="mem-1", text="alpha"),
                SourceUnit(kind="code", ref="a.py", text="alpha"),
                SourceUnit(kind="doc", ref="d.md", text="alpha"),
            ],
        )
        node = [n for n in _nodes(db_session, p["id"]) if n.tag == "alpha"][0]
        assert node.weight == 3  # three distinct (kind, ref) sources

    def test_weight_not_inflated_by_per_line_pointers(self, db_session, make_project):
        # A per-line lane emits multiple pointers for the SAME (kind, ref): three
        # doc line ranges + one memory. That is 4 pointers but only 2 distinct
        # sources, so weight must be 2, not 4 (anti-inflation, DWB-525/526).
        p = make_project()
        register_sources(
            db_session,
            p["id"],
            [
                SourceUnit(kind="doc", ref="d.md", text="beta", line_start=1, line_end=1),
                SourceUnit(kind="doc", ref="d.md", text="beta", line_start=5, line_end=5),
                SourceUnit(kind="doc", ref="d.md", text="beta", line_start=9, line_end=9),
                SourceUnit(kind="memory", ref="mem-1", text="beta"),
            ],
        )
        node = [n for n in _nodes(db_session, p["id"]) if n.tag == "beta"][0]
        ptrs = _pointers(db_session, p["id"], tag="beta")
        assert len(ptrs) == 4       # per-line pointers preserved for precision
        assert node.weight == 2     # but weight counts distinct sources only


# --- normalization merge ----------------------------------------------------

class TestMerge:
    def test_normalized_collision_merges_one_node(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session,
            p["id"],
            [
                SourceUnit(kind="memory", ref="mem-1", text="Nodes NODE node"),
                SourceUnit(kind="code", ref="a.py", text="nodes"),
            ],
        )
        nodes = [n for n in _nodes(db_session, p["id"]) if n.tag == "node"]
        assert len(nodes) == 1


# --- idempotency + refresh + prune ------------------------------------------

class TestIdempotencyAndPrune:
    def test_rerun_is_idempotent(self, db_session, make_project):
        p = make_project()
        units = [
            SourceUnit(kind="memory", ref="mem-1", text="idempotent design"),
            SourceUnit(kind="code", ref="a.py", text="idempotent design"),
        ]
        register_sources(db_session, p["id"], units)
        first_nodes = _tag_set(db_session, p["id"])
        first_ptr_count = len(_pointers(db_session, p["id"]))

        register_sources(db_session, p["id"], units)
        assert _tag_set(db_session, p["id"]) == first_nodes
        assert len(_pointers(db_session, p["id"])) == first_ptr_count

    def test_refresh_updates_line_ranges(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session, p["id"],
            [
                SourceUnit(kind="doc", ref="d.md", text="staleness"),
                SourceUnit(kind="code", ref="a.py", text="staleness",
                           sha="old", line_start=1, line_end=2),
            ],
        )
        # Re-register the code ref with a new sha + lines (rot refresh).
        register_sources(
            db_session, p["id"],
            [
                SourceUnit(kind="code", ref="a.py", text="staleness",
                           sha="new", line_start=40, line_end=45),
            ],
        )
        # "staleness" ends in 'ss' so the stemmer leaves it intact.
        code_ptr = [
            pt for pt in _pointers(db_session, p["id"], tag="staleness")
            if pt.kind.value == "code"
        ]
        # exactly one code pointer (old replaced), with the new provenance
        assert len(code_ptr) == 1
        assert code_ptr[0].sha == "new"
        assert code_ptr[0].line_start == 40

    def test_prune_when_domain_drops_below_two(self, db_session, make_project):
        p = make_project()
        register_sources(
            db_session, p["id"],
            [
                SourceUnit(kind="memory", ref="mem-1", text="fragile"),
                SourceUnit(kind="code", ref="a.py", text="fragile"),
            ],
        )
        assert "fragile" in _tag_set(db_session, p["id"])

        # The code ref no longer mentions the tag -> re-register it empty via
        # prune_scope; the tag drops to one domain and the node is removed.
        register_sources(
            db_session, p["id"], [], prune_scope={("code", "a.py")}
        )
        assert "fragile" not in _tag_set(db_session, p["id"])
        assert _pointers(db_session, p["id"], tag="fragile") == []

    def test_incremental_cross_ref_grounding(self, db_session, make_project):
        p = make_project()
        # First establish a grounded node so a code pointer for "shared" persists.
        register_sources(
            db_session, p["id"],
            [
                SourceUnit(kind="code", ref="a.py", text="widget helper"),
                SourceUnit(kind="doc", ref="d.md", text="widget helper"),
            ],
        )
        # Now a memory touch mentioning "widget" adds a third domain pointer.
        register_sources(
            db_session, p["id"],
            [SourceUnit(kind="memory", ref="mem-1", text="widget")],
        )
        ptrs = _pointers(db_session, p["id"], tag="widget")
        assert {pt.kind.value for pt in ptrs} == {"code", "doc", "memory"}

    def test_generic_high_df_tag_suppressed(self, db_session, make_project):
        # 10 documents all mention "common" (grounds code+doc trivially); only two
        # mention "special". With suppress_generic, "common" (df/N = 1.0) is
        # dropped as boilerplate while "special" (df=2) survives.
        p = make_project()
        units = []
        for i in range(10):
            kind = "code" if i % 2 == 0 else "doc"
            text = "common special" if i < 2 else "common"
            units.append(SourceUnit(kind=kind, ref=f"f{i}", text=text))
        res = register_sources(db_session, p["id"], units, suppress_generic=True)
        tags = _tag_set(db_session, p["id"])
        assert "common" not in tags
        assert "special" in tags
        assert "common" in res.suppressed_tags

    def test_suppression_off_by_default_grounds_generic(self, db_session, make_project):
        # Same corpus, no suppress_generic -> "common" grounds normally (proves
        # suppression is opt-in and incremental callers are unaffected).
        p = make_project()
        units = []
        for i in range(10):
            kind = "code" if i % 2 == 0 else "doc"
            units.append(SourceUnit(kind=kind, ref=f"f{i}", text="common"))
        register_sources(db_session, p["id"], units)
        assert "common" in _tag_set(db_session, p["id"])

    def test_suppression_noop_below_min_docs(self, db_session, make_project):
        # Below GENERIC_MIN_DOCS the DF ratio is not meaningful; even with
        # suppress_generic a tag in every (few) doc still grounds.
        p = make_project()
        units = [
            SourceUnit(kind="code", ref="a.py", text="common"),
            SourceUnit(kind="doc", ref="d.md", text="common"),
        ]
        register_sources(db_session, p["id"], units, suppress_generic=True)
        assert "common" in _tag_set(db_session, p["id"])

    def test_project_isolation(self, db_session, make_project):
        p1 = make_project()
        p2 = make_project()
        register_sources(
            db_session, p1["id"],
            [
                SourceUnit(kind="memory", ref="m", text="isolation"),
                SourceUnit(kind="code", ref="c", text="isolation"),
            ],
        )
        assert "isolation" in _tag_set(db_session, p1["id"])
        assert _tag_set(db_session, p2["id"]) == set()
