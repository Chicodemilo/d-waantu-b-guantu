# Path: app/services/jira.py
# File: jira.py
# Created: 2026-05-27
# Purpose: Read-only Jira REST client with in-process TTL cache for slow-changing data
# Caller: app/routers/jira.py
# Callees: requests, app.config
# Data In: Jira REST API responses
# Data Out: Normalized dicts for FastAPI routers
# Last Modified: 2026-05-27

"""Minimal Jira REST wrapper used by the `/api/jira/*` proxy endpoints.

Sync-only (matches the rest of this codebase). Caching is an in-process
dict keyed by (method, path, frozen-params); each entry stores (expires_at,
value). The cache is opt-in per call — pass `cache_ttl=...` to enable it.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests
from fastapi import HTTPException
from requests.auth import HTTPBasicAuth

from app.config import settings

_TIMEOUT = 15  # seconds — fail fast; Jira is usually <1s

_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_key(method: str, path: str, params: Optional[dict]) -> tuple:
    if params:
        items = tuple(sorted((k, str(v)) for k, v in params.items()))
    else:
        items = ()
    return (method.upper(), path, items)


def _cache_get(key: tuple) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            _cache.pop(key, None)
            return None
        return value


def _cache_set(key: tuple, value: Any, ttl: int) -> None:
    with _cache_lock:
        _cache[key] = (time.time() + ttl, value)


def clear_cache() -> None:
    """Drop all cached entries — used by tests and by an admin endpoint."""
    with _cache_lock:
        _cache.clear()


def _require_configured() -> None:
    if not settings.jira_configured:
        raise HTTPException(
            503,
            "Jira is not configured — set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN in .env",
        )


def _request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    cache_ttl: int = 0,
) -> Any:
    """Call Jira and return parsed JSON. Raises HTTPException on failure.

    When `cache_ttl > 0`, the response is memoized for that many seconds.
    Cache keys hash the method/path/params — bodies are not supported (read-only).
    """
    _require_configured()

    key = _cache_key(method, path, params)
    if cache_ttl > 0:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    url = settings.JIRA_BASE_URL.rstrip("/") + path
    try:
        resp = requests.request(
            method,
            url,
            params=params,
            auth=HTTPBasicAuth(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HTTPException(502, f"Jira request failed: {exc}")

    if resp.status_code == 401:
        raise HTTPException(401, "Jira auth failed — check JIRA_EMAIL / JIRA_API_TOKEN")
    if resp.status_code == 404:
        raise HTTPException(404, f"Jira returned 404 for {path}")
    if resp.status_code >= 400:
        # Surface Jira's error text but cap it so we don't leak huge payloads.
        body = (resp.text or "")[:500]
        raise HTTPException(resp.status_code, f"Jira error: {body}")

    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(502, "Jira returned non-JSON response")

    if cache_ttl > 0:
        _cache_set(key, data, cache_ttl)
    return data


# ── Public read API ────────────────────────────────────────────────


def list_projects() -> list[dict]:
    """List all Jira projects visible to the configured user. Cached (slow-changing)."""
    data = _request(
        "GET",
        "/rest/api/3/project/search",
        params={"maxResults": 100},
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS * 5,
    )
    return [
        {"id": p.get("id"), "key": p.get("key"), "name": p.get("name")}
        for p in data.get("values", [])
    ]


def get_issue(issue_key: str) -> dict:
    """Return a normalized issue dict for the given Jira key."""
    raw = _request(
        "GET",
        f"/rest/api/3/issue/{issue_key}",
        params={"fields": "summary,status,assignee,issuetype,parent,priority,updated,created"},
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS,
    )
    return _normalize_issue(raw)


def search_issues(jql: str, limit: int = 50) -> list[dict]:
    """Search via JQL and return normalized issues."""
    data = _request(
        "GET",
        "/rest/api/3/search/jql",
        params={
            "jql": jql,
            "maxResults": min(max(1, limit), 100),
            "fields": "summary,status,assignee,issuetype,parent,priority,updated,created",
        },
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS,
    )
    return [_normalize_issue(i) for i in data.get("issues", [])]


def get_active_sprints(project_key: str) -> list[dict]:
    """Return active sprints for a project's default board (first board)."""
    boards = _request(
        "GET",
        "/rest/agile/1.0/board",
        params={"projectKeyOrId": project_key, "type": "scrum"},
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS * 10,
    )
    values = boards.get("values", [])
    if not values:
        return []
    board_id = values[0]["id"]
    sprints = _request(
        "GET",
        f"/rest/agile/1.0/board/{board_id}/sprint",
        params={"state": "active"},
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS,
    )
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "state": s.get("state"),
            "start_date": s.get("startDate"),
            "end_date": s.get("endDate"),
        }
        for s in sprints.get("values", [])
    ]


def get_sprint_issues(sprint_id: int) -> list[dict]:
    """Return all issues in a Jira sprint (normalized)."""
    data = _request(
        "GET",
        f"/rest/agile/1.0/sprint/{sprint_id}/issue",
        params={"fields": "summary,status,assignee,issuetype,parent,priority,updated"},
        cache_ttl=settings.JIRA_CACHE_TTL_SECONDS,
    )
    return [_normalize_issue(i) for i in data.get("issues", [])]


def batch_get_issues(issue_keys: list[str]) -> list[dict]:
    """Look up many Jira issues in a single JQL call. Chunked to 100 keys.

    Order is not preserved; caller should re-key by `.key` if needed. Skips
    cache because the typical caller is the sync job which wants live data.
    """
    if not issue_keys:
        return []
    results: list[dict] = []
    keys = list({k for k in issue_keys if k})  # de-dupe while preserving order doesn't matter
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        jql = f"key in ({','.join(chunk)})"
        data = _request(
            "GET",
            "/rest/api/3/search/jql",
            params={
                "jql": jql,
                "maxResults": 100,
                "fields": "summary,status,assignee,issuetype,parent,priority,updated,created",
            },
            cache_ttl=0,
        )
        for raw in data.get("issues", []):
            results.append(_normalize_issue(raw))
    return results


# ── Status mapping (Jira → DWB) ────────────────────────────────────


# Source of truth for the auto-sync job. Lower-cased keys for robust matching.
JIRA_TO_DWB_STATUS: dict[str, str] = {
    "to do":                   "todo",
    "open":                    "todo",
    "backlog":                 "backlog",
    "in progress":             "in_progress",
    "in review":               "in_review",
    "ready for testing/review": "in_review",
    "ready for testing":       "in_review",
    "ready for review":        "in_review",
    "done":                    "done",
    "resolved":                "done",
    "closed":                  "done",
    "won't do":                "done",
}


def jira_status_to_dwb(jira_status: str | None) -> str | None:
    """Return the DWB status that maps to this Jira status, or None if unknown."""
    if not jira_status:
        return None
    return JIRA_TO_DWB_STATUS.get(jira_status.strip().lower())


# ── Sync: Jira → DWB ──────────────────────────────────────────────


def sync_linked_tickets(db, project_id: int | None = None) -> dict:
    """Pull current Jira status for every linked DWB ticket and update DWB rows.

    Jira leads — when a Jira status maps to a different DWB status than the
    ticket currently has, we PATCH the ticket. Unknown Jira statuses (no entry
    in JIRA_TO_DWB_STATUS) are reported under `unmapped` and don't touch DWB.

    Returns: {synced, changed, unmapped, errors, details}
      - synced: number of linked tickets considered
      - changed: number of rows updated
      - unmapped: list of {jira_key, jira_status} skipped
      - errors:   list of {jira_key, error}
      - details:  list of {jira_key, dwb_id, before, after} for each change
    """
    # Local imports avoid hard-coupling jira service to ticket model at import time.
    from sqlalchemy import select
    from app.models.ticket import Ticket
    from app.schemas.ticket import TicketUpdate
    from app.services import ticket as ticket_svc

    stmt = select(Ticket).where(Ticket.jira_issue_key.isnot(None))
    if project_id is not None:
        stmt = stmt.where(Ticket.project_id == project_id)
    linked = list(db.scalars(stmt))

    if not linked:
        return {"synced": 0, "changed": 0, "unmapped": [], "errors": [], "details": []}

    key_to_ticket = {t.jira_issue_key: t for t in linked}
    keys = list(key_to_ticket.keys())

    try:
        issues = batch_get_issues(keys)
    except HTTPException:
        raise  # let the router surface this as-is
    except Exception as exc:
        raise HTTPException(502, f"Jira batch fetch failed: {exc}")

    by_key = {i["key"]: i for i in issues if i.get("key")}
    missing = [k for k in keys if k not in by_key]

    changed = 0
    unmapped: list[dict] = []
    errors: list[dict] = []
    details: list[dict] = []

    for key, ticket in key_to_ticket.items():
        issue = by_key.get(key)
        if issue is None:
            errors.append({"jira_key": key, "error": "Jira issue not found or inaccessible"})
            continue
        jira_status = issue.get("status")
        mapped = jira_status_to_dwb(jira_status)
        if mapped is None:
            unmapped.append({"jira_key": key, "jira_status": jira_status})
            continue
        current = ticket.status.value if hasattr(ticket.status, "value") else ticket.status
        if mapped == current:
            continue
        try:
            ticket_svc.update_ticket(db, ticket, TicketUpdate(status=mapped))
            details.append({
                "jira_key": key,
                "dwb_id": ticket.id,
                "before": current,
                "after": mapped,
            })
            changed += 1
        except Exception as exc:
            errors.append({"jira_key": key, "error": str(exc)})

    return {
        "synced": len(linked),
        "changed": changed,
        "unmapped": unmapped,
        "errors": errors,
        "details": details,
        "missing": missing,
    }


# ── Rollup: DWB ticket completion grouped by Jira Epic ─────────────


def rollup_by_epic(db, project_id: int) -> dict:
    """Group linked DWB tickets by their root Jira Epic and return per-epic stats.

    Walks one hop up the parent chain for non-Epic parents (matches the
    `report` Subtask handling). Tickets whose linked Jira issue has no Epic
    ancestor (or is itself an Epic) are bucketed under "(no epic)".
    """
    from sqlalchemy import select
    from app.models.ticket import Ticket

    linked = list(db.scalars(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.jira_issue_key.isnot(None))
    ))
    if not linked:
        return {"project_id": project_id, "epics": [], "unlinked_count": 0}

    keys = [t.jira_issue_key for t in linked]
    issues = batch_get_issues(keys)
    by_key = {i["key"]: i for i in issues if i.get("key")}

    # Resolve Epic for each linked ticket. Non-Epic parents → one extra hop.
    epic_for_key: dict[str, str | None] = {}
    extra_lookups: dict[str, str | None] = {}  # parent_key → root_epic_key
    for key in keys:
        issue = by_key.get(key)
        if not issue:
            epic_for_key[key] = None
            continue
        parent_key = issue.get("parent_key")
        parent_type = (issue.get("parent_type") or "").lower()
        if not parent_key:
            epic_for_key[key] = None
            continue
        if parent_type == "epic":
            epic_for_key[key] = parent_key
            continue
        # Non-Epic parent — one extra hop, cached per parent_key.
        if parent_key not in extra_lookups:
            try:
                parent_issue = get_issue(parent_key)
                gp = parent_issue.get("parent_key")
                gp_type = (parent_issue.get("parent_type") or "").lower()
                extra_lookups[parent_key] = gp if gp_type == "epic" else None
            except Exception:
                extra_lookups[parent_key] = None
        epic_for_key[key] = extra_lookups[parent_key]

    # Fetch Epic summaries (single batch, cached).
    epic_keys = sorted({e for e in epic_for_key.values() if e})
    epic_summaries: dict[str, str] = {}
    if epic_keys:
        for e in batch_get_issues(epic_keys):
            if e.get("key"):
                epic_summaries[e["key"]] = e.get("summary", "")

    # Group tickets and tally.
    buckets: dict[str, dict] = {}
    for ticket in linked:
        epic_key = epic_for_key.get(ticket.jira_issue_key)
        bucket_key = epic_key or "(no epic)"
        bucket = buckets.setdefault(bucket_key, {
            "epic_key": epic_key,
            "epic_summary": epic_summaries.get(epic_key, "") if epic_key else "",
            "linked_count": 0,
            "done": 0,
            "in_progress": 0,
            "in_review": 0,
            "todo": 0,
            "backlog": 0,
            "tickets": [],
        })
        status = ticket.status.value if hasattr(ticket.status, "value") else ticket.status
        bucket["linked_count"] += 1
        bucket.setdefault(status, 0)
        bucket[status] += 1
        bucket["tickets"].append({
            "id": ticket.id,
            "ticket_key": ticket.ticket_key,
            "jira_issue_key": ticket.jira_issue_key,
            "status": status,
        })

    out = []
    for bucket in buckets.values():
        total = bucket["linked_count"] or 1
        bucket["completion_pct"] = round(100 * bucket["done"] / total, 1)
        out.append(bucket)
    # Stable sort: epic key (no-epic last).
    out.sort(key=lambda b: (b["epic_key"] is None, b["epic_key"] or ""))

    return {"project_id": project_id, "epics": out}


# ── Normalization ─────────────────────────────────────────────────


def _normalize_issue(raw: dict) -> dict:
    """Flatten Jira's deeply-nested issue shape into a frontend-friendly dict."""
    fields = raw.get("fields") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    issuetype = fields.get("issuetype") or {}
    parent = fields.get("parent") or {}
    parent_fields = parent.get("fields") or {}
    priority = fields.get("priority") or {}

    return {
        "key": raw.get("key"),
        "id": raw.get("id"),
        "summary": fields.get("summary") or "",
        "status": status.get("name"),
        "status_category": (status.get("statusCategory") or {}).get("name"),
        "assignee": assignee.get("displayName"),
        "issue_type": issuetype.get("name"),
        "parent_key": parent.get("key"),
        "parent_type": (parent_fields.get("issuetype") or {}).get("name"),
        "priority": priority.get("name"),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }
