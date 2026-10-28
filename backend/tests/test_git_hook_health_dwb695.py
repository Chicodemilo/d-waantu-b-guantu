# Path: tests/test_git_hook_health_dwb695.py
# File: test_git_hook_health_dwb695.py
# Created: 2026-10-28
# Purpose: DWB-695 - the health check that tells UNARMED apart from QUIET, every state
# Caller: pytest
# Callees: app/services/git_hook_health.hook_status, GET /api/projects/{id}/hook-status, scripts/install-git-hooks.sh
# Data In: real throwaway git repositories under tmp_path
# Data Out: Assertions on armed / state / silence_means, and on installer agreement
# Last Modified: 2026-10-28

"""DWB-695: "nobody committed" and "nothing was ever installed" are the same
observation from inside DWB, and that is the actual defect.

Arming a clone takes one local action and always will - git deliberately
refuses to execute hooks that arrive with a clone, because that would be
arbitrary code execution on `git clone`. So the goal is not to remove the step.
It is to make its absence VISIBLE.

EVERY STATE BELOW WAS CONFIRMED AGAINST REAL GIT BEFORE IT WAS CODED, not
assumed from documentation:

  - `core.hooksPath` REPLACES the hooks directory. Set it to an empty dir and
    `.git/hooks` is switched off with it - eleven samples still sitting there,
    none of them reachable. Measured; this is live on IND today.
  - git SILENTLY SKIPS a non-executable hook. It prints a hint to the
    COMMITTER's terminal, which never reaches DWB, so from here it is
    indistinguishable from no hook at all.

Both are states where a repository looks configured and reports nothing, which
is why each is named rather than collapsed into "no hook".
"""

import os
import subprocess
from pathlib import Path

import pytest

from app.models.project import Project
from app.services import git_hook_health

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_HOOK = REPO_ROOT / "scripts" / "hooks" / "post-commit"
INSTALLER = REPO_ROOT / "scripts" / "install-git-hooks.sh"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def bare_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Probe")
    _git(repo, "config", "user.email", "probe@example.invalid")
    return repo


@pytest.fixture
def hook_project(make_project, bare_repo):
    return make_project(repo_path=str(bare_repo), prefix="HKT")


def _status(db_session, project_dict):
    project = db_session.get(Project, project_dict["id"])
    return git_hook_health.hook_status(db_session, project)


def _write_hook(path: Path, body: str, *, executable: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    if executable:
        path.chmod(0o755)
    else:
        path.chmod(0o644)


DWB_BODY = "#!/usr/bin/env bash\ncurl -X POST http://x/api/hooks/post-commit\n"
FOREIGN_BODY = "#!/usr/bin/env bash\necho 'some other project hook'\n"


class TestArmedStates:

    def test_a_repo_with_no_hook_is_UNARMED_and_says_so(
        self, db_session, hook_project, bare_repo
    ):
        r = _status(db_session, hook_project)
        assert r["armed"] is False
        assert r["state"] == git_hook_health.STATE_NO_HOOK
        assert "UNARMED" in r["silence_means"]
        assert "not by the work" in r["silence_means"], (
            "the reading must warn against reading zero rows as 'nothing was "
            "committed' - that misreading is the whole defect"
        )

    def test_an_installed_dwb_hook_is_ARMED(
        self, db_session, hook_project, bare_repo
    ):
        _write_hook(bare_repo / ".git" / "hooks" / "post-commit", DWB_BODY)
        r = _status(db_session, hook_project)
        assert r["armed"] is True
        assert r["state"] == git_hook_health.STATE_ARMED
        assert "ARMED AND QUIET" in r["silence_means"], (
            "an armed project with no rows must say the silence IS about the work"
        )

    def test_a_non_executable_hook_is_UNARMED(
        self, db_session, hook_project, bare_repo
    ):
        """Git skips it and tells only the committer. Confirmed against real
        git: the commit succeeds, the hook does not run, DWB hears nothing."""
        _write_hook(
            bare_repo / ".git" / "hooks" / "post-commit", DWB_BODY, executable=False
        )
        r = _status(db_session, hook_project)
        assert r["armed"] is False
        assert r["state"] == git_hook_health.STATE_NOT_EXECUTABLE
        assert "not executable" in r["silence_means"]

    def test_a_foreign_hook_is_UNARMED_because_it_never_tells_dwb(
        self, db_session, hook_project, bare_repo
    ):
        """A post-commit hook that runs is not the same as one that reports.
        Keying on the ENDPOINT rather than on the file name or a symlink target
        is deliberate: an operator may copy the script or fold the POST into a
        hook of their own, and both of those are genuinely armed."""
        _write_hook(bare_repo / ".git" / "hooks" / "post-commit", FOREIGN_BODY)
        r = _status(db_session, hook_project)
        assert r["armed"] is False
        assert r["state"] == git_hook_health.STATE_FOREIGN_HOOK

    def test_hooks_path_override_is_reported_AND_disables_the_default(
        self, db_session, hook_project, bare_repo
    ):
        """THE IND FAILURE, pinned.

        A hook sitting in `.git/hooks` is unreachable the moment core.hooksPath
        points elsewhere. The repo looks configured and runs nothing, which is
        the state most likely to be mistaken for progress.
        """
        # A perfectly good hook in the DEFAULT location...
        _write_hook(bare_repo / ".git" / "hooks" / "post-commit", DWB_BODY)
        # ...and an override pointing at an empty directory.
        (bare_repo / ".githooks").mkdir()
        _git(bare_repo, "config", "core.hooksPath", ".githooks")

        r = _status(db_session, hook_project)
        assert r["armed"] is False, (
            "a hook in .git/hooks must NOT count as armed once core.hooksPath "
            "points somewhere else - git will never run it"
        )
        assert r["hooks_path_override"] == ".githooks"
        assert r["hooks_path_overrides_default"] is True
        assert "DISABLES .git/hooks" in r["silence_means"]
        assert r["hooks_dir"].endswith(".githooks")


class TestCannotAnswerIsNotUnarmed:

    def test_no_repo_path_is_NULL_not_False(self, db_session, make_project):
        """Three-valued on purpose, same convention as gate-status.

        Reporting "unarmed" for a project DWB cannot look at would be inventing
        a finding out of a missing field.
        """
        project = make_project(repo_path=None)
        r = _status(db_session, project)
        assert r["armed"] is None
        assert r["state"] == git_hook_health.STATE_NO_REPO_PATH
        assert "CANNOT SAY" in r["silence_means"]

    def test_an_unreadable_repo_path_is_NULL_not_False(
        self, db_session, make_project, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path / "does-not-exist"))
        r = _status(db_session, project)
        assert r["armed"] is None
        assert r["state"] == git_hook_health.STATE_REPO_UNREADABLE

    def test_a_directory_that_is_not_a_git_repo_is_NULL(
        self, db_session, make_project, tmp_path
    ):
        plain = tmp_path / "plain"
        plain.mkdir()
        project = make_project(repo_path=str(plain))
        r = _status(db_session, plain and {"id": project["id"]})
        assert r["armed"] is None

    def test_null_is_falsy_so_a_naive_check_lands_safe(
        self, db_session, make_project
    ):
        """Documented consequence, asserted so it cannot drift: `if armed`
        treats 'could not look' as not-armed, which is the safe direction. A
        caller acting ON unarmed must test `is False`."""
        project = make_project(repo_path=None)
        r = _status(db_session, project)
        assert not r["armed"]
        assert r["armed"] is not False


class TestHookStatusEndpoint:

    def test_endpoint_returns_the_status(self, client, hook_project, bare_repo):
        _write_hook(bare_repo / ".git" / "hooks" / "post-commit", DWB_BODY)
        r = client.get(f"/api/projects/{hook_project['id']}/hook-status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["armed"] is True
        assert body["silence_means"]

    def test_endpoint_404s_on_an_unknown_project(self, client):
        assert client.get("/api/projects/99999999/hook-status").status_code == 404


class TestInstallerAgreesWithTheHealthCheck:
    """The installer decides 'armed' in bash and the service decides it in
    Python. Two implementations of one predicate drift, and the drift would be
    silent: an operator would see ARMED and DWB would report unarmed, or worse
    the reverse. These pin them together on the cases that differ."""

    @pytest.mark.skipif(not INSTALLER.exists(), reason="installer not present")
    def test_check_mode_reports_unarmed_and_installs_NOTHING(self, bare_repo):
        """--check must be read-only. An earlier run of this probe appeared to
        pass while silently installing, because the throwaway clone carried the
        COMMITTED installer rather than the working-tree one - so the assertion
        that nothing was created is the one that matters here."""
        (bare_repo / "scripts" / "hooks").mkdir(parents=True)
        (bare_repo / "scripts" / "install-git-hooks.sh").write_text(
            INSTALLER.read_text()
        )
        (bare_repo / "scripts" / "install-git-hooks.sh").chmod(0o755)
        (bare_repo / "scripts" / "hooks" / "post-commit").write_text(
            SHIPPED_HOOK.read_text()
        )
        (bare_repo / "scripts" / "hooks" / "post-commit").chmod(0o755)

        out = subprocess.run(
            [str(bare_repo / "scripts" / "install-git-hooks.sh"), "--check"],
            cwd=str(bare_repo), capture_output=True, text=True,
        )
        assert out.returncode == 1, f"--check should exit 1 when unarmed: {out.stdout}"
        assert "UNARMED" in out.stdout
        assert not (bare_repo / ".git" / "hooks" / "post-commit").exists(), (
            "--check installed a hook; it must change nothing"
        )

    @pytest.mark.skipif(not INSTALLER.exists(), reason="installer not present")
    def test_install_then_both_agree_it_is_armed(self, db_session, hook_project, bare_repo):
        (bare_repo / "scripts" / "hooks").mkdir(parents=True)
        (bare_repo / "scripts" / "install-git-hooks.sh").write_text(
            INSTALLER.read_text()
        )
        (bare_repo / "scripts" / "install-git-hooks.sh").chmod(0o755)
        (bare_repo / "scripts" / "hooks" / "post-commit").write_text(
            SHIPPED_HOOK.read_text()
        )
        (bare_repo / "scripts" / "hooks" / "post-commit").chmod(0o755)

        out = subprocess.run(
            [str(bare_repo / "scripts" / "install-git-hooks.sh")],
            cwd=str(bare_repo), capture_output=True, text=True,
        )
        assert out.returncode == 0, f"install failed: {out.stdout} {out.stderr}"
        assert "ARMED" in out.stdout, "the installer did not verify its own work"

        # ...and the service independently agrees.
        r = _status(db_session, hook_project)
        assert r["armed"] is True, (
            "the installer reported ARMED and the health check disagrees - the "
            "bash and Python definitions have drifted"
        )

    @pytest.mark.skipif(not INSTALLER.exists(), reason="installer not present")
    def test_both_call_a_non_executable_hook_unarmed(
        self, db_session, hook_project, bare_repo
    ):
        """The case the two implementations are most likely to differ on,
        because it is the one a naive existence check gets wrong."""
        (bare_repo / "scripts" / "install-git-hooks.sh").parent.mkdir(
            parents=True, exist_ok=True
        )
        (bare_repo / "scripts" / "install-git-hooks.sh").write_text(
            INSTALLER.read_text()
        )
        (bare_repo / "scripts" / "install-git-hooks.sh").chmod(0o755)
        _write_hook(
            bare_repo / ".git" / "hooks" / "post-commit", DWB_BODY, executable=False
        )

        out = subprocess.run(
            [str(bare_repo / "scripts" / "install-git-hooks.sh"), "--check"],
            cwd=str(bare_repo), capture_output=True, text=True,
        )
        assert out.returncode == 1
        assert "NOT EXECUTABLE" in out.stdout

        r = _status(db_session, hook_project)
        assert r["armed"] is False
        assert r["state"] == git_hook_health.STATE_NOT_EXECUTABLE
        assert os.access(bare_repo / ".git" / "hooks" / "post-commit", os.X_OK) is False
