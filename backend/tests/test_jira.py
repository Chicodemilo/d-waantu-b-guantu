# Path: tests/test_jira.py
# File: test_jira.py
# Created: 2026-05-27
# Purpose: Unit tests for /api/jira/* endpoints — service layer, caching, error paths
# Caller: pytest
# Callees: app.services.jira, app.routers.jira, app.config

"""Tests for the Jira proxy.

The Jira REST client is sync `requests`-based, so we monkeypatch
`app.services.jira._request` and `requests.request` directly rather than
spinning up a fake HTTP server.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import jira as svc


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_cache():
    svc.clear_cache()
    yield
    svc.clear_cache()


def _ensure_project_jira_linked(client, project_id: int) -> None:
    """DWB-332: the ticket router refuses jira_issue_key writes when the
    project's jira_base_url is null. The make_project factory leaves it null
    by default; link the project to a stub Jira URL here so the existing
    test bodies (which assume linking works) continue to pass without
    rewriting every test."""
    project = client.get(f"/api/projects/{project_id}").json()
    if not project.get("jira_base_url"):
        client.patch(
            f"/api/projects/{project_id}",
            json={
                "jira_base_url": "https://test.atlassian.net",
                "jira_project_key": "POR",
            },
        )


def _link_ticket(client, ticket_id: int, jira_key: str, status: str | None = None) -> dict:
    """Helper: PATCH a ticket to set jira_issue_key (+ optional status)."""
    ticket = client.get(f"/api/tickets/{ticket_id}").json()
    _ensure_project_jira_linked(client, ticket["project_id"])
    body: dict = {"jira_issue_key": jira_key}
    if status is not None:
        body["status"] = status
    r = client.patch(f"/api/tickets/{ticket_id}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def configured_jira(monkeypatch):
    """Pretend Jira is configured. Yields the settings so tests can tweak TTL."""
    monkeypatch.setattr(settings, "JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr(settings, "JIRA_EMAIL", "test@example.com")
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "JIRA_CACHE_TTL_SECONDS", 60)
    yield settings


def _mock_response(status_code: int, json_body: dict | list, text: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    r.text = text
    return r


# ── /config endpoint ──────────────────────────────────────────────


def test_config_endpoint_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "JIRA_BASE_URL", "")
    monkeypatch.setattr(settings, "JIRA_EMAIL", "")
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "")
    r = client.get("/api/jira/config")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["base_url"] is None


def test_config_endpoint_when_configured(client, configured_jira):
    r = client.get("/api/jira/config")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["base_url"] == "https://example.atlassian.net"


# ── 503 when Jira not configured ──────────────────────────────────


def test_endpoints_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "JIRA_BASE_URL", "")
    for path in (
        "/api/jira/projects",
        "/api/jira/issues/POR-1",
        "/api/jira/search?jql=project=POR",
        "/api/jira/projects/POR/sprints",
        "/api/jira/sprints/123/issues",
    ):
        r = client.get(path)
        assert r.status_code == 503, f"{path} should be 503 when unconfigured"


# ── Normalization ─────────────────────────────────────────────────


def test_normalize_issue_flattens_nested_fields():
    raw = {
        "key": "POR-1",
        "id": "10000",
        "fields": {
            "summary": "Test issue",
            "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "assignee": {"displayName": "Jane Doe"},
            "issuetype": {"name": "Task"},
            "parent": {"key": "POR-100", "fields": {"issuetype": {"name": "Epic"}}},
            "priority": {"name": "Medium"},
            "created": "2026-05-01T10:00:00.000+0000",
            "updated": "2026-05-26T15:00:00.000+0000",
        },
    }
    out = svc._normalize_issue(raw)
    # DWB-356 added reporter + sprint_name; DWB-363 added epic_key;
    # DWB-364 added issue_type_is_subtask. The parent here is an Epic so
    # epic_key resolves to "POR-100"; the issuetype dict omits the
    # `subtask` field so issue_type_is_subtask defaults to False.
    assert out == {
        "key": "POR-1",
        "id": "10000",
        "summary": "Test issue",
        "status": "In Progress",
        "status_category": "In Progress",
        "assignee": "Jane Doe",
        "reporter": None,
        "issue_type": "Task",
        "issue_type_is_subtask": False,
        "parent_key": "POR-100",
        "parent_type": "Epic",
        "priority": "Medium",
        "created": "2026-05-01T10:00:00.000+0000",
        "updated": "2026-05-26T15:00:00.000+0000",
        "sprint_name": None,
        "epic_key": "POR-100",
    }


def test_normalize_issue_handles_missing_optional_fields():
    raw = {"key": "POR-2", "id": "1", "fields": {"summary": "x"}}
    out = svc._normalize_issue(raw)
    assert out["assignee"] is None
    assert out["parent_key"] is None
    assert out["parent_type"] is None
    assert out["status"] is None
    assert out["priority"] is None


# ── Service layer (mocked requests) ────────────────────────────────


def test_get_issue_normalizes_response(configured_jira, monkeypatch):
    raw = {
        "key": "POR-1",
        "id": "10000",
        "fields": {
            "summary": "x",
            "status": {"name": "Done"},
            "issuetype": {"name": "Task"},
        },
    }
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, raw)),
    )
    out = svc.get_issue("POR-1")
    assert out["key"] == "POR-1"
    assert out["status"] == "Done"
    assert out["issue_type"] == "Task"


def test_list_projects_normalizes(configured_jira, monkeypatch):
    raw = {
        "values": [
            {"id": "1", "key": "POR", "name": "Portal", "extra": "ignored"},
            {"id": "2", "key": "CI",  "name": "Claims"},
        ]
    }
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, raw)),
    )
    out = svc.list_projects()
    assert out == [
        {"id": "1", "key": "POR", "name": "Portal"},
        {"id": "2", "key": "CI",  "name": "Claims"},
    ]


def test_search_issues_passes_jql(configured_jira, monkeypatch):
    mock = MagicMock(return_value=_mock_response(200, {"issues": []}))
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    svc.search_issues(jql='project = POR AND status = Done', limit=25)
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["params"]["jql"] == 'project = POR AND status = Done'
    assert call_kwargs["params"]["maxResults"] == 25


def test_get_active_sprints_no_board_returns_empty(configured_jira, monkeypatch):
    mock = MagicMock(return_value=_mock_response(200, {"values": []}))
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    assert svc.get_active_sprints("POR") == []
    # Only the boards call should happen — no sprint lookup if no boards.
    assert mock.call_count == 1


def test_get_active_sprints_normalizes(configured_jira, monkeypatch):
    boards = {"values": [{"id": 42, "name": "POR board"}]}
    sprints = {"values": [
        {"id": 7, "name": "Sprint X", "state": "active",
         "startDate": "2026-05-20", "endDate": "2026-05-27"},
    ]}
    mock = MagicMock(side_effect=[
        _mock_response(200, boards),
        _mock_response(200, sprints),
    ])
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    out = svc.get_active_sprints("POR")
    assert out == [{
        "id": 7, "name": "Sprint X", "state": "active",
        "start_date": "2026-05-20", "end_date": "2026-05-27",
    }]


# ── Cache behavior ────────────────────────────────────────────────


def test_cache_hits_skip_second_request(configured_jira, monkeypatch):
    mock = MagicMock(return_value=_mock_response(200, {"values": []}))
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    svc.list_projects()
    svc.list_projects()
    assert mock.call_count == 1  # second call served from cache


def test_cache_expires_after_ttl(configured_jira, monkeypatch):
    monkeypatch.setattr(settings, "JIRA_CACHE_TTL_SECONDS", 0)  # ⇒ effective TTL still > 0 via *5 multiplier on projects
    # Use raw _request with ttl=1 to control TTL deterministically
    mock = MagicMock(return_value=_mock_response(200, {"ok": 1}))
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    svc._request("GET", "/x", cache_ttl=1)
    svc._request("GET", "/x", cache_ttl=1)
    assert mock.call_count == 1
    # Fast-forward past the TTL by mutating the stored expiry.
    key = svc._cache_key("GET", "/x", None)
    with svc._cache_lock:
        expires_at, value = svc._cache[key]
        svc._cache[key] = (time.time() - 1, value)
    svc._request("GET", "/x", cache_ttl=1)
    assert mock.call_count == 2


def test_cache_separates_by_params(configured_jira, monkeypatch):
    mock = MagicMock(return_value=_mock_response(200, {"issues": []}))
    monkeypatch.setattr("app.services.jira.requests.request", mock)
    svc.search_issues("project = POR")
    svc.search_issues("project = CI")
    assert mock.call_count == 2  # different JQL ⇒ different cache key


# ── Error paths ───────────────────────────────────────────────────


def test_401_surfaces_as_401(configured_jira, monkeypatch):
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(401, {}, text="unauthorized")),
    )
    with pytest.raises(HTTPException) as exc_info:
        svc.get_issue("POR-1")
    assert exc_info.value.status_code == 401


def test_404_surfaces_as_404(configured_jira, monkeypatch):
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(404, {}, text="not found")),
    )
    with pytest.raises(HTTPException) as exc_info:
        svc.get_issue("POR-999")
    assert exc_info.value.status_code == 404


def test_network_failure_surfaces_as_502(configured_jira, monkeypatch):
    import requests as _requests
    def _boom(*a, **kw):
        raise _requests.ConnectionError("network down")
    monkeypatch.setattr("app.services.jira.requests.request", _boom)
    with pytest.raises(HTTPException) as exc_info:
        svc.get_issue("POR-1")
    assert exc_info.value.status_code == 502


# ── Router integration via TestClient ─────────────────────────────


def test_router_issue_endpoint(client, configured_jira, monkeypatch):
    raw = {"key": "POR-1", "id": "1", "fields": {"summary": "hi", "status": {"name": "Done"}}}
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, raw)),
    )
    r = client.get("/api/jira/issues/POR-1")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "POR-1"
    assert body["status"] == "Done"


def test_router_search_endpoint(client, configured_jira, monkeypatch):
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": []})),
    )
    r = client.get("/api/jira/search?jql=project=POR&limit=10")
    assert r.status_code == 200
    assert r.json() == []


def test_router_cache_clear(client):
    svc._cache[("GET", "/x", ())] = (time.time() + 60, {"ok": 1})
    r = client.post("/api/jira/cache/clear")
    assert r.status_code == 204
    assert svc._cache == {}


# ── Status mapping ───────────────────────────────────────────────


def test_jira_status_mapping_known_values():
    assert svc.jira_status_to_dwb("Done") == "done"
    assert svc.jira_status_to_dwb("Resolved") == "done"
    assert svc.jira_status_to_dwb("Won't Do") == "done"
    assert svc.jira_status_to_dwb("In Progress") == "in_progress"
    assert svc.jira_status_to_dwb("Ready for Testing/Review") == "in_review"
    assert svc.jira_status_to_dwb("To Do") == "todo"
    assert svc.jira_status_to_dwb("Open") == "todo"
    assert svc.jira_status_to_dwb("Backlog") == "backlog"


def test_jira_status_mapping_case_insensitive():
    assert svc.jira_status_to_dwb("DONE") == "done"
    assert svc.jira_status_to_dwb("in progress") == "in_progress"
    assert svc.jira_status_to_dwb("  Done  ") == "done"


def test_jira_status_mapping_unknown_returns_none():
    assert svc.jira_status_to_dwb("Brewing") is None
    assert svc.jira_status_to_dwb(None) is None
    assert svc.jira_status_to_dwb("") is None


# ── Sync: Jira → DWB ──────────────────────────────────────────────


def test_sync_no_linked_tickets(client, make_ticket, configured_jira, monkeypatch):
    # A bare ticket has no jira_issue_key → sync should be a no-op.
    make_ticket()
    r = client.post("/api/jira/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] == 0
    assert body["changed"] == 0


def test_sync_updates_dwb_status_when_jira_differs(client, make_ticket, configured_jira, monkeypatch):
    t = make_ticket()
    _link_ticket(client, t["id"], "POR-101", status="todo")
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": [
            {"key": "POR-101", "id": "1", "fields": {
                "summary": "x", "status": {"name": "Done"}, "issuetype": {"name": "Task"}}},
        ]})),
    )
    r = client.post("/api/jira/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] == 1
    assert body["changed"] == 1
    assert body["details"][0] == {
        "jira_key": "POR-101", "dwb_id": t["id"], "before": "todo", "after": "done",
    }
    # Verify the DWB ticket was actually updated.
    fresh = client.get(f"/api/tickets/{t['id']}").json()
    assert fresh["status"] == "done"


def test_sync_noop_when_statuses_already_match(client, make_ticket, configured_jira, monkeypatch):
    t = make_ticket()
    _link_ticket(client, t["id"], "POR-102", status="in_progress")
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": [
            {"key": "POR-102", "id": "1", "fields": {
                "summary": "x", "status": {"name": "In Progress"}, "issuetype": {"name": "Task"}}},
        ]})),
    )
    r = client.post("/api/jira/sync")
    body = r.json()
    assert body["synced"] == 1
    assert body["changed"] == 0


def test_sync_reports_unmapped_jira_status(client, make_ticket, configured_jira, monkeypatch):
    t = make_ticket()
    _link_ticket(client, t["id"], "POR-103", status="todo")
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": [
            {"key": "POR-103", "id": "1", "fields": {
                "summary": "x", "status": {"name": "Brewing"}, "issuetype": {"name": "Task"}}},
        ]})),
    )
    r = client.post("/api/jira/sync")
    body = r.json()
    assert body["changed"] == 0
    assert body["unmapped"] == [{"jira_key": "POR-103", "jira_status": "Brewing"}]


def test_sync_reports_missing_jira_issues(client, make_ticket, configured_jira, monkeypatch):
    t = make_ticket()
    _link_ticket(client, t["id"], "POR-MISSING", status="todo")
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": []})),  # empty result
    )
    r = client.post("/api/jira/sync")
    body = r.json()
    assert body["changed"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["jira_key"] == "POR-MISSING"


def test_sync_scoped_to_project(client, make_project, make_ticket, configured_jira, monkeypatch):
    p1 = make_project()
    p2 = make_project()
    t1 = make_ticket(project_id=p1["id"])
    t2 = make_ticket(project_id=p2["id"])
    _link_ticket(client, t1["id"], "POR-201", status="todo")
    _link_ticket(client, t2["id"], "POR-202", status="todo")

    def _fake_request(method, url, **kw):
        jql = kw.get("params", {}).get("jql", "")
        # Only return POR-201 — verifying the JQL was scoped.
        if "POR-201" in jql:
            return _mock_response(200, {"issues": [
                {"key": "POR-201", "id": "1", "fields": {
                    "summary": "x", "status": {"name": "Done"}, "issuetype": {"name": "Task"}}},
            ]})
        return _mock_response(200, {"issues": []})

    monkeypatch.setattr("app.services.jira.requests.request", _fake_request)
    r = client.post(f"/api/jira/sync?project_id={p1['id']}")
    body = r.json()
    assert body["synced"] == 1  # only the p1 ticket
    assert body["changed"] == 1
    assert body["details"][0]["dwb_id"] == t1["id"]


# ── Rollup ────────────────────────────────────────────────────────


def test_rollup_empty_when_no_linked_tickets(client, make_project, make_ticket, configured_jira):
    p = make_project()
    make_ticket(project_id=p["id"])  # unlinked
    r = client.get(f"/api/jira/rollup?project_id={p['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["epics"] == []


def test_rollup_groups_by_epic_and_counts(client, make_project, make_ticket, configured_jira, monkeypatch):
    p = make_project()
    a = make_ticket(project_id=p["id"])
    b = make_ticket(project_id=p["id"])
    c = make_ticket(project_id=p["id"])
    _link_ticket(client, a["id"], "POR-301", status="done")
    _link_ticket(client, b["id"], "POR-302", status="in_progress")
    _link_ticket(client, c["id"], "POR-303", status="todo")
    # POR-301 + 302 are under Epic POR-500; POR-303 is under Epic POR-501.
    issues_response = {"issues": [
        {"key": "POR-301", "id": "1", "fields": {
            "summary": "a", "status": {"name": "Done"}, "issuetype": {"name": "Task"},
            "parent": {"key": "POR-500", "fields": {"issuetype": {"name": "Epic"}}}}},
        {"key": "POR-302", "id": "2", "fields": {
            "summary": "b", "status": {"name": "In Progress"}, "issuetype": {"name": "Task"},
            "parent": {"key": "POR-500", "fields": {"issuetype": {"name": "Epic"}}}}},
        {"key": "POR-303", "id": "3", "fields": {
            "summary": "c", "status": {"name": "To Do"}, "issuetype": {"name": "Task"},
            "parent": {"key": "POR-501", "fields": {"issuetype": {"name": "Epic"}}}}},
    ]}
    epic_response = {"issues": [
        {"key": "POR-500", "id": "100", "fields": {"summary": "Epic Alpha", "status": {"name": "In Progress"}, "issuetype": {"name": "Epic"}}},
        {"key": "POR-501", "id": "101", "fields": {"summary": "Epic Beta",  "status": {"name": "To Do"},      "issuetype": {"name": "Epic"}}},
    ]}

    call_counter = {"n": 0}
    def _fake_request(method, url, **kw):
        call_counter["n"] += 1
        # First batch: linked ticket keys. Second batch: epic keys.
        jql = kw.get("params", {}).get("jql", "")
        if "POR-301" in jql or "POR-302" in jql or "POR-303" in jql:
            return _mock_response(200, issues_response)
        if "POR-500" in jql or "POR-501" in jql:
            return _mock_response(200, epic_response)
        return _mock_response(200, {"issues": []})
    monkeypatch.setattr("app.services.jira.requests.request", _fake_request)

    r = client.get(f"/api/jira/rollup?project_id={p['id']}")
    body = r.json()
    epics = body["epics"]
    assert len(epics) == 2

    alpha = next(e for e in epics if e["epic_key"] == "POR-500")
    assert alpha["epic_summary"] == "Epic Alpha"
    assert alpha["linked_count"] == 2
    assert alpha["done"] == 1
    assert alpha["in_progress"] == 1
    assert alpha["completion_pct"] == 50.0

    beta = next(e for e in epics if e["epic_key"] == "POR-501")
    assert beta["linked_count"] == 1
    assert beta["todo"] == 1
    assert beta["completion_pct"] == 0.0


def test_rollup_walks_subtask_parent_chain(client, make_project, make_ticket, configured_jira, monkeypatch):
    p = make_project()
    t = make_ticket(project_id=p["id"])
    _link_ticket(client, t["id"], "POR-401", status="done")
    # POR-401 is a Subtask whose parent is POR-410 (Task) whose parent is POR-500 (Epic).
    initial = {"issues": [
        {"key": "POR-401", "id": "1", "fields": {
            "summary": "subtask", "status": {"name": "Done"}, "issuetype": {"name": "Subtask"},
            "parent": {"key": "POR-410", "fields": {"issuetype": {"name": "Task"}}}}},
    ]}
    grandparent = {"key": "POR-410", "id": "10", "fields": {
        "summary": "Task POR-410", "status": {"name": "In Progress"}, "issuetype": {"name": "Task"},
        "parent": {"key": "POR-500", "fields": {"issuetype": {"name": "Epic"}}}}}
    epic_batch = {"issues": [
        {"key": "POR-500", "id": "100", "fields": {"summary": "Epic Alpha", "status": {"name": "In Progress"}, "issuetype": {"name": "Epic"}}},
    ]}

    def _fake_request(method, url, **kw):
        if url.endswith("/POR-410"):
            return _mock_response(200, grandparent)
        jql = kw.get("params", {}).get("jql", "")
        if "POR-401" in jql:
            return _mock_response(200, initial)
        if "POR-500" in jql:
            return _mock_response(200, epic_batch)
        return _mock_response(200, {"issues": []})
    monkeypatch.setattr("app.services.jira.requests.request", _fake_request)

    r = client.get(f"/api/jira/rollup?project_id={p['id']}")
    body = r.json()
    assert len(body["epics"]) == 1
    epic = body["epics"][0]
    assert epic["epic_key"] == "POR-500"
    assert epic["epic_summary"] == "Epic Alpha"
    assert epic["linked_count"] == 1
    assert epic["done"] == 1
    assert epic["completion_pct"] == 100.0


def test_rollup_bucket_for_tickets_without_epic_ancestor(client, make_project, make_ticket, configured_jira, monkeypatch):
    p = make_project()
    t = make_ticket(project_id=p["id"])
    _link_ticket(client, t["id"], "POR-601", status="todo")
    # Linked issue has no parent at all.
    monkeypatch.setattr(
        "app.services.jira.requests.request",
        MagicMock(return_value=_mock_response(200, {"issues": [
            {"key": "POR-601", "id": "1", "fields": {
                "summary": "orphan", "status": {"name": "To Do"}, "issuetype": {"name": "Task"}}},
        ]})),
    )
    r = client.get(f"/api/jira/rollup?project_id={p['id']}")
    body = r.json()
    assert len(body["epics"]) == 1
    assert body["epics"][0]["epic_key"] is None
    assert body["epics"][0]["linked_count"] == 1
