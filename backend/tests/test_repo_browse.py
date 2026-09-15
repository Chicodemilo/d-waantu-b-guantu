# Path: tests/test_repo_browse.py
# File: test_repo_browse.py
# Created: 2026-09-15
# Purpose: DWB-553 - the read-only repo directory browser. Covers root and nested
#          listings, repo-relative normalization, the three containment checks
#          (syntactic traversal, absolute input, and a symlink resolving outside
#          the root), the dot-directory/node_modules/__pycache__ skips, missing repo_path,
#          and that the endpoint writes nothing.
# Caller: pytest (named for app/routers/repo_browse.py so the force_test_coverage gate sees the router as covered)
# Callees: app/services/repo_browse, app/routers/repo_browse
# Data In: pytest fixtures (client, make_project, tmp_path) + a fixture directory tree
# Data Out: assertions
# Last Modified: 2026-09-15

import pytest

from app.services import repo_browse as rb


@pytest.fixture
def repo(tmp_path):
    """A small tree: real dirs, a file, a dot dir, node_modules, and a nested level."""
    (tmp_path / "backend" / "app" / "services").mkdir(parents=True)
    (tmp_path / "backend" / "tests").mkdir()
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "backend" / "app" / "__pycache__").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "backend" / "app" / "main.py").write_text("x\n")
    return tmp_path


def _names(listing):
    return [d["name"] for d in listing["directories"]]


class TestListDirectories:
    def test_root_listing(self, repo):
        out = rb.list_directories(str(repo))
        assert out["parent"] == ""
        assert _names(out) == ["backend", "build", "docs", "frontend"]
        # Repo-relative paths, ready to send back as parent.
        assert [d["path"] for d in out["directories"]] == [
            "backend", "build", "docs", "frontend",
        ]

    def test_nested_listing(self, repo):
        out = rb.list_directories(str(repo), "backend")
        assert out["parent"] == "backend"
        assert _names(out) == ["app", "tests"]
        assert [d["path"] for d in out["directories"]] == ["backend/app", "backend/tests"]

    def test_two_levels_down(self, repo):
        out = rb.list_directories(str(repo), "backend/app")
        assert _names(out) == ["services"]
        assert out["directories"][0]["path"] == "backend/app/services"

    def test_directories_only_no_files(self, repo):
        out = rb.list_directories(str(repo))
        assert "README.md" not in _names(out)
        nested = rb.list_directories(str(repo), "backend/app")
        assert "main.py" not in _names(nested)

    def test_generated_dirs_and_dot_dirs_skipped(self, repo):
        names = _names(rb.list_directories(str(repo)))
        assert ".git" not in names
        assert ".claude" not in names
        assert "node_modules" not in names
        assert "__pycache__" not in names

    def test_pycache_skipped_at_every_level(self, repo):
        """It is generated output wherever it appears, not just at the root."""
        nested = _names(rb.list_directories(str(repo), "backend/app"))
        assert "__pycache__" not in nested
        assert nested == ["services"]

    def test_ambiguous_names_are_still_listed(self, repo):
        """build/ is output in some repos and source in others, so hiding it
        would remove a subtree the user may legitimately need to reach."""
        assert "build" in _names(rb.list_directories(str(repo)))

    def test_empty_directory_lists_empty(self, repo):
        out = rb.list_directories(str(repo), "docs")
        assert out["directories"] == []
        assert out["parent"] == "docs"

    @pytest.mark.parametrize("raw,expected", [
        ("", ""),
        ("   ", ""),
        ("./backend", "backend"),
        ("backend/", "backend"),
        ("/backend", None),          # absolute -> refused, see below
    ])
    def test_parent_normalization(self, repo, raw, expected):
        if expected is None:
            with pytest.raises(rb.RepoBrowseError):
                rb.list_directories(str(repo), raw)
        else:
            assert rb.list_directories(str(repo), raw)["parent"] == expected

    def test_backslashes_normalized(self, repo):
        assert rb.list_directories(str(repo), "backend\\app")["parent"] == "backend/app"


class TestContainment:
    @pytest.mark.parametrize("attempt", [
        "..",
        "../",
        "../../etc",
        "backend/../../etc",
        "backend/../..",
    ])
    def test_traversal_refused_with_a_reason(self, repo, attempt):
        with pytest.raises(rb.RepoBrowseError) as ei:
            rb.list_directories(str(repo), attempt)
        assert ei.value.code == "invalid_path"
        assert "escape the repo root" in ei.value.detail

    @pytest.mark.parametrize("attempt", ["/etc", "/etc/passwd", "~/secrets", "C:/Windows"])
    def test_absolute_refused_with_a_reason(self, repo, attempt):
        with pytest.raises(rb.RepoBrowseError) as ei:
            rb.list_directories(str(repo), attempt)
        assert ei.value.code == "invalid_path"
        assert "not absolute" in ei.value.detail

    def test_symlink_out_of_the_repo_is_not_browsable(self, repo, tmp_path):
        """The check no string inspection would catch: a link whose RESOLVED
        target sits outside the root."""
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        (outside / "secret").mkdir(exist_ok=True)
        link = repo / "escape_hatch"
        link.symlink_to(outside, target_is_directory=True)

        # It is not offered in the listing...
        assert "escape_hatch" not in _names(rb.list_directories(str(repo)))
        # ...and following it explicitly is refused.
        with pytest.raises(rb.RepoBrowseError) as ei:
            rb.list_directories(str(repo), "escape_hatch")
        assert ei.value.code == "invalid_path"

    def test_symlink_inside_the_repo_still_works(self, repo):
        (repo / "linked").symlink_to(repo / "docs", target_is_directory=True)
        assert "linked" in _names(rb.list_directories(str(repo)))


class TestRepoPathFailures:
    def test_missing_repo_path(self):
        for value in (None, ""):
            with pytest.raises(rb.RepoBrowseError) as ei:
                rb.list_directories(value)
            assert ei.value.code == "no_repo_path"

    def test_repo_path_not_a_directory(self, tmp_path):
        f = tmp_path / "a_file"
        f.write_text("x")
        with pytest.raises(rb.RepoBrowseError) as ei:
            rb.list_directories(str(f))
        assert ei.value.code == "no_repo_path"

    def test_unknown_directory_is_not_found(self, repo):
        with pytest.raises(rb.RepoBrowseError) as ei:
            rb.list_directories(str(repo), "nope/missing")
        assert ei.value.code == "not_found"


class TestRepoBrowseEndpoint:
    def test_root_and_nested_over_http(self, client, make_project, repo):
        p = make_project(repo_path=str(repo))
        r = client.get(f"/api/projects/{p['id']}/repo-directories")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["parent"] == ""
        assert [d["name"] for d in body["directories"]] == [
            "backend", "build", "docs", "frontend",
        ]
        assert set(body["directories"][0]) == {"name", "path"}

        nested = client.get(
            f"/api/projects/{p['id']}/repo-directories", params={"parent": "backend"}
        )
        assert nested.status_code == 200
        assert [d["path"] for d in nested.json()["directories"]] == [
            "backend/app", "backend/tests",
        ]

    def test_traversal_400_naming_why(self, client, make_project, repo):
        p = make_project(repo_path=str(repo))
        r = client.get(
            f"/api/projects/{p['id']}/repo-directories", params={"parent": "../../etc"}
        )
        assert r.status_code == 400, r.text
        assert "escape the repo root" in r.json()["detail"]

    def test_absolute_400_naming_why(self, client, make_project, repo):
        p = make_project(repo_path=str(repo))
        r = client.get(
            f"/api/projects/{p['id']}/repo-directories", params={"parent": "/etc"}
        )
        assert r.status_code == 400
        assert "not absolute" in r.json()["detail"]

    def test_missing_repo_path_400(self, client, make_project):
        p = make_project()          # no repo_path
        r = client.get(f"/api/projects/{p['id']}/repo-directories")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"]

    def test_unknown_directory_404(self, client, make_project, repo):
        p = make_project(repo_path=str(repo))
        r = client.get(
            f"/api/projects/{p['id']}/repo-directories", params={"parent": "nope"}
        )
        assert r.status_code == 404

    def test_unknown_project_404(self, client):
        assert client.get("/api/projects/999999/repo-directories").status_code == 404

    def test_endpoint_writes_nothing(self, client, db_session, make_project, repo):
        """Read-only: browsing must not create rows anywhere."""
        from sqlalchemy import func, select

        from app.models.node_exclusion import NodeExclusion

        p = make_project(repo_path=str(repo))
        before = db_session.scalar(select(func.count()).select_from(NodeExclusion))
        for parent in ("", "backend", "backend/app"):
            client.get(
                f"/api/projects/{p['id']}/repo-directories", params={"parent": parent}
            )
        assert db_session.scalar(select(func.count()).select_from(NodeExclusion)) == before
