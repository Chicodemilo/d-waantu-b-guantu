# Path: tests/test_code_pointers.py
# File: test_code_pointers.py
# Created: 2026-09-14
# Purpose: Tests for the code-pointer grounding lane (DWB-525) - pure git/diff/grep
#          helpers. Builds a throwaway fixture git repo per test (no DB rows) and
#          asserts commit-to-ticket walk, unified-diff hunk line-range parsing,
#          sha-stamped tag grounding, and graceful degradation on git failure.
# Caller: pytest
# Callees: app/services/code_pointers
# Data In: fixture git repo under tmp_path
# Data Out: assertions on walk/diff/grounding dicts
# Last Modified: 2026-09-14

import subprocess
from pathlib import Path

import pytest

from app.services import code_pointers as cp


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A minimal git repo with a deterministic identity so commits are stable."""
    r = tmp_path / "fixture_repo"
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


class TestWalkCommitsForTickets:
    def test_returns_only_commits_referencing_keys(self, repo):
        _commit(repo, "a.py", "x = 1\n", "chore: no key here")
        _commit(repo, "b.py", "y = 2\n", "feat: thing DWB-101")
        _commit(repo, "c.py", "z = 3\n", "fix: other CI-9 not our prefix")

        walked = cp.walk_commits_for_tickets(str(repo), "DWB")
        assert len(walked) == 1
        entry = walked[0]
        assert entry["ticket_keys"] == ["DWB-101"]
        assert entry["files"] == ["b.py"]
        assert entry["short_sha"] == entry["sha"][:8]

    def test_multiple_keys_deduped_in_order(self, repo):
        _commit(repo, "m.py", "a=1\n", "feat: DWB-1 and DWB-2 plus DWB-1 again")
        walked = cp.walk_commits_for_tickets(str(repo), "DWB")
        assert walked[0]["ticket_keys"] == ["DWB-1", "DWB-2"]

    def test_multiline_body_message(self, repo):
        _commit(repo, "n.py", "a=1\n", "subject line\n\nbody mentions DWB-77 here")
        walked = cp.walk_commits_for_tickets(str(repo), "DWB")
        assert walked[0]["ticket_keys"] == ["DWB-77"]

    def test_prefix_scoping_excludes_other_projects(self, repo):
        _commit(repo, "p.py", "a=1\n", "feat: CI-500")
        assert cp.walk_commits_for_tickets(str(repo), "DWB") == []
        walked = cp.walk_commits_for_tickets(str(repo), "CI")
        assert walked[0]["ticket_keys"] == ["CI-500"]


class TestDiffLineRanges:
    def test_added_lines_range(self, repo):
        # First commit: 3 lines. Second: append 2 lines -> new range (4,5).
        _commit(repo, "f.py", "l1\nl2\nl3\n", "init DWB-1")
        sha = _commit(repo, "f.py", "l1\nl2\nl3\nl4\nl5\n", "grow DWB-2")
        ranges = cp.diff_line_ranges(str(repo), sha)
        assert ranges == {"f.py": [(4, 5)]}

    def test_deletion_only_hunk_excluded(self, repo):
        _commit(repo, "d.py", "a\nb\nc\nd\n", "init DWB-1")
        # Remove lines b,c -> pure deletion, no new-side range.
        sha = _commit(repo, "d.py", "a\nd\n", "shrink DWB-2")
        ranges = cp.diff_line_ranges(str(repo), sha)
        assert ranges == {}  # file dropped: no new-side lines

    def test_new_file_full_range(self, repo):
        sha = _commit(repo, "new.py", "one\ntwo\nthree\n", "add DWB-3")
        ranges = cp.diff_line_ranges(str(repo), sha)
        assert ranges == {"new.py": [(1, 3)]}


class TestCommitFiles:
    def test_excludes_deletions(self, repo):
        _commit(repo, "keep.py", "a\n", "init DWB-1")
        _commit(repo, "gone.py", "b\n", "add DWB-2")
        # Delete gone.py, modify keep.py in one commit.
        (repo / "keep.py").write_text("a\nb\n")
        _git(repo, "rm", "-q", "gone.py")
        _git(repo, "add", "keep.py")
        _git(repo, "commit", "-q", "-m", "churn DWB-3")
        sha = _git(repo, "rev-parse", "HEAD")
        files = cp.commit_files(str(repo), sha)
        assert files == ["keep.py"]


class TestRenamedOldPaths:
    def test_reports_rename_old_side(self, repo):
        _commit(repo, "old.py", "sprocket\n", "init DWB-1")
        _git(repo, "mv", "old.py", "new.py")
        _git(repo, "commit", "-q", "-m", "rename DWB-2")
        sha = _git(repo, "rev-parse", "HEAD")
        assert cp.renamed_old_paths(str(repo), sha) == ["old.py"]

    def test_empty_when_no_rename(self, repo):
        sha = _commit(repo, "a.py", "x\n", "init DWB-1")
        assert cp.renamed_old_paths(str(repo), sha) == []

    def test_degrades_on_bad_repo(self):
        assert cp.renamed_old_paths("/nonexistent/xyz", "x") == []


class TestBuildCodeUnits:
    def test_per_line_units_with_sha_and_refs(self, repo):
        sha = _commit(
            repo, "svc.py",
            "def session_open():\n\n    return gate_check()\n",
            "add DWB-1",
        )
        units, prune = cp.build_code_units(str(repo), sha[:8])
        # Blank line (2) is skipped; lines 1 and 3 produce units.
        by_line = {u.line_start: u for u in units if u.ref == "svc.py"}
        assert set(by_line) == {1, 3}
        u1 = by_line[1]
        assert u1.kind == "code"
        assert u1.ref == "svc.py"
        assert u1.line_start == u1.line_end == 1
        assert u1.sha == sha  # short sha expanded to full
        assert "session_open" in u1.text
        # Every touched file is in the prune (refresh) scope.
        assert ("code", "svc.py") in prune

    def test_multiple_files(self, repo):
        _commit(repo, "a.py", "alpha\n", "init DWB-1")
        sha = _git(repo, "rev-parse", "HEAD")
        # second commit touches two files
        (repo / "a.py").write_text("alpha\nbeta\n")
        (repo / "b.py").write_text("gamma\n")
        _git(repo, "add", "a.py", "b.py")
        _git(repo, "commit", "-q", "-m", "grow DWB-2")
        sha2 = _git(repo, "rev-parse", "HEAD")
        units, prune = cp.build_code_units(str(repo), sha2)
        refs = {u.ref for u in units}
        assert refs == {"a.py", "b.py"}
        assert ("code", "a.py") in prune and ("code", "b.py") in prune

    def test_deleted_file_in_prune_scope_no_units(self, repo):
        _commit(repo, "keep.py", "a\n", "init DWB-1")
        _commit(repo, "gone.py", "b\n", "add DWB-2")
        (repo / "keep.py").write_text("a\nc\n")
        _git(repo, "rm", "-q", "gone.py")
        _git(repo, "add", "keep.py")
        _git(repo, "commit", "-q", "-m", "churn DWB-3")
        sha = _git(repo, "rev-parse", "HEAD")
        units, prune = cp.build_code_units(str(repo), sha)
        refs = {u.ref for u in units}
        assert "gone.py" not in refs          # deleted -> no units
        assert ("code", "gone.py") in prune   # ...but pruned
        assert ("code", "keep.py") in prune

    def test_renamed_old_path_in_prune_scope(self, repo):
        _commit(repo, "old.py", "sprocket\n", "init DWB-1")
        _git(repo, "mv", "old.py", "new.py")
        _git(repo, "commit", "-q", "-m", "rename DWB-2")
        sha = _git(repo, "rev-parse", "HEAD")
        units, prune = cp.build_code_units(str(repo), sha)
        refs = {u.ref for u in units}
        assert "new.py" in refs              # new path re-grounds
        assert "old.py" not in refs          # old path hosts no units
        assert ("code", "old.py") in prune   # ...but its stale pointers prune
        assert ("code", "new.py") in prune   # new path is also a refresh scope

    def test_degrades_on_bad_repo(self):
        assert cp.build_code_units(None, "x") == ([], set())
        assert cp.build_code_units("/nonexistent/xyz", "x") == ([], set())


class TestRegisterCodeUnits:
    """Integration: build_code_units -> node_registry.register_sources. A node
    only grounds once its tag spans 2 domains (Miles ruling), so we pair the
    code units with a doc unit sharing a tag to cross the threshold."""

    def test_code_units_ground_with_sha_and_line(self, repo, db_session, make_project):
        from app.models.node import Node, NodePointer, NodePointerKind
        from app.services import node_registry as nr

        project = make_project()
        pid = project["id"]

        # A distinctive token present in code and (below) a doc, so it grounds.
        sha = _commit(repo, "widget.py", "widgetize the thing\n", "add DWB-1")
        code_units, prune = cp.build_code_units(str(repo), sha)

        doc_unit = nr.SourceUnit(
            kind="doc", ref="README.md", text="widgetize is documented", line_start=3, line_end=3
        )
        nr.register_sources(db_session, pid, code_units + [doc_unit], prune_scope=prune)
        db_session.flush()

        node = db_session.query(Node).filter_by(project_id=pid, tag="widgetize").one_or_none()
        assert node is not None, "shared 2-domain tag should ground"
        code_ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.code)
            .one()
        )
        assert code_ptr.ref == "widget.py"
        assert code_ptr.sha == sha
        assert code_ptr.line_start == 1 and code_ptr.line_end == 1

    def test_code_only_tag_does_not_ground(self, repo, db_session, make_project):
        from app.models.node import Node
        from app.services import node_registry as nr

        project = make_project()
        pid = project["id"]
        sha = _commit(repo, "solo.py", "lonelyword here\n", "add DWB-1")
        units, prune = cp.build_code_units(str(repo), sha)
        nr.register_sources(db_session, pid, units, prune_scope=prune)
        db_session.flush()
        # One domain only -> no node.
        assert db_session.query(Node).filter_by(project_id=pid, tag="lonelyword").one_or_none() is None

    def test_ground_commit_op(self, repo, db_session, make_project):
        from app.models.node import NodePointer, NodePointerKind
        from app.services import node_registry as nr

        pid = make_project()["id"]
        # Seed a live 2-domain node for the shared tag (refs outside w.py's scope)
        # so a single code touch keeps it grounded. A 1-domain seed never persists.
        nr.register_sources(db_session, pid, [
            nr.SourceUnit(kind="doc", ref="seed.md", text="widgetize doc", line_start=1, line_end=1),
            nr.SourceUnit(kind="code", ref="seed.py", text="widgetize()", sha="s0", line_start=1, line_end=1),
        ])
        sha = _commit(repo, "w.py", "widgetize()\n", "add DWB-1")
        cp.ground_commit(db_session, pid, str(repo), sha)
        db_session.flush()
        ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.code, ref="w.py")
            .one()
        )
        assert ptr.sha == sha

    def test_ground_code_history_newest_sha_wins(self, repo, db_session, make_project):
        from app.models.node import NodePointer, NodePointerKind
        from app.services import node_registry as nr

        pid = make_project()["id"]
        nr.register_sources(db_session, pid, [
            nr.SourceUnit(kind="doc", ref="seed.md", text="widgetize doc", line_start=1, line_end=1),
            nr.SourceUnit(kind="code", ref="seed.py", text="widgetize()", sha="s0", line_start=1, line_end=1),
        ])
        # Two commits touch the same file; the newer must win the (code, ref) scope.
        _commit(repo, "w.py", "widgetize()\n", "first DWB-1")
        sha2 = _commit(repo, "w.py", "# header\nwidgetize()\n", "second DWB-2")
        cp.ground_code_history(db_session, pid, str(repo), "DWB")
        db_session.flush()
        ptrs = (
            db_session.query(NodePointer)
            .filter_by(project_id=pid, tag="widgetize", kind=NodePointerKind.code, ref="w.py")
            .all()
        )
        # Only the newest commit's grounding survives (line moved to 2, sha=sha2).
        assert len(ptrs) == 1
        assert ptrs[0].sha == sha2 and ptrs[0].line_start == 2


class TestDegradation:
    def test_none_repo(self):
        assert cp.walk_commits_for_tickets(None, "DWB") == []

    def test_nonexistent_repo(self):
        assert cp.walk_commits_for_tickets("/nonexistent/xyz", "DWB") == []

    def test_non_git_dir(self, tmp_path):
        assert cp.walk_commits_for_tickets(str(tmp_path), "DWB") == []

    def test_diff_on_bad_sha(self, repo):
        assert cp.diff_line_ranges(str(repo), "deadbeef") == {}

    def test_resolve_full_sha(self, repo):
        sha = _commit(repo, "r.py", "a\n", "add DWB-1")
        assert cp.resolve_full_sha(str(repo), sha[:8]) == sha
        assert cp.resolve_full_sha(str(repo), "nope") is None
