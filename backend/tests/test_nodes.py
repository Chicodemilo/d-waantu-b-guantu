# Path: tests/test_nodes.py
# File: test_nodes.py
# Created: 2026-09-14 (DWB-523)
# Purpose: Tests for the node read API - GET /nodes (weight-ordered list + kind
#          filter) and GET /nodes/match (query normalization, pointers, derived
#          neighbors). Seeds a corpus through the registration service, then
#          asserts over the frozen response shape retrieval + the graph view read.
# Caller: pytest
# Callees: app/routers/nodes, app/services/node_registry
# Data In: pytest fixtures (client, db_session, make_project)
# Data Out: assertions
# Last Modified: 2026-09-14 (DWB-523)

import pytest

from app.services.node_registry import SourceUnit, register_sources


@pytest.fixture
def seeded_project(db_session, make_project):
    """A project with a small grounded corpus.

    - 'tokenizer' grounds in code+memory, and shares ref 'app/x.py' with 'pipeline'
      (so they are neighbors).
    - 'pipeline' grounds in code+doc.
    - 'lonely' appears in one domain only -> never a node.
    """
    p = make_project()
    register_sources(
        db_session,
        p["id"],
        [
            SourceUnit(kind="code", ref="app/x.py", text="tokenizer pipeline",
                       sha="abc", line_start=1, line_end=9),
            SourceUnit(kind="memory", ref="mem-1", text="tokenizer lonely"),
            SourceUnit(kind="doc", ref="README.md", text="pipeline"),
        ],
    )
    db_session.flush()
    return p


class TestListNodes:
    def test_lists_weight_ordered(self, client, seeded_project):
        r = client.get(f"/api/projects/{seeded_project['id']}/nodes")
        assert r.status_code == 200
        data = r.json()
        tags = [n["tag"] for n in data]
        assert "tokenizer" in tags
        assert "pipeline" in tags
        assert "lonely" not in tags  # single-domain, never grounded
        # weight desc ordering
        weights = [n["weight"] for n in data]
        assert weights == sorted(weights, reverse=True)

    def test_pointers_included(self, client, seeded_project):
        r = client.get(f"/api/projects/{seeded_project['id']}/nodes")
        node = next(n for n in r.json() if n["tag"] == "tokenizer")
        kinds = {p["kind"] for p in node["pointers"]}
        assert kinds == {"code", "memory"}
        code_ptr = next(p for p in node["pointers"] if p["kind"] == "code")
        assert code_ptr["sha"] == "abc"
        assert code_ptr["line_start"] == 1
        assert code_ptr["line_end"] == 9

    def test_kind_filter(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes", params={"kind": "doc"}
        )
        assert r.status_code == 200
        tags = {n["tag"] for n in r.json()}
        # only 'pipeline' has a doc pointer
        assert tags == {"pipeline"}

    def test_invalid_kind_422(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes", params={"kind": "bogus"}
        )
        assert r.status_code == 422

    def test_unknown_project_404(self, client):
        r = client.get("/api/projects/999999/nodes")
        assert r.status_code == 404


class TestMatchNodes:
    def test_match_returns_query_tags(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes/match",
            params={"text": "the Tokenizers"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["query"] == "the Tokenizers"
        # normalized + stemmed, stopword dropped
        assert data["query_tags"] == ["tokenizer"]

    def test_match_includes_pointers_and_neighbors(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes/match",
            params={"text": "tokenizer"},
        )
        data = r.json()
        assert len(data["nodes"]) == 1
        node = data["nodes"][0]
        assert node["tag"] == "tokenizer"
        assert {p["kind"] for p in node["pointers"]} == {"code", "memory"}
        # tokenizer + pipeline share ref app/x.py -> pipeline is a neighbor
        neighbor_tags = {nb["tag"] for nb in node["neighbors"]}
        assert "pipeline" in neighbor_tags
        pipeline_nb = next(
            nb for nb in node["neighbors"] if nb["tag"] == "pipeline"
        )
        assert pipeline_nb["shared_refs"] == ["app/x.py"]

    def test_no_match_returns_empty_nodes(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes/match",
            params={"text": "nonexistentterm"},
        )
        assert r.status_code == 200
        assert r.json()["nodes"] == []

    def test_stopword_only_query_empty(self, client, seeded_project):
        r = client.get(
            f"/api/projects/{seeded_project['id']}/nodes/match",
            params={"text": "the and of"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["query_tags"] == []
        assert data["nodes"] == []

    def test_unknown_project_404(self, client):
        r = client.get(
            "/api/projects/999999/nodes/match", params={"text": "x"}
        )
        assert r.status_code == 404
