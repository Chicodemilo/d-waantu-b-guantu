# Path: tests/test_node_exclusions.py
# File: test_node_exclusions.py
# Created: 2026-09-15
# Purpose: DWB-549 - per-project node-scan exclusions. Covers the shared matcher
#          (directory prefixes, any-depth dirs, basename globs, path globs),
#          pattern validation, seed-once-then-never-again persistence, the CRUD
#          endpoints, and both grounding lanes: excluded files never become
#          SourceUnits, newly-excluded refs are PRUNED rather than stranded, and
#          deleting a row restores its pointers on the next scan. Also covers
#          the DWB-567 first-view seeding race across real concurrent sessions.
# Caller: pytest (named for app/routers/node_exclusions.py so the force_test_coverage gate sees the router as covered)
# Callees: app/config/node_scan, app/services/node_exclusion, app/routers/node_exclusions, code_pointers, doc_pointers
# Data In: pytest fixtures (client, db_session, make_project, tmp_path) + a fixture git repo;
#          TestSeedingRace additionally opens real committing sessions on lat_test
# Data Out: assertions
# Last Modified: 2026-09-16 (DWB-567: TestSeedingRace, real concurrent sessions)

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config.node_scan import DEFAULT_NODE_SCAN_EXCLUDES, is_excluded
from app.models.node import NodePointer, NodePointerKind
from app.models.node_exclusion import NodeExclusion
from app.models.project import Project
from app.services import code_pointers as cp
from app.services import doc_pointers as dp
from app.services import node_exclusion as nx
from app.services.node_registry import SourceUnit, register_sources

DEFAULTS = DEFAULT_NODE_SCAN_EXCLUDES


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
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


def _commit(repo: Path, files: dict, message: str) -> str:
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _refs(db, pid, kind=None):
    q = db.query(NodePointer).filter(NodePointer.project_id == pid)
    if kind is not None:
        q = q.filter(NodePointer.kind == kind)
    return {p.ref for p in q.all()}


class TestExclusionMatcher:
    @pytest.mark.parametrize("path", [
        ".claude/team_lead_playbook.md",
        ".claude/agents/backend-worker.md",
        "backend/tests/test_nodes.py",
        "backend/tests/conftest.py",
        "frontend/src/__tests__/App.test.jsx",
        "frontend/src/components/nodes/__tests__/NodeCloud.test.jsx",
        "backend/app/services/test_helper.py",
        "frontend/src/api/nodes.test.js",
    ])
    def test_excluded_paths(self, path):
        assert is_excluded(path, DEFAULTS) is True

    @pytest.mark.parametrize("path", [
        "docs/team_lead_playbook.md",          # the SOURCE copy stays
        "docs/agent_scoring_spec.md",
        "backend/app/services/scoring.py",
        "backend/app/services/stick_redemption.py",
        "frontend/src/pages/NodesPage.jsx",
        "frontend/src/hooks/useNodeConnections.js",
        "README.md",
        "HANDOFF.md",
        "backend/app/config/node_scan.py",
        "my__tests__notes.md",                 # not a __tests__ DIRECTORY
        "contest.py",                          # not conftest.py
        "latest.py",                           # does not match test_*.py
    ])
    def test_kept_paths(self, path):
        assert is_excluded(path, DEFAULTS) is False

    def test_source_and_deployed_playbook_split(self):
        """The whole point of the .claude/ rule: one copy indexed, not two."""
        assert is_excluded("docs/pm_playbook.md", DEFAULTS) is False
        assert is_excluded(".claude/pm_playbook.md", DEFAULTS) is True

    def test_path_normalization(self):
        assert is_excluded("./backend/tests/test_x.py", DEFAULTS) is True
        assert is_excluded("/.claude/x.md", DEFAULTS) is True
        assert is_excluded("backend\\tests\\test_x.py", DEFAULTS) is True

    def test_empty_path_never_excluded(self):
        assert is_excluded("", DEFAULTS) is False
        assert is_excluded("   ", DEFAULTS) is False

    def test_no_patterns_excludes_nothing(self):
        """A project whose rows a user cleared indexes everything, exactly as
        every project did before this ticket."""
        assert is_excluded("backend/tests/test_x.py", ()) is False
        assert is_excluded(".claude/pm_playbook.md", []) is False

    def test_patterns_are_exactly_what_is_passed(self):
        assert is_excluded("anything/at/all.py", ("anything/",)) is True
        assert is_excluded("backend/tests/x.py", ("anything/",)) is False

    def test_path_glob_matches_whole_path(self):
        pats = ("docs/generated/*.md",)
        assert is_excluded("docs/generated/api.md", patterns=pats) is True
        assert is_excluded("docs/api.md", patterns=pats) is False

    def test_any_depth_directory_pattern(self):
        pats = ("**/fixtures/",)
        assert is_excluded("a/b/fixtures/data.json", patterns=pats) is True
        assert is_excluded("fixtures/data.json", patterns=pats) is True
        # A FILE named fixtures is not a fixtures directory.
        assert is_excluded("a/b/fixtures", patterns=pats) is False


class TestPatternValidation:
    @pytest.mark.parametrize("raw,expected", [
        ("backend/tests/", "backend/tests/"),
        ("  docs/x.md  ", "docs/x.md"),
        ("./backend/tests/", "backend/tests/"),
        ("backend\\tests\\", "backend/tests/"),
    ])
    def test_normalizes(self, raw, expected):
        assert nx.validate_pattern(raw) == expected

    @pytest.mark.parametrize("raw,reason", [
        ("", "must not be empty"),
        ("   ", "must not be empty"),
        ("/etc/passwd", "repo-relative"),
        ("~/secrets", "repo-relative"),
        ("C:/Windows", "repo-relative"),
        ("../outside", "escape the repo root"),
        ("docs/../../etc", "escape the repo root"),
        ("x" * 501, "500 characters"),
    ])
    def test_rejects_with_a_reason(self, raw, reason):
        with pytest.raises(nx.InvalidExclusionPattern) as ei:
            nx.validate_pattern(raw)
        assert reason in str(ei.value)


class TestSeeding:
    def test_seeds_once_then_never_again(self, db_session, make_project):
        p = make_project()
        project = db_session.get(Project, p["id"])
        assert project.node_exclusions_seeded is False
        written = nx.ensure_seeded(db_session, project)
        assert written == len(DEFAULTS)
        assert project.node_exclusions_seeded is True
        assert nx.ensure_seeded(db_session, project) == 0

    def test_deleted_default_stays_deleted(self, db_session, make_project):
        """The reason this is DB state and not config: a removed default must
        not come back on the next read."""
        p = make_project()
        pid = p["id"]
        rows = nx.list_exclusions(db_session, pid)
        target = next(r for r in rows if r.pattern == "backend/tests/")
        nx.delete_exclusion(db_session, pid, target.id)
        again = {r.pattern for r in nx.list_exclusions(db_session, pid)}
        assert "backend/tests/" not in again
        assert nx.patterns_for_project(db_session, pid) == tuple(
            d for d in DEFAULTS if d != "backend/tests/"
        )

    def test_clearing_every_row_means_scan_everything(self, db_session, make_project):
        p = make_project()
        pid = p["id"]
        for row in nx.list_exclusions(db_session, pid):
            nx.delete_exclusion(db_session, pid, row.id)
        assert nx.patterns_for_project(db_session, pid) == ()
        assert is_excluded("backend/tests/x.py", nx.patterns_for_project(db_session, pid)) is False

    def test_patterns_for_unknown_project_degrade_to_empty(self, db_session):
        assert nx.patterns_for_project(db_session, 999999) == ()

    def test_add_and_delete(self, db_session, make_project):
        p = make_project()
        pid = p["id"]
        row = nx.add_exclusion(db_session, pid, "  ./vendor/  ")
        assert row.pattern == "vendor/"
        assert "vendor/" in nx.patterns_for_project(db_session, pid)
        nx.delete_exclusion(db_session, pid, row.id)
        assert "vendor/" not in nx.patterns_for_project(db_session, pid)

    def test_duplicate_is_refused(self, db_session, make_project):
        p = make_project()
        nx.add_exclusion(db_session, p["id"], "vendor/")
        with pytest.raises(nx.NodeExclusionError) as ei:
            nx.add_exclusion(db_session, p["id"], "vendor/")
        assert ei.value.code == "duplicate"

    def test_adding_seeds_first(self, db_session, make_project):
        """A user's first manual entry must not suppress defaults they never saw."""
        p = make_project()
        nx.add_exclusion(db_session, p["id"], "vendor/")
        patterns = nx.patterns_for_project(db_session, p["id"])
        assert set(DEFAULTS) <= set(patterns)
        assert "vendor/" in patterns

    def test_delete_wrong_project_is_not_found(self, db_session, make_project):
        p1, p2 = make_project(), make_project()
        row = nx.add_exclusion(db_session, p1["id"], "vendor/")
        with pytest.raises(nx.NodeExclusionError) as ei:
            nx.delete_exclusion(db_session, p2["id"], row.id)
        assert ei.value.code == "not_found"


class TestExclusionEndpoints:
    def test_list_seeds_on_first_call(self, client, make_project):
        p = make_project()
        r = client.get(f"/api/projects/{p['id']}/node-exclusions")
        assert r.status_code == 200, r.text
        patterns = [row["pattern"] for row in r.json()]
        assert patterns == list(DEFAULTS)
        body = r.json()[0]
        assert set(body) == {"id", "project_id", "pattern", "created_at"}
        # Second call does not duplicate.
        again = client.get(f"/api/projects/{p['id']}/node-exclusions")
        assert [row["pattern"] for row in again.json()] == list(DEFAULTS)

    def test_post_adds_one(self, client, make_project):
        p = make_project()
        r = client.post(f"/api/projects/{p['id']}/node-exclusions", json={"pattern": "vendor/"})
        assert r.status_code == 201, r.text
        assert r.json()["pattern"] == "vendor/"
        listed = [row["pattern"] for row in client.get(f"/api/projects/{p['id']}/node-exclusions").json()]
        assert "vendor/" in listed

    @pytest.mark.parametrize("bad,reason", [
        ("/etc/passwd", "repo-relative"),
        ("../escape", "escape the repo root"),
        ("", "must not be empty"),
    ])
    def test_post_rejects_bad_paths_with_a_reason(self, client, make_project, bad, reason):
        p = make_project()
        r = client.post(f"/api/projects/{p['id']}/node-exclusions", json={"pattern": bad})
        assert r.status_code == 400, r.text
        assert reason in r.json()["detail"]

    def test_post_duplicate_409(self, client, make_project):
        p = make_project()
        client.post(f"/api/projects/{p['id']}/node-exclusions", json={"pattern": "vendor/"})
        r = client.post(f"/api/projects/{p['id']}/node-exclusions", json={"pattern": "vendor/"})
        assert r.status_code == 409

    def test_delete_removes_and_is_permanent(self, client, make_project):
        p = make_project()
        rows = client.get(f"/api/projects/{p['id']}/node-exclusions").json()
        target = next(r for r in rows if r["pattern"] == "backend/tests/")
        assert client.delete(f"/api/projects/{p['id']}/node-exclusions/{target['id']}").status_code == 204
        after = [r["pattern"] for r in client.get(f"/api/projects/{p['id']}/node-exclusions").json()]
        assert "backend/tests/" not in after

    def test_unknown_project_404(self, client):
        assert client.get("/api/projects/999999/node-exclusions").status_code == 404
        r = client.post("/api/projects/999999/node-exclusions", json={"pattern": "a/"})
        assert r.status_code == 404

    def test_delete_unknown_row_404(self, client, make_project):
        p = make_project()
        assert client.delete(f"/api/projects/{p['id']}/node-exclusions/999999").status_code == 404


class TestDocLaneExclusions:
    def test_enumerate_drops_excluded_targets(self, tmp_path):
        _write(tmp_path / "README.md", "readme\n")
        _write(tmp_path / "docs" / "pm_playbook.md", "playbook\n")
        _write(tmp_path / "docs" / "generated.md", "gen\n")
        assert dp.enumerate_doc_targets(str(tmp_path)) == [
            "README.md", "docs/generated.md", "docs/pm_playbook.md",
        ]
        kept = dp.enumerate_doc_targets(str(tmp_path), exclusions=("docs/generated.md",))
        assert kept == ["README.md", "docs/pm_playbook.md"]
        # The unfiltered view still reports the candidate, for the prune scope.
        assert "docs/generated.md" in dp.enumerate_doc_targets(
            str(tmp_path), exclusions=("docs/generated.md",), include_excluded=True
        )

    def test_excluded_doc_never_becomes_a_unit_but_stays_in_prune_scope(self, tmp_path):
        _write(tmp_path / "README.md", "widget readme\n")
        _write(tmp_path / "docs" / "legacy.md", "widget legacy\n")
        units, prune = dp.build_doc_units(str(tmp_path), exclusions=("docs/legacy.md",))
        assert {u.ref for u in units} == {"README.md"}
        assert ("doc", "docs/legacy.md") in prune

    def test_turning_on_an_exclusion_prunes_then_deleting_it_restores(
        self, db_session, make_project, tmp_path
    ):
        """Both halves of the AC: excluding prunes existing pointers, and
        removing the row restores them on the next scan."""
        p = make_project(repo_path=str(tmp_path))
        pid = p["id"]
        _write(tmp_path / "README.md", "widget readme\n")
        _write(tmp_path / "docs" / "legacy.md", "widget legacy\n")
        # Live 2-domain seed on refs outside the doc scope.
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref="m", text="widget"),
            SourceUnit(kind="code", ref="seed.py", text="widget"),
        ])
        # No exclusion rows yet -> indexes exactly as before the ticket.
        dp.ground_docs(db_session, pid, str(tmp_path))
        db_session.flush()
        assert "docs/legacy.md" in _refs(db_session, pid, NodePointerKind.doc)

        row = nx.add_exclusion(db_session, pid, "docs/legacy.md")
        dp.ground_docs(db_session, pid, str(tmp_path))
        db_session.flush()
        assert "docs/legacy.md" not in _refs(db_session, pid, NodePointerKind.doc)
        assert "README.md" in _refs(db_session, pid, NodePointerKind.doc)

        nx.delete_exclusion(db_session, pid, row.id)
        dp.ground_docs(db_session, pid, str(tmp_path))
        db_session.flush()
        assert "docs/legacy.md" in _refs(db_session, pid, NodePointerKind.doc)


class TestCodeLaneExclusions:
    def test_build_code_units_skips_excluded_and_prunes_them(self, repo):
        sha = _commit(repo, {
            "backend/app/services/widget.py": "widget core\n",
            "backend/tests/test_widget.py": "widget test\n",
            ".claude/pm_playbook.md": "widget playbook\n",
            "docs/pm_playbook.md": "widget playbook\n",
        }, "ZZ-1 add widget")
        units, prune = cp.build_code_units(str(repo), sha, exclusions=DEFAULTS)
        refs = {u.ref for u in units}
        assert "backend/app/services/widget.py" in refs
        assert "docs/pm_playbook.md" in refs
        assert "backend/tests/test_widget.py" not in refs
        assert ".claude/pm_playbook.md" not in refs
        # Excluded files still enter the prune scope.
        assert ("code", "backend/tests/test_widget.py") in prune
        assert ("code", ".claude/pm_playbook.md") in prune

    def test_no_exclusions_indexes_everything(self, repo):
        sha = _commit(repo, {
            "backend/app/services/widget.py": "widget core\n",
            "backend/tests/test_widget.py": "widget test\n",
        }, "ZZ-1 add widget")
        units, _ = cp.build_code_units(str(repo), sha)
        assert "backend/tests/test_widget.py" in {u.ref for u in units}

    def test_code_provider_uses_the_projects_rows(self, db_session, make_project, repo):
        p = make_project(repo_path=str(repo), prefix="ZZ")
        _commit(repo, {
            "backend/app/services/widget.py": "widget core\n",
            "backend/tests/test_widget.py": "widget test\n",
            ".claude/pm_playbook.md": "widget playbook\n",
        }, "ZZ-1 add widget")
        project = db_session.get(Project, p["id"])
        refs = {u.ref for u in cp.code_provider(db_session, project, str(repo))}
        assert refs == {"backend/app/services/widget.py"}

    def test_ground_commit_prunes_a_newly_excluded_file_then_restores_it(
        self, db_session, make_project, repo
    ):
        p = make_project(repo_path=str(repo))
        pid = p["id"]
        # Live 2-domain seed on refs outside the commit's scope.
        register_sources(db_session, pid, [
            SourceUnit(kind="memory", ref="m", text="widget"),
            SourceUnit(kind="doc", ref="seed.md", text="widget"),
        ])
        # Clear the seeded defaults so the first pass indexes everything.
        for row in nx.list_exclusions(db_session, pid):
            nx.delete_exclusion(db_session, pid, row.id)
        sha = _commit(repo, {
            "backend/app/services/widget.py": "widget core\n",
            "backend/tests/test_widget.py": "widget test\n",
        }, "ZZ-1 add widget")
        cp.ground_commit(db_session, pid, str(repo), sha)
        db_session.flush()
        assert "backend/tests/test_widget.py" in _refs(db_session, pid, NodePointerKind.code)

        row = nx.add_exclusion(db_session, pid, "backend/tests/")
        cp.ground_commit(db_session, pid, str(repo), sha)
        db_session.flush()
        code_refs = _refs(db_session, pid, NodePointerKind.code)
        assert "backend/tests/test_widget.py" not in code_refs
        assert "backend/app/services/widget.py" in code_refs

        # Deleting the row restores the pointers on the next scan (AC).
        nx.delete_exclusion(db_session, pid, row.id)
        cp.ground_commit(db_session, pid, str(repo), sha)
        db_session.flush()
        assert "backend/tests/test_widget.py" in _refs(db_session, pid, NodePointerKind.code)


class TestSeedingRace:
    """DWB-567: two first views of the same project must not collide.

    These tests use REAL, separately committing sessions rather than the shared
    ``db_session`` fixture, and that is the whole point. Every other test in this
    file runs inside one transaction, where a second call sees the first call's
    uncommitted rows and skips them: a sequential test passes against the broken
    code and proves nothing. The condition being tested only exists between two
    transactions.
    """

    @staticmethod
    def _session():
        """A real session on the test DB, resolved at call time.

        conftest repoints ``app.database.SessionLocal`` at the lat_test engine;
        reading it through the module (rather than importing the name) means we
        cannot bind the production factory by import order. The assertion is a
        hard stop so a wiring change can never let these committing tests loose
        on the dev database.
        """
        import app.database as app_database

        session = app_database.SessionLocal()
        assert "lat_test" in str(session.get_bind().url), (
            "refusing to run a committing test outside lat_test"
        )
        return session

    PREFIX = "RCE"

    @classmethod
    def _drop_projects(cls):
        """Remove any project of ours, plus its rows.

        These rows are COMMITTED, so the surrounding rollback fixture does not
        clean them up and projects.prefix is unique: a test that died mid-way
        would otherwise poison every later test in the class. Runs before and
        after each one.
        """
        session = cls._session()
        try:
            ids = list(
                session.scalars(
                    select(Project.id).where(Project.prefix == cls.PREFIX)
                ).all()
            )
            if ids:
                session.query(NodeExclusion).filter(
                    NodeExclusion.project_id.in_(ids)
                ).delete(synchronize_session=False)
                session.query(Project).filter(Project.id.in_(ids)).delete(
                    synchronize_session=False
                )
                session.commit()
        finally:
            session.close()

    @pytest.fixture
    def raw_project(self):
        """A committed, never-seeded project, torn down after the test."""
        self._drop_projects()
        setup = self._session()
        try:
            project = Project(prefix=self.PREFIX, name="DWB567 race")
            setup.add(project)
            setup.commit()
            pid = project.id
        finally:
            setup.close()

        yield pid

        self._drop_projects()

    def _committed_state(self, pid):
        check = self._session()
        try:
            rows = check.scalars(
                select(NodeExclusion.pattern).where(
                    NodeExclusion.project_id == pid
                )
            ).all()
            return sorted(rows), check.get(Project, pid).node_exclusions_seeded
        finally:
            check.close()

    def test_race_loser_gets_the_full_list(self, raw_project):
        """The deterministic form of the bug: no threads, no timing luck.

        The loser is simply a transaction that opened before the winner
        committed. Against the pre-fix code this raises IntegrityError on the
        duplicate insert, which is the 500 Miles saw.
        """
        pid = raw_project
        loser = self._session()
        try:
            # Opening read: fixes the loser's snapshot before anything is seeded.
            loser.get(Project, pid)

            winner = self._session()
            try:
                assert len(nx.list_exclusions(winner, pid)) == len(DEFAULTS)
                winner.commit()
            finally:
                winner.close()

            rows = nx.list_exclusions(loser, pid)
            assert [r.pattern for r in rows] == list(DEFAULTS)
            loser.commit()
        finally:
            loser.close()

        patterns, seeded = self._committed_state(pid)
        assert patterns == sorted(DEFAULTS)
        assert seeded is True

    def test_race_loser_does_not_degrade_to_indexing_everything(self, raw_project):
        """AC 5. patterns_for_project swallows any exception and returns (),
        which the grounding lanes read as "exclude nothing". The race therefore
        used to fail SILENTLY here rather than loudly: a scan that lost the race
        indexed every path the project meant to exclude. An empty tuple is the
        wrong answer, so assert the real list."""
        pid = raw_project
        loser = self._session()
        try:
            loser.get(Project, pid)

            winner = self._session()
            try:
                nx.list_exclusions(winner, pid)
                winner.commit()
            finally:
                winner.close()

            assert nx.patterns_for_project(loser, pid) == DEFAULTS
            loser.commit()
        finally:
            loser.close()

    def test_concurrent_first_views_both_return_the_defaults(self, raw_project):
        """Genuinely simultaneous first views, synchronized on a barrier.

        Which transaction wins is not asserted: every interleaving must give
        both callers the full list and leave exactly one set of rows behind.
        """
        import threading

        pid = raw_project
        barrier = threading.Barrier(2)
        results: dict[int, tuple] = {}

        def view(idx):
            session = self._session()
            try:
                session.get(Project, pid)
                barrier.wait(timeout=20)
                rows = nx.list_exclusions(session, pid)
                session.commit()
                results[idx] = ("ok", [r.pattern for r in rows])
            except Exception as e:  # noqa: BLE001 - reported as a failure below
                session.rollback()
                results[idx] = ("error", f"{type(e).__name__}: {e}")
            finally:
                session.close()

        threads = [threading.Thread(target=view, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive(), "a concurrent first view never finished"

        for idx in (0, 1):
            kind, payload = results[idx]
            assert kind == "ok", f"view {idx} failed: {payload}"
            assert payload == list(DEFAULTS), f"view {idx} got {payload}"

        patterns, seeded = self._committed_state(pid)
        assert patterns == sorted(DEFAULTS), "seeding was not exactly-once"
        assert seeded is True

    def test_concurrent_reads_never_reseed_a_cleared_project(self, raw_project):
        """AC 2 under concurrency: the seed-once contract is what makes deleting
        a default permanent, and the lock must not weaken it. A user who removes
        every default keeps an empty list no matter how many readers arrive."""
        import threading

        pid = raw_project
        setup = self._session()
        try:
            for row in nx.list_exclusions(setup, pid):
                nx.delete_exclusion(setup, pid, row.id)
            setup.commit()
        finally:
            setup.close()

        barrier = threading.Barrier(2)
        results: dict[int, tuple] = {}

        def view(idx):
            session = self._session()
            try:
                session.get(Project, pid)
                barrier.wait(timeout=20)
                rows = nx.list_exclusions(session, pid)
                session.commit()
                results[idx] = ("ok", [r.pattern for r in rows])
            except Exception as e:  # noqa: BLE001 - reported as a failure below
                session.rollback()
                results[idx] = ("error", f"{type(e).__name__}: {e}")
            finally:
                session.close()

        threads = [threading.Thread(target=view, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        for idx in (0, 1):
            assert results[idx] == ("ok", []), results[idx]

        patterns, seeded = self._committed_state(pid)
        assert patterns == []
        assert seeded is True

    def test_duplicate_insert_still_raises(self, raw_project):
        """AC 3. The fix removes the conflict instead of catching it, so nothing
        in this module swallows an IntegrityError. If someone later wraps the
        seed in a broad try/except, a genuine duplicate would go quiet: this
        fails the moment that happens."""
        from sqlalchemy.exc import IntegrityError

        pid = raw_project
        session = self._session()
        try:
            nx.list_exclusions(session, pid)
            session.commit()

            session.add(NodeExclusion(project_id=pid, pattern=DEFAULTS[0]))
            with pytest.raises(IntegrityError):
                session.flush()
        finally:
            session.rollback()
            session.close()

    def test_first_view_lock_does_not_serialize_later_views(self, raw_project):
        """The lock is on the slow path only. Once a project is seeded, two
        overlapping readers must both complete without either waiting on the
        other, which is what keeps the fix off the hot path."""
        pid = raw_project
        setup = self._session()
        try:
            nx.list_exclusions(setup, pid)
            setup.commit()
        finally:
            setup.close()

        first = self._session()
        second = self._session()
        try:
            # Overlapping transactions, both post-seed: neither takes a lock, so
            # this cannot block regardless of the order the statements interleave.
            assert len(nx.list_exclusions(first, pid)) == len(DEFAULTS)
            assert len(nx.list_exclusions(second, pid)) == len(DEFAULTS)
            first.commit()
            second.commit()
        finally:
            first.close()
            second.close()
