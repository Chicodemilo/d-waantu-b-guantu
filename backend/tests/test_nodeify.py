# Path: tests/test_nodeify.py
# File: test_nodeify.py
# Created: 2026-09-14 (DWB-527)
# Purpose: Tests for the nodeify full pass + the memory touch-update seam -
#          bootstrap grounding across memory+doc+git, idempotent re-run, prune of
#          vanished sources, content refresh, and event-driven memory re-grounding.
# Caller: pytest
# Callees: app/services/node_touch, app/services/agent (memory append wiring)
# Data In: pytest fixtures (client, db_session, make_project, make_agent, tmp_path)
# Data Out: assertions
# Last Modified: 2026-09-15 (DWB-538: 10-doc two-domain small-corpus pass)

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.node import Node, NodePointer


@pytest.fixture(autouse=True)
def _clean_source_providers():
    """Isolate nodeify's provider registry. Other lanes (DWB-525/526) register
    their code/doc providers as an import-time side-effect, which would otherwise
    override the LIGHT defaults these tests assert on. Snapshot, clear, restore."""
    from app.services import node_touch
    saved = dict(node_touch._PROVIDER_OVERRIDES)
    node_touch._PROVIDER_OVERRIDES.clear()
    yield
    node_touch._PROVIDER_OVERRIDES.clear()
    node_touch._PROVIDER_OVERRIDES.update(saved)


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mem_file(repo: Path, prefix: str, agent_name: str) -> Path:
    return repo / ".dwb" / "memory" / prefix / agent_name / "memory.md"


def _tags(db, project_id):
    return {
        n.tag
        for n in db.execute(
            select(Node).where(Node.project_id == project_id)
        ).scalars().all()
    }


def _ptr_count(db, project_id):
    return len(
        db.execute(
            select(NodePointer).where(NodePointer.project_id == project_id)
        ).scalars().all()
    )


class TestNodeifyFullPass:
    def test_bootstrap_grounds_across_memory_and_doc(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        _write(tmp_path / "README.md", "the widget pipeline handles tokenizer flow")
        _write(
            _mem_file(tmp_path, p["prefix"], "AgentOne"),
            "widget pipeline design notes",
        )

        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == p["id"]
        assert body["nodeified_at"]
        assert body["source_counts"]["memory"] == 1
        assert body["source_counts"]["doc"] == 1

        tags = _tags(db_session, p["id"])
        # widget + pipeline are in BOTH doc and memory -> grounded
        assert "widget" in tags
        assert "pipeline" in tags
        # tokenizer/flow are doc-only, notes/design memory-only -> not grounded
        assert "tokenizer" not in tags
        assert "flow" not in tags

    def test_nodeified_at_stamped(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        _write(tmp_path / "README.md", "alpha beta")
        _write(_mem_file(tmp_path, p["prefix"], "AgentOne"), "alpha beta")
        client.post(f"/api/projects/{p['id']}/nodeify")
        proj = client.get(f"/api/projects/{p['id']}").json()
        assert proj["nodeified_at"] is not None

    def test_idempotent_rerun(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        _write(tmp_path / "README.md", "widget pipeline")
        _write(_mem_file(tmp_path, p["prefix"], "AgentOne"), "widget pipeline")

        client.post(f"/api/projects/{p['id']}/nodeify")
        tags1 = _tags(db_session, p["id"])
        ptrs1 = _ptr_count(db_session, p["id"])

        client.post(f"/api/projects/{p['id']}/nodeify")
        assert _tags(db_session, p["id"]) == tags1
        assert _ptr_count(db_session, p["id"]) == ptrs1

    def test_prune_when_source_vanishes(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        readme = tmp_path / "README.md"
        _write(readme, "widget pipeline")
        _write(_mem_file(tmp_path, p["prefix"], "AgentOne"), "widget pipeline")
        client.post(f"/api/projects/{p['id']}/nodeify")
        assert "widget" in _tags(db_session, p["id"])

        # Doc vanishes -> widget/pipeline drop to memory-only -> pruned.
        readme.unlink()
        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 200
        assert "widget" not in _tags(db_session, p["id"])
        assert _ptr_count(db_session, p["id"]) == 0

    def test_content_refresh(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        _write(tmp_path / "README.md", "widget pipeline")
        mem = _mem_file(tmp_path, p["prefix"], "AgentOne")
        _write(mem, "widget pipeline")
        client.post(f"/api/projects/{p['id']}/nodeify")
        assert "widget" in _tags(db_session, p["id"])

        # Memory rewritten: widget removed, gadget added. README still has widget
        # (1 domain now) + no gadget. So after refresh: widget pruned, gadget not
        # grounded (memory-only) -> no nodes.
        _write(mem, "gadget pipeline")
        client.post(f"/api/projects/{p['id']}/nodeify")
        tags = _tags(db_session, p["id"])
        assert "widget" not in tags   # lost its memory grounding
        assert "pipeline" in tags     # still doc + memory
        assert "gadget" not in tags   # memory-only

    def test_git_commit_grounds_code_domain(
        self, client, db_session, make_project, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        # a doc mentions widget; a commit message also mentions widget -> 2 domains
        _write(tmp_path / "README.md", "widget subsystem")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "implement widget handler"],
            cwd=tmp_path, check=True,
        )

        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 200
        assert r.json()["source_counts"]["code"] >= 1
        # widget grounded via doc + code; the code pointer carries the commit sha.
        widget_ptrs = db_session.execute(
            select(NodePointer).where(
                NodePointer.project_id == p["id"], NodePointer.tag == "widget"
            )
        ).scalars().all()
        kinds = {pt.kind.value for pt in widget_ptrs}
        assert "code" in kinds and "doc" in kinds
        code_ptr = next(pt for pt in widget_ptrs if pt.kind.value == "code")
        assert code_ptr.sha == code_ptr.ref  # ref == commit sha
        assert len(code_ptr.sha) == 40

    def test_repo_path_missing_400(self, client, make_project):
        p = make_project()  # no repo_path
        r = client.post(f"/api/projects/{p['id']}/nodeify")
        assert r.status_code == 400

    def test_unknown_project_404(self, client):
        r = client.post("/api/projects/999999/nodeify")
        assert r.status_code == 404


class TestSmallCorpusSuppression:
    """DWB-538: a nodeify pass over a 10-doc two-domain corpus must ground the
    shared tags. Before the GENERIC_MIN_DF floor the 0.12 ratio gave a threshold
    of 1.2 at 10 docs, so every grounded (df>=2) tag was suppressed and the
    cloud came back empty."""

    def test_ten_doc_two_domain_pass_grounds_shared_tags(
        self, client, db_session, make_project, tmp_path
    ):
        repo = tmp_path
        project = make_project(repo_path=str(repo))
        prefix = project["prefix"]
        rocks = ["quartz", "basalt", "granite", "marble", "slate"]
        # 5 memory docs + 5 doc docs = 10 distinct (kind, ref) documents. Each
        # rock sits in one memory + one doc (df=2); "common" is in all 10.
        for i, rock in enumerate(rocks):
            # Distinct headings per file: an identical ISO heading token in all
            # five memory docs would itself count as a (never-grounding) generic.
            _write(_mem_file(repo, prefix, f"Agent{i}"),
                   f"## 2026-09-15T00:0{i}:00+00:00\ncommon {rock}\n")
            name = "README.md" if i == 0 else f"docs/{rock}.md"
            _write(repo / name, f"common {rock}\n")

        r = client.post(f"/api/projects/{project['id']}/nodeify")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_counts"] == {"code": 0, "doc": 5, "memory": 5}
        assert body["grounded"] == 5
        assert body["suppressed"] == 1
        tags = _tags(db_session, project["id"])
        assert set(rocks) <= tags
        assert "common" not in tags


class TestMemoryTouchWiring:
    def test_memory_append_regrounds_tags(
        self, client, db_session, make_project, make_agent, tmp_path
    ):
        p = make_project(repo_path=str(tmp_path))
        agent = make_agent(project_id=p["id"], name="Toucher")
        # Pre-ground "widget" via doc + code so a memory mention lands a 3rd domain.
        _write(tmp_path / "README.md", "widget helper")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "widget wiring"], cwd=tmp_path, check=True)
        client.post(f"/api/projects/{p['id']}/nodeify")
        assert "widget" in _tags(db_session, p["id"])

        # Now the agent appends a memory note mentioning widget -> touch adds a
        # memory-domain pointer to the existing node.
        r = client.post(
            f"/api/agents/{agent['id']}/memory/append",
            json={"file": "memory", "content": "widget behaviour observed"},
            headers={"X-Agent-ID": str(agent["id"])},
        )
        assert r.status_code == 201, r.text

        widget_ptrs = db_session.execute(
            select(NodePointer).where(
                NodePointer.project_id == p["id"], NodePointer.tag == "widget"
            )
        ).scalars().all()
        kinds = {pt.kind.value for pt in widget_ptrs}
        assert "memory" in kinds

    def test_memory_append_touch_never_breaks_write(
        self, client, make_project, make_agent, tmp_path
    ):
        # A memory append on a project with no grounded neighbors must still
        # succeed (touch is best-effort; single-domain memory grounds nothing).
        p = make_project(repo_path=str(tmp_path))
        agent = make_agent(project_id=p["id"], name="Solo")
        r = client.post(
            f"/api/agents/{agent['id']}/memory/append",
            json={"file": "memory", "content": "lonely note"},
            headers={"X-Agent-ID": str(agent["id"])},
        )
        assert r.status_code == 201
