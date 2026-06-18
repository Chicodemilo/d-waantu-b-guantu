# Path: app/middleware/activity_logger.py
# File: activity_logger.py
# Created: 2026-03-29
# Purpose: Middleware to auto-log POST/PATCH/DELETE activity to activity_log (DWB-329: subpath-aware entity_type for consolidate-complete)
# Caller: app/main.py
# Callees: app/database.SessionLocal, app/models/activity_log.ActivityLog
# Data In: HTTP request/response, X-Agent-ID header
# Data Out: activity_log rows (side effect)
# Last Modified: 2026-06-12 (DWB-329)

"""FastAPI middleware that auto-inserts activity_log rows for mutating requests."""

import json
import logging
import re

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import SessionLocal
from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.project_agent import ProjectAgent

logger = logging.getLogger(__name__)

# Maps HTTP method → action verb
_METHOD_ACTION = {
    "POST": "created",
    "PATCH": "updated",
    "PUT": "updated",
    "DELETE": "deleted",
}

# Pattern: /api/<entity_type> or /api/<entity_type>/<id>/...
_PATH_RE = re.compile(r"^/api/([a-z][a-z0-9_-]+)")

# DWB-329 subpath-aware overrides. Some /api/agents/{id}/<subpath> endpoints
# are administrative acks rather than agent-create work; tagging them with a
# more specific entity_type lets participants_for_sprint exclude them from
# the sprint-participation activity_log signal. Add more entries here when
# new admin/gate subpaths emerge (e.g. dismiss-all, reopen-sprint).
_CONSOLIDATE_COMPLETE_RE = re.compile(
    r"^/api/agents/\d+/consolidate-complete(?:/\d+)?/?$"
)


def _parse_entity_type(path: str) -> str | None:
    """Extract entity type from URL path, e.g. /api/tickets/5 → 'ticket'.

    DWB-329: /api/agents/{id}/consolidate-complete (POST + DELETE) maps to
    the dedicated entity_type 'agent_consolidation_ack' so participation
    signals can exclude it. All other /api/agents subpaths still resolve to
    'agent'.
    """
    if _CONSOLIDATE_COMPLETE_RE.match(path):
        return "agent_consolidation_ack"
    m = _PATH_RE.match(path)
    if not m:
        return None
    raw = m.group(1)
    # Strip trailing 's' for plural → singular (tickets→ticket, sprints→sprint)
    if raw.endswith("ies"):
        return raw[:-3] + "y"
    if raw.endswith("s") and not raw.endswith("ss"):
        raw = raw[:-1]
    # Normalize hyphens to underscores
    return raw.replace("-", "_")


def _resolve_agent_id(request: Request, data: dict, entity_type: str, project_id: int, db) -> int | None:
    """Resolve agent_id using priority chain:
    1. X-Agent-ID header (highest priority)
    2. Response body fields (entity-type-aware)
    3. Project PM/TL fallback for sprint/epic creation
    4. None (shows as "system")
    """
    # 1. X-Agent-ID header — highest priority
    header_val = request.headers.get("X-Agent-ID")
    if header_val:
        try:
            return int(header_val)
        except (ValueError, TypeError):
            pass

    # 2. Entity-type-aware body field lookups
    if entity_type == "alert":
        agent_id = data.get("raised_by_agent_id")
        if agent_id:
            return agent_id

    if entity_type == "ticket":
        agent_id = data.get("assigned_agent_id")
        if agent_id:
            return agent_id

    # Generic body field fallback
    for field in ("assigned_agent_id", "agent_id", "raised_by_agent_id"):
        agent_id = data.get(field)
        if agent_id:
            return agent_id

    # 3. For sprint/epic creation — look up project PM or TL as fallback
    if entity_type in ("sprint", "epic") and project_id:
        try:
            agent_id = db.scalars(
                select(Agent.id)
                .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
                .where(ProjectAgent.project_id == project_id)
                .where(Agent.role.in_(["pm", "team-lead"]))
                .order_by(Agent.role.asc())  # pm sorts before team-lead
                .limit(1)
            ).first()
            if agent_id:
                return agent_id
        except Exception:
            pass

    # 4. Last resort: null (shows as "system")
    return None


class ActivityLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method.upper()

        # Only intercept mutating methods
        if method not in _METHOD_ACTION:
            return await call_next(request)

        response = await call_next(request)

        # Only log successful responses (2xx)
        if not (200 <= response.status_code < 300):
            return response

        try:
            await self._log_activity(request, response, method)
        except Exception as exc:
            logger.warning("Activity logging failed: %s", exc)

        return response

    async def _log_activity(
        self, request: Request, response: Response, method: str
    ) -> None:
        path = request.url.path
        action = _METHOD_ACTION[method]
        entity_type = _parse_entity_type(path)
        if not entity_type:
            return

        # Read the response body — need to reconstruct it
        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

        # Rebuild the response so the client still gets the body
        async def _body_gen():
            yield body_bytes
        response.body_iterator = _body_gen()

        # Parse response JSON
        try:
            data = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return

        if not isinstance(data, dict):
            return

        entity_id = data.get("id")
        if entity_id is None:
            return

        project_id = data.get("project_id")
        if project_id is None:
            return

        # Build details — grab key fields, skip large/null values
        detail_keys = ["title", "name", "status", "ticket_key", "severity"]
        details = {}
        for k in detail_keys:
            v = data.get(k)
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                details[k] = v
            else:
                details[k] = str(v)

        details_json = json.dumps(details, default=str) if details else None

        db = SessionLocal()
        try:
            agent_id = _resolve_agent_id(request, data, entity_type, project_id, db)

            db.add(ActivityLog(
                project_id=project_id,
                agent_id=agent_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                details=details_json,
            ))
            db.commit()
        except Exception as exc:
            logger.warning("Failed to insert activity_log: %s", exc)
            db.rollback()
        finally:
            db.close()
