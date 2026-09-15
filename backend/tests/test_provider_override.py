# Path: tests/test_provider_override.py
# File: test_provider_override.py
# Created: 2026-09-14
# Purpose: Verify the DWB-525/526 provider overrides plug into node_touch.nodeify
#          (DWB-527) and REPLACE the light defaults: a full pass grounds code
#          pointers as file-path + line refs (not ref=sha) and doc pointers with
#          line refs. Explicitly registers the providers (independent of import
#          side-effects) and restores the registry afterwards.
# Caller: pytest
# Callees: app/services/node_touch.nodeify_project, code_pointers, doc_pointers
# Data In: fixture git repo + docs under tmp_path
# Data Out: assertions on grounded NodePointer shape
# Last Modified: 2026-09-14

import subprocess

import pytest

from app.models.node import NodePointer, NodePointerKind
from app.services import code_pointers, doc_pointers, node_touch


@pytest.fixture
def _providers_registered():
    """Register my rich providers for the pass, then restore the registry."""
    saved = dict(node_touch._PROVIDER_OVERRIDES)
    node_touch.register_source_provider("code", code_pointers.code_provider)
    node_touch.register_source_provider("doc", doc_pointers.doc_provider)
    yield
    node_touch._PROVIDER_OVERRIDES.clear()
    node_touch._PROVIDER_OVERRIDES.update(saved)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def test_nodeify_code_pointer_is_file_and_line(
    client, db_session, make_project, tmp_path, _providers_registered
):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")

    project = make_project(repo_path=str(repo))
    prefix = project["prefix"]

    # A doc mentions widget (doc domain) and a ticket-referencing commit touches a
    # file containing widget (code domain) -> widget grounds across 2 domains.
    (repo / "README.md").write_text("the widget subsystem\n")
    (repo / "widget.py").write_text("def widget():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{prefix}-1 implement widget")

    r = client.post(f"/api/projects/{project['id']}/nodeify")
    assert r.status_code == 200, r.text

    code_ptrs = (
        db_session.query(NodePointer)
        .filter_by(project_id=project["id"], tag="widget", kind=NodePointerKind.code)
        .all()
    )
    assert code_ptrs, "widget should ground in the code domain"
    # The override grounds every touched file (widget.py AND README.md were both in
    # the commit), each ref=FILE PATH with a line ref - not the light default's
    # single ref==sha, line_start==None pointer. Check the widget.py grounding.
    refs = {p.ref for p in code_ptrs}
    assert "widget.py" in refs
    ptr = next(p for p in code_ptrs if p.ref == "widget.py")
    assert ptr.sha is not None and ptr.sha != ptr.ref  # sha stamped, ref is the path
    assert ptr.line_start is not None                   # concrete line ref
    # None of the code refs is the raw commit sha (the light-default signature).
    assert not any(len(r) == 40 and r == p.sha for r in refs for p in code_ptrs if p.ref == r)

    # Doc pointer for widget carries a line ref too (per-line override).
    doc_ptr = (
        db_session.query(NodePointer)
        .filter_by(project_id=project["id"], tag="widget", kind=NodePointerKind.doc)
        .first()
    )
    assert doc_ptr is not None
    assert doc_ptr.ref == "README.md"
    assert doc_ptr.line_start == 1
