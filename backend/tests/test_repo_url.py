# Path:          tests/test_repo_url.py
# File:          test_repo_url.py
# Created:       2026-06-25
# Purpose:       Unit tests for git-remote -> GitHub web base derivation (DWBG-021)
# Caller:        pytest
# Callees:       app.services.repo_url.normalize_github_remote / derive_repo_web_url
# Data In:       Raw remote URL strings; a real git repo created under tmp_path
# Data Out:      Assertions on normalized web base / None
# Last Modified: 2026-06-25

"""Tests for repo web-URL derivation.

normalize_github_remote is a pure string function: it covers the SSH and HTTPS
normalization matrix and every null case without touching the filesystem.
derive_repo_web_url is exercised against a real git repo under tmp_path plus the
no-repo / bad-path null paths, and the ProjectRead schema is checked to surface
the computed field.
"""

import subprocess

import pytest

from app.services.repo_url import derive_repo_web_url, normalize_github_remote


class TestNormalizeGithubRemote:
    def test_ssh_form_with_dotgit(self):
        assert (
            normalize_github_remote("git@github.com:owner/repo.git")
            == "https://github.com/owner/repo"
        )

    def test_ssh_form_without_dotgit(self):
        assert (
            normalize_github_remote("git@github.com:owner/repo")
            == "https://github.com/owner/repo"
        )

    def test_https_form_with_dotgit_is_stripped(self):
        assert (
            normalize_github_remote("https://github.com/owner/repo.git")
            == "https://github.com/owner/repo"
        )

    def test_https_form_without_dotgit(self):
        assert (
            normalize_github_remote("https://github.com/owner/repo")
            == "https://github.com/owner/repo"
        )

    def test_https_with_userinfo(self):
        assert (
            normalize_github_remote("https://user@github.com/owner/repo.git")
            == "https://github.com/owner/repo"
        )

    def test_ssh_url_scheme_form(self):
        assert (
            normalize_github_remote("ssh://git@github.com/owner/repo.git")
            == "https://github.com/owner/repo"
        )

    def test_git_scheme_form(self):
        assert (
            normalize_github_remote("git://github.com/owner/repo.git")
            == "https://github.com/owner/repo"
        )

    def test_trailing_slash_tolerated(self):
        assert (
            normalize_github_remote("https://github.com/owner/repo/")
            == "https://github.com/owner/repo"
        )

    def test_hyphenated_owner_and_repo(self):
        assert (
            normalize_github_remote("git@github.com:my-org/my-repo.git")
            == "https://github.com/my-org/my-repo"
        )

    # --- null cases ---

    def test_none_input_returns_none(self):
        assert normalize_github_remote(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_github_remote("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_github_remote("   \n ") is None

    def test_non_github_https_returns_none(self):
        assert normalize_github_remote("https://gitlab.com/owner/repo.git") is None

    def test_non_github_ssh_returns_none(self):
        assert normalize_github_remote("git@bitbucket.org:owner/repo.git") is None

    def test_github_lookalike_subdomain_returns_none(self):
        # not github.com proper
        assert normalize_github_remote("https://github.com.evil.com/owner/repo") is None

    def test_garbage_returns_none(self):
        assert normalize_github_remote("not a url at all") is None


class TestDeriveRepoWebUrl:
    def test_none_path_returns_none(self):
        assert derive_repo_web_url(None) is None

    def test_nonexistent_path_returns_none(self, tmp_path):
        bogus = tmp_path / "does-not-exist"
        assert derive_repo_web_url(str(bogus)) is None

    def test_path_that_is_not_a_repo_returns_none(self, tmp_path):
        # tmp_path exists but is not a git repo -> git config returns non-zero
        assert derive_repo_web_url(str(tmp_path)) is None

    def test_real_repo_ssh_remote(self, tmp_path):
        repo = tmp_path / "repo-ssh"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        assert derive_repo_web_url(str(repo)) == "https://github.com/owner/repo"

    def test_real_repo_https_remote_strips_dotgit(self, tmp_path):
        repo = tmp_path / "repo-https"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
            cwd=repo,
            check=True,
        )
        assert derive_repo_web_url(str(repo)) == "https://github.com/owner/repo"

    def test_real_repo_non_github_remote_returns_none(self, tmp_path):
        repo = tmp_path / "repo-gitlab"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/owner/repo.git"],
            cwd=repo,
            check=True,
        )
        assert derive_repo_web_url(str(repo)) is None

    def test_real_repo_no_remote_returns_none(self, tmp_path):
        repo = tmp_path / "repo-no-remote"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        assert derive_repo_web_url(str(repo)) is None


class TestProjectReadSurfacesRepoUrl:
    def test_repo_url_present_and_null_off_non_repo(self, client, tmp_path):
        # A project whose repo_path is a plain dir (not a git repo) -> repo_url null.
        project = client.post(
            "/api/projects",
            json={"prefix": "RU", "name": "Repo URL Test", "repo_path": str(tmp_path)},
        ).json()
        data = client.get(f"/api/projects/{project['id']}").json()
        assert "repo_url" in data
        assert data["repo_url"] is None

    def test_repo_url_derived_from_real_github_repo(self, client, tmp_path):
        repo = tmp_path / "gh-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        project = client.post(
            "/api/projects",
            json={"prefix": "RU2", "name": "Repo URL Real", "repo_path": str(repo)},
        ).json()
        assert project["repo_url"] == "https://github.com/owner/repo"
