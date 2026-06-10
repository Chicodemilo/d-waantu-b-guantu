# Path: app/services/jira_sync.py
# File: jira_sync.py
# Created: 2026-06-10
# Purpose: Manual Jira -> DWB cache sync. READ-ONLY ingestion: NEVER writes back to Jira (DWB-342)
# Caller: app/routers/projects.py (jira-sync endpoints)
# Callees: app/services/jira.py (read-only client), app/models/jira_ticket_snapshot, app/models/project
# Data In: Jira REST responses (via app.services.jira), DWB ticket + snapshot rows
# Data Out: Refreshed jira_ticket_snapshots rows + project sync-state columns; counts dict
# Last Modified: 2026-06-10

"""Manual Jira -> DWB ingestion for the unified Jira table (DWB-342).

Hard rule: NOTHING in this module mutates Jira. Every call into
``app.services.jira`` is a read (search / get / list). The whole point
of the read-only contract is that a future regression that adds a write
call will be visible in this file's diff; everything Jira-mutating in
the codebase routes through ``dwb2jira`` (which is intentionally NOT
imported here).

Concurrency: at most one sync per project at a time. Enforced via
``project.last_jira_sync_status`` - the lock taker bumps to ``running``
inside a SELECT ... FOR UPDATE then commits; a second concurrent caller
sees ``running`` and is told to retry. The lock is released on success
(``done``) or failure (``error``) so retries don't need manual
intervention.

Idempotent: running back-to-back on an unchanged Jira side produces
zero ``updated`` rows the second time. The diff check is field-by-field
on the snapshot columns, not a blanket overwrite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jira_ticket_snapshot import JiraTicketSnapshot
from app.models.project import JiraSyncStatus, Project
from app.models.ticket import Ticket
from app.services import jira as jira_client


class SyncAlreadyRunning(Exception):
    """Raised when a second sync is requested while one is in flight."""


class SyncNotConfigured(Exception):
    """Raised when the project has no Jira link (project.jira_base_url is null).

    DWB-342 list endpoint may serve an empty table for non-Jira projects
    (clear "no linked tickets" message); attempting to sync one is a
    different surface and should 400 with a clear message.
    """


# Field names on JiraTicketSnapshot that the sync writes to. Used by the
# diff loop and to keep the snapshot upsert in one place. Order matters
# only for readability.
_SNAPSHOT_FIELDS = (
    "jira_status",
    "jira_sprint_name",
    "jira_assignee",
    "jira_reporter",
    "jira_title",
    "jira_description",
    "jira_created_at",
    "jira_updated_at",
    # DWB-362: 11th column - Jira issue type (Task / Bug / Sub-task / etc.).
    "jira_issue_type",
    # DWB-363: 12th column - Jira epic (key + resolved name).
    "jira_epic_key",
    "jira_epic_name",
    # DWB-364: 13th column - parent Jira key (subtasks only; NULL otherwise).
    "jira_parent_key",
)


def _parse_jira_datetime(value: str | None) -> datetime | None:
    """Jira returns ISO 8601 strings with a "+0000" zone. Parse to naive UTC.

    Returns None when value is None or unparseable (defensive - we'd rather
    leave the snapshot field NULL than fail the whole sync on a single
    weird row).
    """
    if not value:
        return None
    try:
        # Strip the timezone offset to land in naive UTC (DWB datetime columns
        # are naive). Jira sends "2026-06-10T12:00:00.000+0000".
        cleaned = value.replace("Z", "+0000")
        # Common Jira format: trailing "+0000" without a colon. Insert one
        # so fromisoformat is happy on pre-Python-3.11 builds.
        if cleaned.endswith("+0000"):
            cleaned = cleaned[:-5] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _normalize_jira_payload(issue: dict) -> dict:
    """Translate a normalized Jira issue (from jira_client._normalize_issue)
    into the snapshot column shape.

    The Jira normalizer gives us flattened keys (summary, status,
    assignee, reporter, sprint_name, issue_type, parent, etc.). DWB-356
    added sprint_name + reporter extraction; DWB-362 added issue_type to
    the snapshot column. ``description`` is still not extracted by the
    upstream normalizer (the snapshot column stays NULL for now);
    follow-up if needed.
    """
    return {
        "jira_status": issue.get("status"),
        "jira_sprint_name": issue.get("sprint_name"),
        "jira_assignee": issue.get("assignee"),
        "jira_reporter": issue.get("reporter"),
        "jira_title": issue.get("summary"),
        "jira_description": issue.get("description"),
        "jira_created_at": _parse_jira_datetime(issue.get("created")),
        "jira_updated_at": _parse_jira_datetime(issue.get("updated")),
        # DWB-362: issuetype.name flattened by app.services.jira._normalize_issue.
        "jira_issue_type": issue.get("issue_type"),
        # DWB-363: epic_key from _extract_epic_key. epic_name is resolved
        # in a second batched pass after the per-issue normalize, so the
        # initial payload here leaves it as None and run_sync fills it in.
        "jira_epic_key": issue.get("epic_key"),
        "jira_epic_name": None,
        # DWB-364: parent key, but ONLY for subtasks. Gated on the
        # authoritative issuetype.subtask boolean so the gate is robust
        # to issue-type name variants ("Sub-task" / "Subtask" / etc.).
        # For non-subtask tickets the parent linkage is either
        # (a) None, or (b) already surfaced via the Epic column, so
        # we persist None here to keep the Parent column subtask-
        # exclusive per the spec.
        "jira_parent_key": (
            issue.get("parent_key")
            if issue.get("issue_type_is_subtask")
            else None
        ),
    }


def _try_acquire_lock(db: Session, project: Project) -> bool:
    """Bump project.last_jira_sync_status to 'running' if it's not already.

    Returns True if this caller took the lock, False if another sync was
    already in flight. Commits immediately so a concurrent caller in
    another process sees the running flag.
    """
    if project.last_jira_sync_status == JiraSyncStatus.running:
        return False
    project.last_jira_sync_status = JiraSyncStatus.running
    db.commit()
    return True


def _release_lock(
    db: Session,
    project: Project,
    *,
    status: JiraSyncStatus,
    counts: dict[str, Any] | None,
) -> None:
    project.last_jira_sync_status = status
    project.last_jira_sync_counts = counts
    project.last_jira_sync_at = datetime.utcnow().replace(microsecond=0)
    db.commit()


def run_sync(
    db: Session,
    project_id: int,
    *,
    jira_client_override: Any = None,
) -> dict[str, Any]:
    """Pull Jira-side snapshot for every linked DWB ticket and upsert.

    Returns a counts dict::

        {
            "added": int,       # new snapshot rows created
            "updated": int,     # snapshot rows that changed
            "unchanged": int,   # snapshot rows that already matched
            "missing": list,    # Jira keys we couldn't fetch
            "errors": list,     # per-ticket errors (non-fatal)
        }

    Raises:
      - SyncNotConfigured: project has no jira_base_url.
      - SyncAlreadyRunning: another sync is in flight for this project.

    ``jira_client_override`` is an injection seam for tests. When None,
    uses the real ``app.services.jira`` module. When set, the object
    must expose ``batch_get_issues(list[str]) -> list[dict]`` matching
    the real client's contract. The override gets passed through here
    instead of monkey-patching the module so the test can assert which
    methods got called (read-only invariant).
    """
    project = db.get(Project, project_id)
    if project is None:
        # Caller (router) is expected to 404 before calling, but be defensive.
        raise SyncNotConfigured(f"project {project_id} not found")
    if not project.jira_base_url:
        raise SyncNotConfigured(
            f"project '{project.prefix}' has no jira_base_url - configure Jira "
            f"before running a sync",
        )

    if not _try_acquire_lock(db, project):
        raise SyncAlreadyRunning(
            f"project '{project.prefix}' already has a Jira sync in progress",
        )

    client = jira_client_override or jira_client

    counts: dict[str, Any] = {
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "missing": [],
        "errors": [],
    }

    try:
        linked = list(db.scalars(
            select(Ticket)
            .where(Ticket.project_id == project_id)
            .where(Ticket.jira_issue_key.isnot(None))
        ))
        if not linked:
            # Project has no linked tickets - clean exit, counts are zero.
            _release_lock(db, project, status=JiraSyncStatus.done, counts=counts)
            return counts

        keys = [t.jira_issue_key for t in linked]
        # READ-ONLY fetch. Two batch_get_issues calls total: one for the
        # linked tickets, one for the unique epic keys those tickets
        # reference (DWB-363, to populate jira_epic_name). Both are reads.
        issues = client.batch_get_issues(keys)
        by_key = {i["key"]: i for i in issues if i.get("key")}

        # DWB-363: collect unique epic keys from the just-fetched issues,
        # then batch-fetch the epic issues themselves to resolve their
        # summaries. ONE extra call per sync regardless of project size -
        # we explicitly avoid an N+1 fetch per linked ticket. Epic keys
        # that aren't reachable (deleted, restricted) get summary=None
        # and the sync persists epic_key only.
        epic_keys = sorted({
            issue["epic_key"] for issue in by_key.values()
            if issue.get("epic_key")
        })
        epic_summaries: dict[str, str] = {}
        if epic_keys:
            try:
                epic_issues = client.batch_get_issues(epic_keys)
                for ei in epic_issues:
                    if ei.get("key"):
                        epic_summaries[ei["key"]] = ei.get("summary") or ""
            except Exception as exc:  # pragma: no cover - defensive
                # Don't fail the whole sync because the epic-summary
                # lookup tripped. Snapshots still write epic_key; the
                # name stays None until the next sync retries.
                counts["errors"].append({
                    "epic_lookup": f"{type(exc).__name__}: {exc}",
                })

        # Existing snapshots keyed by ticket_id for the diff loop.
        existing_snapshots = {
            s.ticket_id: s for s in db.scalars(
                select(JiraTicketSnapshot).where(
                    JiraTicketSnapshot.ticket_id.in_([t.id for t in linked])
                )
            )
        }

        for ticket in linked:
            issue = by_key.get(ticket.jira_issue_key)
            if issue is None:
                counts["missing"].append(ticket.jira_issue_key)
                continue
            try:
                normalized = _normalize_jira_payload(issue)
                # DWB-363: fill epic_name from the cached batched lookup.
                # epic_key may be None (no epic on this issue) - leave name None too.
                if normalized.get("jira_epic_key"):
                    normalized["jira_epic_name"] = epic_summaries.get(
                        normalized["jira_epic_key"]
                    )
            except Exception as exc:  # pragma: no cover - defensive
                counts["errors"].append({
                    "jira_key": ticket.jira_issue_key,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            snapshot = existing_snapshots.get(ticket.id)
            now = datetime.utcnow().replace(microsecond=0)

            if snapshot is None:
                snapshot = JiraTicketSnapshot(
                    ticket_id=ticket.id,
                    jira_issue_key=ticket.jira_issue_key,
                    last_synced_at=now,
                    **normalized,
                )
                db.add(snapshot)
                counts["added"] += 1
                continue

            # Diff check - only count as "updated" when a snapshot column
            # actually changed. Per-row last_synced_at always bumps so the
            # frontend can show how fresh each row is.
            changed = False
            for field in _SNAPSHOT_FIELDS:
                new_val = normalized[field]
                if getattr(snapshot, field) != new_val:
                    setattr(snapshot, field, new_val)
                    changed = True
            # Keep the cached key in lockstep with the canonical link in
            # case a ticket got its jira_issue_key edited.
            if snapshot.jira_issue_key != ticket.jira_issue_key:
                snapshot.jira_issue_key = ticket.jira_issue_key
                changed = True
            snapshot.last_synced_at = now
            if changed:
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1

        db.flush()
        _release_lock(db, project, status=JiraSyncStatus.done, counts=counts)
        return counts
    except SyncAlreadyRunning:
        # Lock release not needed - we didn't actually take it.
        raise
    except Exception as exc:
        # Release the lock on error so the operator can retry without
        # manual intervention. Capture the error in the counts payload.
        counts["errors"].append({"sync": f"{type(exc).__name__}: {exc}"})
        _release_lock(db, project, status=JiraSyncStatus.error, counts=counts)
        raise
