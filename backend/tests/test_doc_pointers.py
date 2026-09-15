# Path: tests/test_doc_pointers.py
# File: test_doc_pointers.py
# Created: 2026-09-14
# Purpose: Tests for the doc-pointer grounding lane (DWB-526) - target enumeration
#          + doc-kind SourceUnit builder. Builds a fixture doc tree under tmp_path
#          and asserts root-doc + docs/*.md discovery, per-line unit shape with
#          line refs, prune scope, empty-corpus degradation, and grounding through
#          node_registry.register_sources (paired with a code unit to cross the
#          2-domain grounding rule).
# Caller: pytest
# Callees: app/services/doc_pointers, app/services/node_registry
# Data In: fixture doc tree under tmp_path
# Data Out: assertions on target list, unit shape, and persisted nodes/pointers
# Last Modified: 2026-09-14

from app.services import doc_pointers as dp


def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


class TestEnumerateDocTargets:
    def test_root_and_docs_dir(self, tmp_path):
        _write(tmp_path, "README.md", "# readme\n")
        _write(tmp_path, "ARCHITECTURE.md", "# arch\n")
        _write(tmp_path, "docs/guide.md", "# guide\n")
        _write(tmp_path, "docs/other.md", "# other\n")
        _write(tmp_path, "docs/notes.txt", "ignore me\n")     # not .md
        _write(tmp_path, "random.md", "not a tracked root doc\n")

        targets = dp.enumerate_doc_targets(str(tmp_path))
        assert "README.md" in targets
        assert "ARCHITECTURE.md" in targets
        assert "docs/guide.md" in targets
        assert "docs/other.md" in targets
        assert "docs/notes.txt" not in targets
        assert "random.md" not in targets
        docs_only = [t for t in targets if t.startswith("docs/")]
        assert docs_only == sorted(docs_only)

    def test_missing_files_skipped(self, tmp_path):
        _write(tmp_path, "HANDOFF.md", "# handoff\n")
        assert dp.enumerate_doc_targets(str(tmp_path)) == ["HANDOFF.md"]

    def test_none_repo(self):
        assert dp.enumerate_doc_targets(None) == []

    def test_nonexistent_repo(self):
        assert dp.enumerate_doc_targets("/nonexistent/xyz") == []


class TestBuildDocUnits:
    def test_per_line_units_with_refs(self, tmp_path):
        _write(tmp_path, "README.md", "intro line\n\nsprint gate stuff\n")
        units, prune = dp.build_doc_units(str(tmp_path))
        by_line = {u.line_start: u for u in units if u.ref == "README.md"}
        # Blank line 2 skipped.
        assert set(by_line) == {1, 3}
        u3 = by_line[3]
        assert u3.kind == "doc"
        assert u3.ref == "README.md"
        assert u3.line_start == u3.line_end == 3
        assert u3.sha is None                 # docs are working-tree, no sha
        assert "sprint gate" in u3.text
        assert ("doc", "README.md") in prune

    def test_prune_scope_covers_all_targets(self, tmp_path):
        _write(tmp_path, "README.md", "a\n")
        _write(tmp_path, "docs/x.md", "b\n")
        _, prune = dp.build_doc_units(str(tmp_path))
        assert prune == {("doc", "README.md"), ("doc", "docs/x.md")}

    def test_empty_corpus_degrades(self, tmp_path):
        assert dp.build_doc_units(str(tmp_path)) == ([], set())

    def test_none_repo_degrades(self):
        assert dp.build_doc_units(None) == ([], set())


class TestRegisterDocUnits:
    """Integration: build_doc_units -> register_sources. Pair with a code unit
    sharing a tag so the 2-domain grounding rule is satisfied."""

    def test_doc_unit_grounds_with_line_ref(self, tmp_path, db_session, make_project):
        from app.models.node import Node, NodePointer, NodePointerKind
        from app.services import node_registry as nr

        project = make_project()
        pid = project["id"]
        _write(tmp_path, "README.md", "line one\nwidgetize documented here\n")
        doc_units, prune = dp.build_doc_units(str(tmp_path))

        code_unit = nr.SourceUnit(
            kind="code", ref="w.py", text="widgetize()", sha="abc123", line_start=5, line_end=5
        )
        nr.register_sources(db_session, pid, doc_units + [code_unit], prune_scope=prune)
        db_session.flush()

        node = db_session.query(Node).filter_by(project_id=pid, tag="widgetize").one_or_none()
        assert node is not None
        doc_ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.doc)
            .one()
        )
        assert doc_ptr.ref == "README.md"
        assert doc_ptr.line_start == 2 and doc_ptr.line_end == 2
        assert doc_ptr.sha is None

    def test_ground_docs_op_reground_prunes(self, tmp_path, db_session, make_project):
        from app.models.node import NodePointer, NodePointerKind
        from app.services import node_registry as nr

        pid = make_project()["id"]
        # Seed a live 2-domain node (refs outside the doc scope re-grounded below)
        # so the README doc pointer persists across re-grounds.
        nr.register_sources(db_session, pid, [
            nr.SourceUnit(kind="code", ref="w.py", text="widgetize()", sha="a1", line_start=1, line_end=1),
            nr.SourceUnit(kind="doc", ref="seed.md", text="widgetize doc", line_start=1, line_end=1),
        ])
        _write(tmp_path, "README.md", "widgetize documented\n")
        dp.ground_docs(db_session, pid, str(tmp_path))
        db_session.flush()
        ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.doc, ref="README.md")
            .one()
        )
        assert ptr.line_start == 1

        # Re-ground after the doc changes: the tag moves lines, stale pointer pruned.
        _write(tmp_path, "README.md", "intro\nwidgetize documented\n")
        dp.ground_docs(db_session, pid, str(tmp_path))
        db_session.flush()
        ptrs = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.doc, ref="README.md")
            .all()
        )
        assert len(ptrs) == 1 and ptrs[0].line_start == 2
