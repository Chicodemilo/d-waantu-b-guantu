# Path: tests/test_pointer_wiring.py
# File: test_pointer_wiring.py
# Created: 2026-09-14
# Purpose: Integration tests for the pointer-grounding EVENT wiring (DWB-525/526):
#          POST /api/hooks/post-commit re-grounds code pointers for a commit's
#          touched files, and deploy_bundle re-grounds doc pointers for the repo's
#          doc corpus. Each seeds a live 2-domain node (refs outside the event's
#          scope) so the grounded tag persists under the 2-domain rule.
# Caller: pytest
# Callees: app/routers/hooks.py, app/services/playbook_deploy.deploy_bundle
# Data In: fixture git repo / doc tree under tmp_path
# Data Out: assertions on persisted NodePointer rows
# Last Modified: 2026-09-14

import subprocess

from app.models.node import NodePointer, NodePointerKind
from app.models.project import Project
from app.services import node_registry as nr


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _init_repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@e.com")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "commit.gpgsign", "false")
    return r


def _head(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _seed_two_domain(db, pid):
    """Seed a live 'widgetize' node grounded in doc+code, on refs the events below
    do not touch, so a single new pointer keeps it above the 2-domain threshold."""
    nr.register_sources(db, pid, [
        nr.SourceUnit(kind="doc", ref="seed.md", text="widgetize doc", line_start=1, line_end=1),
        nr.SourceUnit(kind="code", ref="seed.py", text="widgetize()", sha="s0", line_start=1, line_end=1),
    ])
    db.flush()


class TestPostCommitCodeWiring:
    def test_post_commit_grounds_code_pointer(self, client, db_session, make_project, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "widget.py").write_text("widgetize the thing\n")
        _git(repo, "add", "widget.py")
        _git(repo, "commit", "-q", "-m", "feat: DWB-1 add widgetize")
        sha = _head(repo)

        project = make_project(repo_path=str(repo))
        _seed_two_domain(db_session, project["id"])

        r = client.post("/api/hooks/post-commit", json={
            "repo_path": str(repo),
            "commit_message": "feat: DWB-1 add widgetize",
            "commit_sha": sha,
        })
        assert r.status_code == 200

        ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=project["id"], tag="widgetize",
                       kind=NodePointerKind.code, ref="widget.py")
            .one()
        )
        assert ptr.sha == sha
        assert ptr.line_start == 1

    def test_post_commit_unknown_repo_no_error(self, client, tmp_path):
        # repo_path that matches no project: hook still 200s, no grounding.
        r = client.post("/api/hooks/post-commit", json={
            "repo_path": str(tmp_path / "nope"),
            "commit_message": "feat: X-1",
            "commit_sha": "deadbeef",
        })
        assert r.status_code == 200
        assert r.json()["project_id"] is None


class TestDeployDocWiring:
    def test_deploy_grounds_doc_pointer(self, db_session, make_project, tmp_path):
        from app.services.playbook_deploy import deploy_bundle

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("intro line\nwidgetize documented here\n")

        project = make_project(repo_path=str(repo))
        _seed_two_domain(db_session, project["id"])

        project_row = db_session.get(Project, project["id"])
        deploy_bundle(db_session, project_row)  # commits internally + grounds docs

        ptr = (
            db_session.query(NodePointer)
            .filter_by(project_id=project["id"], tag="widgetize",
                       kind=NodePointerKind.doc, ref="README.md")
            .one()
        )
        assert ptr.line_start == 2   # README line 2
        assert ptr.sha is None       # docs carry no sha
