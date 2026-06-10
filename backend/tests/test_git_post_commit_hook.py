# Path: tests/test_git_post_commit_hook.py
# File: test_git_post_commit_hook.py
# Created: 2026-06-10
# Purpose: Tests for POST /api/hooks/post-commit auto-close behavior (DWB-345)
# Caller: pytest
# Callees: app/routers/hooks.py, app/services/git_hook.py
# Data In: Factory-created projects, tickets via conftest
# Data Out: Assertions on closed/skipped/unknown response shape + DB state
# Last Modified: 2026-06-10

"""DWB-345: POST /api/hooks/post-commit parses commit messages for
<PROJECT_PREFIX>-NNN tokens, auto-closes any matching ticket whose status
is in {in_progress, in_review} (skips backlog/todo/done), idempotent on
re-fire, silent no-op when repo_path doesn't match a known project."""

import tempfile


def _make_project_with_repo(client, prefix: str) -> dict:
    """Create a project with a temp dir as its repo_path (so the hook can
    resolve it). Returns the project dict + the tmpdir context manager
    handle the caller must keep alive."""
    tmp = tempfile.TemporaryDirectory()
    project = client.post(
        "/api/projects",
        json={
            "prefix": prefix,
            "name": f"{prefix} Project",
            "repo_path": tmp.name,
        },
    ).json()
    project["_tmp"] = tmp  # keep alive
    return project


def _move_ticket_to(client, ticket_id: int, status: str):
    """Helper: PATCH a ticket through to a target status, skipping the
    forbidden todo->done auto-close path for tests that need an
    in_progress / in_review starting state."""
    r = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"status": status},
    )
    assert r.status_code == 200, r.text


class TestPostCommitHookHappyPath:
    def test_in_progress_ticket_closes(self, client, make_ticket):
        project = _make_project_with_repo(client, "PC1")
        ticket = make_ticket(
            project_id=project["id"],
            ticket_key="PC1-101",
        )
        _move_ticket_to(client, ticket["id"], "in_progress")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "fix: things (PC1-101)",
            "commit_sha": "abc123def",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == project["id"]
        assert body["project_prefix"] == "PC1"
        assert body["commit_sha"] == "abc123def"
        assert len(body["closed"]) == 1
        assert body["closed"][0]["ticket_key"] == "PC1-101"
        assert body["closed"][0]["prior_status"] == "in_progress"
        assert body["skipped"] == []
        assert body["unknown"] == []

        # DB-side: the ticket is actually done now.
        assert client.get(
            f"/api/tickets/{ticket['id']}"
        ).json()["status"] == "done"

    def test_in_review_ticket_closes(self, client, make_ticket):
        project = _make_project_with_repo(client, "PC2")
        ticket = make_ticket(project_id=project["id"], ticket_key="PC2-7")
        _move_ticket_to(client, ticket["id"], "in_progress")
        _move_ticket_to(client, ticket["id"], "in_review")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "merge PC2-7: done",
            "commit_sha": "sha2",
        })
        body = r.json()
        assert len(body["closed"]) == 1
        assert body["closed"][0]["prior_status"] == "in_review"

    def test_multiple_keys_in_one_message(self, client, make_ticket):
        project = _make_project_with_repo(client, "PC3")
        t1 = make_ticket(project_id=project["id"], ticket_key="PC3-1")
        t2 = make_ticket(project_id=project["id"], ticket_key="PC3-2")
        _move_ticket_to(client, t1["id"], "in_progress")
        _move_ticket_to(client, t2["id"], "in_progress")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "batch: PC3-1, PC3-2 - cleanup",
            "commit_sha": "sha-multi",
        })
        body = r.json()
        keys = sorted(c["ticket_key"] for c in body["closed"])
        assert keys == ["PC3-1", "PC3-2"]


class TestPostCommitHookGates:
    def test_backlog_ticket_skipped(self, client, make_ticket):
        project = _make_project_with_repo(client, "PCB")
        ticket = make_ticket(project_id=project["id"], ticket_key="PCB-9")
        # Default ticket status is backlog - no transition needed.

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "PCB-9: refactor",
            "commit_sha": "sha-b",
        })
        body = r.json()
        assert body["closed"] == []
        assert len(body["skipped"]) == 1
        assert body["skipped"][0]["status"] == "backlog"
        assert body["skipped"][0]["reason"] == "not_in_autoclose_set"
        # DB state unchanged.
        assert client.get(
            f"/api/tickets/{ticket['id']}"
        ).json()["status"] == "backlog"

    def test_already_done_ticket_skipped_idempotent(
        self, client, make_ticket
    ):
        project = _make_project_with_repo(client, "PCD")
        ticket = make_ticket(project_id=project["id"], ticket_key="PCD-1")
        _move_ticket_to(client, ticket["id"], "in_progress")
        _move_ticket_to(client, ticket["id"], "done")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "(PCD-1) followup",
            "commit_sha": "sha-d",
        })
        body = r.json()
        assert body["closed"] == []
        assert body["skipped"][0]["reason"] == "already_done"

    def test_re_firing_same_commit_is_idempotent(
        self, client, make_ticket
    ):
        project = _make_project_with_repo(client, "PCI")
        ticket = make_ticket(project_id=project["id"], ticket_key="PCI-5")
        _move_ticket_to(client, ticket["id"], "in_progress")

        # First fire: closes.
        body1 = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "PCI-5",
            "commit_sha": "x",
        }).json()
        assert len(body1["closed"]) == 1

        # Second fire on same commit: all skipped, no exceptions.
        body2 = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "PCI-5",
            "commit_sha": "x",
        }).json()
        assert body2["closed"] == []
        assert body2["skipped"][0]["reason"] == "already_done"


class TestPostCommitHookParsing:
    def test_no_keys_in_message_returns_no_op(self, client, make_ticket):
        project = _make_project_with_repo(client, "PCN")
        # Ticket exists but message references nothing.
        make_ticket(project_id=project["id"], ticket_key="PCN-1")
        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "fix: nothing special",
            "commit_sha": "sha-n",
        })
        body = r.json()
        assert body["closed"] == body["skipped"] == body["unknown"] == []
        assert body["reason"] == "no_ticket_keys_in_message"

    def test_unknown_ticket_key_lands_in_unknown(self, client):
        project = _make_project_with_repo(client, "PCU")
        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "PCU-999: never created",
            "commit_sha": "sha-u",
        })
        body = r.json()
        assert body["closed"] == body["skipped"] == []
        assert body["unknown"] == ["PCU-999"]

    def test_other_project_prefix_ignored(self, client, make_ticket):
        """A commit message that mentions OTHER-1 must not close
        OTHER-1 when the commit lands in a project whose prefix is PCO.
        Prefix scoping prevents cross-project surprise."""
        other = _make_project_with_repo(client, "PCO")
        # Create a ticket on a different project with prefix OTHER.
        other_repo = _make_project_with_repo(client, "OTHRA")
        other_ticket = make_ticket(
            project_id=other_repo["id"], ticket_key="OTHRA-1"
        )
        _move_ticket_to(client, other_ticket["id"], "in_progress")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": other["repo_path"],
            "commit_message": "OTHRA-1 should NOT be touched from PCO commit",
            "commit_sha": "sha-x",
        })
        body = r.json()
        # No PCO-NNN tokens in the message → no-op.
        assert body["closed"] == []
        assert body["unknown"] == []
        # OTHRA-1 status untouched.
        assert client.get(
            f"/api/tickets/{other_ticket['id']}"
        ).json()["status"] == "in_progress"

    def test_dedupes_repeated_key_in_message(self, client, make_ticket):
        project = _make_project_with_repo(client, "PCDDUP")
        ticket = make_ticket(
            project_id=project["id"], ticket_key="PCDDUP-1"
        )
        _move_ticket_to(client, ticket["id"], "in_progress")

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": project["repo_path"],
            "commit_message": "PCDDUP-1 first mention\n\nRefs: PCDDUP-1 again",
            "commit_sha": "sha-dup",
        })
        body = r.json()
        assert len(body["closed"]) == 1


class TestPostCommitHookRepoPath:
    def test_unknown_repo_path_silent_noop(self, client):
        r = client.post("/api/hooks/post-commit", json={
            "repo_path": "/nowhere/that/exists",
            "commit_message": "PC-1: hello",
            "commit_sha": "sha-z",
        })
        # 200, well-formed, project_id null.
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] is None
        assert body["reason"] == "no_project_for_repo_path"
        assert body["closed"] == []


class TestPostCommitHookNeverErrors:
    def test_malformed_body_returns_422_not_5xx(self, client):
        """Pydantic validation 422 is fine - the shell hook ignores any
        non-2xx response with `|| true`. The contract is just 'no 5xx'."""
        r = client.post("/api/hooks/post-commit", json={"missing": "fields"})
        assert r.status_code == 422
