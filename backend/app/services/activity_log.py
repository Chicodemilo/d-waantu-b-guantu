# Path: app/services/activity_log.py
# File: activity_log.py
# Created: 2026-03-29
# Purpose: Activity log CRUD, filtered queries, and the canonical log_activity() semantic-event helper (DWB-408)
# Caller: app/routers/activity_logs.py, app/services/* (semantic domain events)
# Callees: app/models/activity_log.py
# Data In: db: Session, filters, semantic-event fields
# Data Out: list[ActivityLog], ActivityLog
# Last Modified: 2026-06-23 (DWB-432: register scoring semantic verbs)

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.schemas.activity_log import ActivityLogCreate

# ---------------------------------------------------------------------------
# Action verb vocabulary (DWB-408)
#
# The activity_log carries two CLASSES of rows, distinguished by `action`:
#
#   1. Generic CRUD, logged AUTOMATICALLY by ActivityLoggerMiddleware. It
#      derives the verb from the HTTP method, so it only ever emits one of
#      MIDDLEWARE_ACTIONS below. It is the catch-all fallback: every 2xx
#      mutating request with an `id` + `project_id` in its response body
#      produces exactly one such row.
#
#   2. Semantic DOMAIN EVENTS, logged EXPLICITLY via log_activity() from the
#      service layer (e.g. a ticket status transition -> "status_changed").
#      These carry richer, hand-built `details`.
#
# THE NO-DOUBLE-LOG RULE
# ----------------------
# A semantic event and the middleware's generic row are NOT a double-log: they
# are deliberately kept DISTINCT by verb. SEMANTIC_ACTIONS is disjoint from
# MIDDLEWARE_ACTIONS (enforced by test), so a single PATCH /api/tickets/{id}
# that changes status yields TWO rows with DIFFERENT verbs:
#   - one `updated` row (middleware, generic catch-all)
#   - one `status_changed` row (this helper, semantic detail {from, to})
# The feed can therefore prefer the semantic verb and treat the generic
# `updated` as a low-signal fallback, without either masking the other.
#
# RULE FOR NEW EVENTS: never emit a semantic event whose action is one of
# MIDDLEWARE_ACTIONS. Pick a distinct, past-tense verb and register it in
# SEMANTIC_ACTIONS so the disjointness test keeps guarding the boundary.
MIDDLEWARE_ACTIONS = frozenset({"created", "updated", "deleted"})

SEMANTIC_ACTIONS = frozenset({
    # ticket events (DWB-409)
    "status_changed",
    "assigned",
    "reopened",
    # sprint / consolidation events (DWB-410)
    "sprint_opened",
    "sprint_closed",
    "consolidation_acked",
    # DWB session events (DWB-411)
    "session_opened",
    "session_closed",
    # agent tool-action events (DWB-418..421). Emitted from the PostToolUse /
    # lifecycle hook handlers in hook_tracking.py, entity_type="tool_action".
    # The hook endpoints are not logged by ActivityLoggerMiddleware (their
    # responses carry no id/project_id), so these never shadow a generic row -
    # no SEMANTIC_GENERIC_SHADOWS entry is needed (the .get default is empty).
    "file_written",
    "message_sent",
    "agent_spawned",
    "notification",
    "context_compaction",
    # scoring events (DWB-432). score_awarded/score_docked fire for human + peer
    # carrots/sticks only (auto-triggers are already represented by their
    # ticket/test/failure feed events). lead_change fires when the project #1
    # spot flips. entity_type="agent". Not middleware-logged -> no shadow entry.
    "score_awarded",
    "score_docked",
    "lead_change",
    # DWB-463: the ad-hoc test-run request is demoted from an alert to a feed
    # action (epic 37, alerts-vs-actions). The sprint-close "tests needed"
    # notice is NOT given its own verb - the existing sprint_closed event
    # already represents the close in the feed, and peer scoring already has
    # score_awarded/score_docked, so only test-run needed a new verb. The
    # run-tests endpoint returns no id, so the middleware never logs a generic
    # row for it (no shadow entry needed).
    "test_run_requested",
})

# Read-side feed dedup (DWB-409). Maps each semantic event to the generic
# middleware verb(s) it SHADOWS — i.e. the CRUD row the SAME request also
# produced. The feed suppresses a generic row only when a semantic sibling
# whose shadow set includes that generic action exists for the same entity
# within a short window. Action-class pairing (not a bare time window) is what
# keeps an unrelated event from masking a generic row: a ticket `created` row
# is never shadowed by `status_changed`, so creation always surfaces even when
# a status change lands seconds later. A semantic action mapped to an empty set
# never suppresses anything (consolidation_acked: the middleware doesn't log
# the ack at all — its response carries no project_id).
SEMANTIC_GENERIC_SHADOWS: dict[str, frozenset] = {
    "status_changed": frozenset({"updated"}),
    "assigned": frozenset({"updated"}),
    "reopened": frozenset({"updated"}),
    # sprint_opened fires from POST-create-active (created) OR PATCH planned->active (updated)
    "sprint_opened": frozenset({"created", "updated"}),
    "sprint_closed": frozenset({"updated"}),
    "consolidation_acked": frozenset(),
    # session open/close are both POST endpoints -> middleware logs 'created'
    "session_opened": frozenset({"created"}),
    "session_closed": frozenset({"created"}),
}


def log_activity(
    db: Session,
    project_id: int,
    agent_id: int | None,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict | str | None = None,
) -> ActivityLog:
    """Insert a single activity_log row for a semantic domain event (DWB-408).

    This is the ONE canonical way the service layer records a semantic event.
    The ActivityLoggerMiddleware remains the automatic catch-all for generic
    CRUD; this helper is for explicit, verb-distinct domain events (see the
    no-double-log rule above).

    Behaviour:
    - `details` may be a dict (JSON-encoded here), a pre-serialized str, or
      None. An empty dict is stored as None.
    - The row is added and FLUSHED (so `id`/`created_at` populate) but NOT
      committed: the caller's request-scoped session (get_db) owns commit, per
      the service-layer no-commit rule. Callers outside a request context must
      commit themselves.

    Returns the persisted ActivityLog instance.
    """
    if isinstance(details, dict):
        details_str = json.dumps(details, default=str) if details else None
    else:
        details_str = details

    log = ActivityLog(
        project_id=project_id,
        agent_id=agent_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        details=details_str,
    )
    db.add(log)
    db.flush()
    return log


def list_activity_logs(
    db: Session,
    project_id: int | None = None,
    agent_id: int | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[ActivityLog]:
    stmt = select(ActivityLog)
    if project_id:
        stmt = stmt.where(ActivityLog.project_id == project_id)
    if agent_id:
        stmt = stmt.where(ActivityLog.agent_id == agent_id)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    stmt = stmt.order_by(ActivityLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_activity_log(db: Session, log_id: int) -> ActivityLog | None:
    return db.get(ActivityLog, log_id)


def create_activity_log(db: Session, data: ActivityLogCreate) -> ActivityLog:
    log = ActivityLog(**data.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
