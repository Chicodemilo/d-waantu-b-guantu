# Path: tests/test_header_gate.py
# File: test_header_gate.py
# Created: 2026-06-19
# Purpose: Tests for the force_headers code-header gate (DWB-403) at sprint close + gate-status.
# Caller: pytest
# Callees: POST/PATCH /api/projects, POST /api/epics, POST/PATCH /api/sprints, GET /api/projects/{id}/gate-status
# Data In: git repo seeded under tmp_path, factory-created project/epic/sprint
# Data Out: assertions on gate-blocked 400s, clean 200 closes, and gate-status shape
# Last Modified: 2026-06-19

"""force_headers gate (DWB-403).

Opt-in per project (default OFF). When ON, sprint close is blocked if any .py
file touched during the sprint is missing the mandatory code-header block.
Scope is sprint-touched/new files only (via git), never repo-wide legacy.
"""

import os
import subprocess

HEADERED = (
    "# Path: app/sample.py\n"
    "# File: sample.py\n"
    "# Purpose: sample module with a proper header\n"
    "# Last Modified: 2026-06-19\n\n"
    "def f():\n    return 1\n"
)
UNHEADERED = "def f():\n    return 1\n"

# Gate flags to disable so close is only ever blocked by force_headers.
_OTHER_GATES_OFF = {
    "force_initial_md": False,
    "force_architecture_md": False,
    "force_handoff_md": False,
    "force_test_run": False,
    "force_test_coverage": False,
    "force_consolidation": False,
}


def _git(repo, *args, env=None):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
        env={**os.environ, **env} if env else None,
    )


def _init_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Tester")


def _commit(tmp_path, msg, date=None):
    _git(tmp_path, "add", "-A")
    env = None
    if date:
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    _git(tmp_path, "commit", "-m", msg, env=env)


def _project(client, tmp_path, prefix, *, force_headers):
    return client.post("/api/projects", json={
        "prefix": prefix, "name": f"Project {prefix}", "repo_path": str(tmp_path),
        "force_headers": force_headers, **_OTHER_GATES_OFF,
    }).json()


def _active_sprint(client, make_epic, project, start_date="2020-01-01"):
    epic = make_epic(project_id=project["id"])
    return client.post("/api/sprints", json={
        "project_id": project["id"], "epic_id": epic["id"],
        "sprint_number": 1, "status": "active", "start_date": start_date,
    }).json()


def _close(client, sprint_id):
    return client.patch(f"/api/sprints/{sprint_id}", json={"status": "completed"})


class TestHeaderGate:
    def test_off_allows_close_with_unheadered_file(self, client, tmp_path, make_epic):
        _init_repo(tmp_path)
        (tmp_path / "bad.py").write_text(UNHEADERED, encoding="utf-8")
        _commit(tmp_path, "add unheadered file")
        project = _project(client, tmp_path, "HG1", force_headers=False)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_on_blocks_unheadered_touched_file(self, client, tmp_path, make_epic):
        _init_repo(tmp_path)
        (tmp_path / "bad.py").write_text(UNHEADERED, encoding="utf-8")
        _commit(tmp_path, "add unheadered file")
        project = _project(client, tmp_path, "HG2", force_headers=True)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "force_headers" in detail
        assert "bad.py" in detail

    def test_on_passes_with_headered_file(self, client, tmp_path, make_epic):
        _init_repo(tmp_path)
        (tmp_path / "good.py").write_text(HEADERED, encoding="utf-8")
        _commit(tmp_path, "add headered file")
        project = _project(client, tmp_path, "HG3", force_headers=True)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_on_blocks_untracked_inflight_file(self, client, tmp_path, make_epic):
        """In-flight (uncommitted, untracked) work is in scope, not just commits."""
        _init_repo(tmp_path)
        (tmp_path / "seed.py").write_text(HEADERED, encoding="utf-8")
        _commit(tmp_path, "seed")
        # New untracked file, never committed:
        (tmp_path / "wip.py").write_text(UNHEADERED, encoding="utf-8")
        project = _project(client, tmp_path, "HG4", force_headers=True)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 400, r.text
        assert "wip.py" in r.json()["detail"]

    def test_legacy_file_before_sprint_not_scanned(self, client, tmp_path, make_epic):
        """The crux of sprint-touched scoping: an unheadered file committed
        BEFORE the sprint start is NOT scanned. Only files touched in-window
        block the close."""
        _init_repo(tmp_path)
        (tmp_path / "legacy.py").write_text(UNHEADERED, encoding="utf-8")
        _commit(tmp_path, "legacy", date="2019-01-01T00:00:00")
        project = _project(client, tmp_path, "HG5", force_headers=True)
        # Sprint starts well after the legacy commit; nothing touched since.
        sprint = _active_sprint(client, make_epic, project, start_date="2020-06-01")

        r = _close(client, sprint["id"])
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_empty_py_file_exempt(self, client, tmp_path, make_epic):
        """Empty files (e.g. __init__.py) carry no code and need no header."""
        _init_repo(tmp_path)
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        _commit(tmp_path, "empty init")
        project = _project(client, tmp_path, "HG6", force_headers=True)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 200, r.text

    def test_non_git_repo_passes(self, client, tmp_path, make_epic):
        """A non-git repo_path yields no scan list; the gate degrades to pass
        rather than blocking a close on tooling."""
        (tmp_path / "bad.py").write_text(UNHEADERED, encoding="utf-8")
        project = _project(client, tmp_path, "HG7", force_headers=True)
        sprint = _active_sprint(client, make_epic, project)

        r = _close(client, sprint["id"])
        assert r.status_code == 200, r.text


class TestHeaderGateStatus:
    def test_gate_status_surfaces_force_headers_off(self, client, tmp_path, make_epic):
        _init_repo(tmp_path)
        (tmp_path / "bad.py").write_text(UNHEADERED, encoding="utf-8")
        _commit(tmp_path, "add unheadered file")
        project = _project(client, tmp_path, "HG8", force_headers=False)

        data = client.get(f"/api/projects/{project['id']}/gate-status").json()
        header_gates = [g for g in data["gates"] if g.get("toggle") == "force_headers"]
        assert len(header_gates) == 1
        hg = header_gates[0]
        assert hg["enabled"] is False
        assert hg["passing"] is True
        assert hg["missing_files"] == []

    def test_gate_status_lists_missing_when_on(self, client, tmp_path, make_epic):
        _init_repo(tmp_path)
        (tmp_path / "bad.py").write_text(UNHEADERED, encoding="utf-8")
        _commit(tmp_path, "add unheadered file")
        project = _project(client, tmp_path, "HG9", force_headers=True)
        _active_sprint(client, make_epic, project)

        data = client.get(f"/api/projects/{project['id']}/gate-status").json()
        hg = [g for g in data["gates"] if g.get("toggle") == "force_headers"][0]
        assert hg["enabled"] is True
        assert hg["passing"] is False
        assert "bad.py" in hg["missing_files"]
        assert data["all_passing"] is False
