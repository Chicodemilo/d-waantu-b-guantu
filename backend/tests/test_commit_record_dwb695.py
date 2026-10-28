# Path: tests/test_commit_record_dwb695.py
# File: test_commit_record_dwb695.py
# Created: 2026-10-28
# Purpose: DWB-695 - commit rows persist, idempotently, including keyless commits; and the data-availability floor
# Caller: pytest
# Callees: app/services/commit_record.py, app/services/code_pointers.py (commit_paths, commit_metadata), POST /api/hooks/post-commit
# Data In: real throwaway git repositories under tmp_path, factory fixtures
# Data Out: Assertions on Commit rows and on coverage_start / within_commit_coverage
# Last Modified: 2026-10-28

"""DWB-695: DWB has closed tickets from commit messages since DWB-345 and
stored nothing about the commit.

WHY THESE TESTS BUILD REAL GIT REPOSITORIES rather than mocking git. The whole
value of the row is that the server reads it back out of the repository, so a
mocked git would test the mock. Every assertion below runs against `git init`
plus real commits in `tmp_path`, which is also the only way to exercise the
cases that matter: a commit with NO ticket key, and a commit that DELETES a
file.

THE TWO THINGS MOST LIKELY TO BE GOT WRONG, both pinned here:

1. A KEYLESS COMMIT MUST STILL BE STORED. `process_post_commit` returns early
   with reason=no_ticket_keys_in_message, and 54.6% of this repo's 284 commits
   carry no key. If persistence hung off the auto-close outcome, the table
   would hold only the commits nobody needs to ask about.

2. THE FLOOR MUST BE FALSE WHEN THERE IS NO DATA. "No commit references this
   ticket" is true of all of history until this table has rows, so a detector
   without a floor fires on everything on its first run - 420 of 614 done
   tickets on project 1 today. `within_commit_coverage` returns False on an
   empty table, and that direction is the safe one.
"""

import subprocess
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.commit import Commit
from app.services import code_pointers, commit_record


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path):
    """A real git repository with a deterministic identity.

    Identity is set locally rather than relying on the machine's global config,
    so the author assertions below cannot pass or fail because of who ran them.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Probe Author")
    _git(repo, "config", "user.email", "probe@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")

    def commit(message, files=None, delete=None):
        for name, body in (files or {}).items():
            (repo / name).write_text(body)
            _git(repo, "add", name)
        for name in (delete or []):
            _git(repo, "rm", "-q", name)
        _git(repo, "commit", "-q", "-m", message, "--allow-empty")
        return _git(repo, "rev-parse", "HEAD")

    return repo, commit


@pytest.fixture
def commit_project(make_project, git_repo):
    repo, _ = git_repo
    return make_project(repo_path=str(repo), prefix="CMT")


class TestCommitRowPersists:

    def test_a_commit_with_a_ticket_key_is_stored_with_its_metadata(
        self, db_session, commit_project, git_repo
    ):
        repo, commit = git_repo
        sha = commit("CMT-1 add the thing", files={"a.py": "x = 1\n"})

        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])

        row = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-1 add the thing",
        )
        assert row is not None
        assert row.commit_sha == sha, "the full sha should round-trip"
        assert row.author_name == "Probe Author"
        assert row.author_email == "probe@example.invalid"
        assert row.ticket_keys == ["CMT-1"]
        assert row.changed_paths == ["a.py"]
        # Both timestamps present and naive (the column type), not tz-aware.
        assert row.authored_at is not None and row.authored_at.tzinfo is None
        assert row.committed_at is not None and row.committed_at.tzinfo is None

    def test_a_commit_with_NO_ticket_key_is_still_stored(
        self, db_session, commit_project, git_repo
    ):
        """The case the table exists for.

        54.6% of this repo's commits carry no key, and the auto-close path
        returns early on them. A keyless commit is not a non-event.
        """
        repo, commit = git_repo
        sha = commit("tidy up the imports", files={"b.py": "y = 2\n"})

        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])

        row = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="tidy up the imports",
        )
        assert row is not None, "a keyless commit was dropped"
        assert row.ticket_keys == []
        assert row.changed_paths == ["b.py"]

    def test_a_short_sha_does_not_create_a_second_row(
        self, db_session, commit_project, git_repo
    ):
        """The unique constraint compares strings, so an unexpanded short sha
        would store a SECOND row for a commit already held at full length and
        the duplicate would read as two commits to anything counting."""
        repo, commit = git_repo
        sha = commit("CMT-2 something", files={"c.py": "z = 3\n"})
        short = sha[:8]

        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])

        first = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-2 something",
        )
        second = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=short, commit_message="CMT-2 something",
        )
        assert first.id == second.id, "the short sha created a duplicate row"
        rows = db_session.execute(
            select(Commit).where(Commit.project_id == project.id)
        ).scalars().all()
        assert len(rows) == 1

    def test_an_unresolvable_sha_stores_nothing_and_does_not_raise(
        self, db_session, commit_project, git_repo
    ):
        repo, commit = git_repo
        commit("CMT-3 real", files={"d.py": "w = 4\n"})

        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])

        row = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            commit_message="CMT-3 real",
        )
        assert row is None
        rows = db_session.execute(
            select(Commit).where(Commit.project_id == project.id)
        ).scalars().all()
        assert rows == []


class TestChangedPathsIncludeDeletions:

    def test_a_deleted_file_appears_in_changed_paths(
        self, db_session, commit_project, git_repo
    ):
        """`commit_paths` exists instead of reusing `commit_files` precisely
        for this case: `commit_files` passes --diff-filter=d because a vanished
        file cannot host a code pointer, which is right for that lane and wrong
        here. A file the work DELETED is evidence the work touched it.

        The paired assertion on `commit_files` is the control: without it this
        test would pass against an implementation that had simply reused the
        existing helper on a commit that happened to also add a file.
        """
        repo, commit = git_repo
        commit("CMT-4 add two", files={"keep.py": "k = 1\n", "gone.py": "g = 1\n"})
        sha = commit("CMT-5 remove one", delete=["gone.py"])

        paths = code_pointers.commit_paths(str(repo), sha)
        files = code_pointers.commit_files(str(repo), sha)

        assert "gone.py" in paths, "commit_paths dropped the deletion"
        assert "gone.py" not in files, (
            "commit_files now reports deletions too, so commit_paths no longer "
            "differs from it and this test has stopped measuring anything"
        )

        # AND THE STORED ROW, which is the assertion that actually matters.
        # An earlier version of this test stopped at the two helper calls
        # above and a mutation swapping the service to `commit_files` SURVIVED
        # it: the helper was correct and unused. Asserting on the column is
        # what pins that the service calls the right one.
        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])
        row = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-5 remove one",
        )
        assert row is not None
        assert "gone.py" in (row.changed_paths or []), (
            "the persisted changed_paths dropped the deleted file, so the "
            "service is not using commit_paths"
        )


class TestDataAvailabilityFloor:

    def test_no_data_means_CANNOT_ANSWER_not_no_commits(
        self, db_session, commit_project
    ):
        """The floor's whole job. Before this table every ticket looked like
        'closed with no commit', because no commit was ever stored."""
        pid = commit_project["id"]
        assert commit_record.coverage_start(db_session, pid) is None
        assert commit_record.within_commit_coverage(
            db_session, pid, datetime(2026, 10, 28, 12, 0, 0)
        ) is False, "an empty table must not license a conclusion about a ticket"

    def test_a_close_before_the_first_commit_is_outside_coverage(
        self, db_session, commit_project, git_repo
    ):
        repo, commit = git_repo
        sha = commit("CMT-6 first", files={"e.py": "v = 5\n"})

        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])
        row = commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-6 first",
        )
        db_session.flush()

        start = commit_record.coverage_start(db_session, project.id)
        assert start is not None and start == row.committed_at

        before = row.committed_at - timedelta(days=1)
        after = row.committed_at + timedelta(days=1)
        assert commit_record.within_commit_coverage(db_session, project.id, before) is False
        assert commit_record.within_commit_coverage(db_session, project.id, after) is True
        # Boundary: the first commit's own instant is INSIDE coverage.
        assert commit_record.within_commit_coverage(
            db_session, project.id, row.committed_at
        ) is True

    def test_a_null_timestamp_is_outside_coverage(
        self, db_session, commit_project, git_repo
    ):
        """A ticket with no close time cannot be placed in any window, and
        guessing would put back the artefact the floor removes."""
        repo, commit = git_repo
        sha = commit("CMT-7 x", files={"f.py": "q = 6\n"})
        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])
        commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-7 x",
        )
        db_session.flush()
        assert commit_record.within_commit_coverage(db_session, project.id, None) is False

    def test_coverage_is_scoped_per_project(
        self, db_session, commit_project, git_repo, make_project
    ):
        """Two projects can be clones of one repository. One project's commit
        data says nothing about another's coverage."""
        repo, commit = git_repo
        sha = commit("CMT-8 y", files={"g.py": "r = 7\n"})
        from app.models.project import Project
        project = db_session.get(Project, commit_project["id"])
        commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-8 y",
        )
        db_session.flush()

        other = make_project()
        assert commit_record.coverage_start(db_session, project.id) is not None
        assert commit_record.coverage_start(db_session, other["id"]) is None


class TestPostCommitEndpointPersists:

    def test_the_hook_endpoint_stores_a_row_for_a_keyless_commit(
        self, client, db_session, commit_project, git_repo
    ):
        """End to end through the real route, on the case that would be lost
        if persistence hung off the auto-close result."""
        repo, commit = git_repo
        sha = commit("no key in this message at all", files={"h.py": "s = 8\n"})

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": str(repo),
            "commit_message": "no key in this message at all",
            "commit_sha": sha,
        })
        assert r.status_code == 200, r.text

        row = db_session.scalar(
            select(Commit).where(
                Commit.project_id == commit_project["id"],
                Commit.commit_sha == sha,
            )
        )
        assert row is not None, (
            "the endpoint did not persist a commit carrying no ticket key"
        )
        assert row.ticket_keys == []
        assert row.branch is None, "branch was not reported, so it must be NULL"

    def test_the_endpoint_accepts_and_stores_a_reported_branch(
        self, client, db_session, commit_project, git_repo
    ):
        """Branch is the one field git cannot recover later, so it can only
        arrive from the payload. A non-default value is used deliberately: a
        test asserting 'main' could pass against a hardcoded default."""
        repo, commit = git_repo
        sha = commit("CMT-9 on a branch", files={"i.py": "t = 9\n"})

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": str(repo),
            "commit_message": "CMT-9 on a branch",
            "commit_sha": sha,
            "branch": "feature/dwb-695-probe",
        })
        assert r.status_code == 200, r.text

        row = db_session.scalar(
            select(Commit).where(
                Commit.project_id == commit_project["id"],
                Commit.commit_sha == sha,
            )
        )
        assert row is not None
        assert row.branch == "feature/dwb-695-probe"

    def test_firing_the_hook_twice_stores_one_row(
        self, client, db_session, commit_project, git_repo
    ):
        repo, commit = git_repo
        sha = commit("CMT-10 twice", files={"j.py": "u = 10\n"})
        body = {
            "repo_path": str(repo),
            "commit_message": "CMT-10 twice",
            "commit_sha": sha,
        }
        assert client.post("/api/hooks/post-commit", json=body).status_code == 200
        assert client.post("/api/hooks/post-commit", json=body).status_code == 200

        rows = db_session.execute(
            select(Commit).where(
                Commit.project_id == commit_project["id"],
                Commit.commit_sha == sha,
            )
        ).scalars().all()
        assert len(rows) == 1, f"re-firing the hook stored {len(rows)} rows"


class TestProjectDeleteClearsCommits:

    def test_deleting_a_project_with_commit_rows_returns_204_not_500(
        self, client, db_session, commit_project, git_repo
    ):
        """Every FK to `projects` in this schema is NO ACTION, so a child table
        left out of `delete_project` does not fail at the model - it 500s the
        delete endpoint the moment a row exists.

        The DWB-624 enumeration guard caught the missing handler by reading the
        mapper registry, but that guard matches the class NAME in the function
        source: it would pass against a line that mentions `Commit` and deletes
        nothing. This is the behavioural half, and the row-count assertion
        after the delete is what makes it one.
        """
        repo, commit = git_repo
        sha = commit("CMT-11 before delete", files={"k.py": "n = 11\n"})

        from app.models.project import Project
        pid = commit_project["id"]
        project = db_session.get(Project, pid)
        commit_record.record_commit(
            db_session, project=project, repo_path=str(repo),
            commit_sha=sha, commit_message="CMT-11 before delete",
        )
        db_session.flush()

        # POSITIVE CONTROL: the row must exist, or the delete below proves
        # nothing - clearing an empty table always "works".
        assert db_session.execute(
            select(Commit).where(Commit.project_id == pid)
        ).scalars().all(), "no commit row to delete, so this test is vacuous"

        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 204, r.text

        assert db_session.execute(
            select(Commit).where(Commit.project_id == pid)
        ).scalars().all() == []
