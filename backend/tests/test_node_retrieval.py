# Path: tests/test_node_retrieval.py
# File: test_node_retrieval.py
# Created: 2026-09-14
# Purpose: Tests for the retrieval-into-work lane (DWB-524): relevant_lessons on
#          spawn-prepare (memory-domain lessons matched to an agent's tickets, with
#          source agent + entry heading resolved from memory.md) and the ticket
#          related-nodes endpoint (lessons/sessions/code groups). Empty corpus
#          degrades to empty lists.
# Caller: pytest
# Callees: app/services/node_retrieval, app/services/agent, app/routers/tickets
# Data In: fixture project + nodes + a memory.md tree under tmp_path
# Data Out: assertions on lessons / related-node groups
# Last Modified: 2026-09-14

from app.models.agent import Agent
from app.models.project import Project
from app.services import node_registry as nr
from app.services import node_retrieval


def _seed_widget_node(db, pid, mem_ref):
    """Ground a 'widget' node in the memory (mem_ref) + code domains."""
    nr.register_sources(db, pid, [
        nr.SourceUnit(kind="memory", ref=mem_ref, text="widget pipeline lesson"),
        nr.SourceUnit(kind="code", ref="handler.py", text="widget()", sha="c0",
                      line_start=3, line_end=3),
    ])
    db.flush()


def _write_memory(repo_root, prefix, agent_name, body):
    p = repo_root / ".dwb" / "memory" / prefix / agent_name / "memory.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return f".dwb/memory/{prefix}/{agent_name}/memory.md"


class TestRelevantLessons:
    def test_matches_and_resolves_heading(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        pid = project["id"]
        prefix = project["prefix"]

        # Source agent Barry's memory.md carries the widget lesson under a heading.
        mem_ref = _write_memory(
            tmp_path, prefix, "Barry",
            "## 2026-09-14T10:00:00+00:00\nwidget pipeline notes here\n",
        )
        _seed_widget_node(db_session, pid, mem_ref)

        # Spawning agent Stan has an assigned ticket about widgets.
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        make_ticket(project_id=pid, title="widget subsystem work",
                    assigned_agent_id=stan["id"], status="in_progress")

        project_obj = db_session.get(Project, pid)
        agent_obj = db_session.get(Agent, stan["id"])
        lessons = node_retrieval.relevant_lessons(db_session, project_obj, agent_obj)

        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["tag"] == "widget"
        assert lesson["source_agent"] == "Barry"
        assert lesson["memory_ref"] == mem_ref
        assert lesson["entry_heading"] == "2026-09-14T10:00:00+00:00"
        assert lesson["date"] == "2026-09-14T10:00:00+00:00"

    def test_skips_own_memory(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        pid, prefix = project["id"], project["prefix"]
        # The lesson lives in STAN's own memory -> must be skipped (already injected).
        mem_ref = _write_memory(tmp_path, prefix, "Stan",
                                "## 2026-09-14T10:00:00+00:00\nwidget notes\n")
        _seed_widget_node(db_session, pid, mem_ref)
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        make_ticket(project_id=pid, title="widget work",
                    assigned_agent_id=stan["id"], status="todo")
        project_obj = db_session.get(Project, pid)
        agent_obj = db_session.get(Agent, stan["id"])
        assert node_retrieval.relevant_lessons(db_session, project_obj, agent_obj) == []

    def test_no_tickets_empty(self, db_session, make_project, make_agent, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        stan = make_agent(project_id=project["id"], name="Stan", role="backend-worker")
        project_obj = db_session.get(Project, project["id"])
        agent_obj = db_session.get(Agent, stan["id"])
        assert node_retrieval.relevant_lessons(db_session, project_obj, agent_obj) == []

    def test_empty_corpus_empty(self, db_session, make_project, make_agent, make_ticket, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        pid = project["id"]
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        make_ticket(project_id=pid, title="widget subsystem",
                    assigned_agent_id=stan["id"], status="in_progress")
        project_obj = db_session.get(Project, pid)
        agent_obj = db_session.get(Agent, stan["id"])
        # No nodes registered -> nothing to match.
        assert node_retrieval.relevant_lessons(db_session, project_obj, agent_obj) == []


class TestSpawnPrepareRelevantLessons:
    def test_spawn_prepare_includes_lessons(self, client, db_session, make_project, make_agent, make_ticket, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        pid, prefix = project["id"], project["prefix"]
        mem_ref = _write_memory(tmp_path, prefix, "Barry",
                                "## 2026-09-14T10:00:00+00:00\nwidget pipeline\n")
        _seed_widget_node(db_session, pid, mem_ref)
        stan = make_agent(project_id=pid, name="Stan", role="backend-worker")
        make_ticket(project_id=pid, title="widget subsystem",
                    assigned_agent_id=stan["id"], status="in_progress")
        db_session.commit()

        r = client.post("/api/agents/spawn-prepare",
                        json={"role": "backend-worker", "name": "Stan", "project_prefix": prefix})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "relevant_lessons" in body
        tags = [l["tag"] for l in body["relevant_lessons"]]
        assert "widget" in tags


class TestTicketRelatedNodes:
    def test_related_nodes_groups(self, client, db_session, make_project, make_ticket, tmp_path):
        project = make_project(repo_path=str(tmp_path))
        pid, prefix = project["id"], project["prefix"]
        mem_ref = _write_memory(tmp_path, prefix, "Barry",
                                "## 2026-09-14T10:00:00+00:00\nwidget lesson\n")
        _seed_widget_node(db_session, pid, mem_ref)
        ticket = make_ticket(project_id=pid, title="widget subsystem")
        db_session.commit()

        r = client.get(f"/api/tickets/{ticket['id']}/related-nodes")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "widget" in body["query_tags"]
        assert any(l["tag"] == "widget" for l in body["lessons"])
        assert any(c["tag"] == "widget" and c["kind"] == "code" for c in body["code"])
        assert body["lessons"][0]["source_agent"] == "Barry"

    def test_related_nodes_empty_corpus(self, client, make_ticket, make_project):
        project = make_project()
        ticket = make_ticket(project_id=project["id"], title="nothing to match here")
        r = client.get(f"/api/tickets/{ticket['id']}/related-nodes")
        assert r.status_code == 200
        body = r.json()
        assert body["lessons"] == [] and body["sessions"] == [] and body["code"] == []

    def test_related_nodes_unknown_ticket_404(self, client):
        assert client.get("/api/tickets/999999/related-nodes").status_code == 404
