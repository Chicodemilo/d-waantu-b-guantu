# Path: app/routers/server_logs.py
# File: server_logs.py
# Created: 2026-06-10
# Purpose: HTTP read surface over the in-memory server-log ring buffer (DWB-372)
# Caller: app/main.py
# Callees: app/services/server_log_buffer
# Data In: HTTP query params
# Data Out: list[ServerLogRead], ServerLogStats
# Last Modified: 2026-06-10

from datetime import datetime

from fastapi import APIRouter, Query

from app.schemas.server_log import ServerLogRead, ServerLogStats
from app.services import server_log_buffer

router = APIRouter(prefix="/api/server-logs", tags=["server-logs"])


@router.get("", response_model=list[ServerLogRead])
def list_server_logs(
    since: datetime | None = Query(None, description="ISO 8601 - exclude entries older than this"),
    level: str | None = Query(None, description="DEBUG/INFO/WARNING/ERROR/CRITICAL (case-insensitive)"),
    logger: str | None = Query(None, alias="logger", description="Exact logger name match (e.g. 'app.services.ticket')"),
    q: str | None = Query(None, description="Substring match against message body (case-insensitive)"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query the in-memory ring buffer. Most-recent first.

    Filters compose with AND semantics. Limit is bounded; default 100.
    The buffer is module-level and does NOT survive `uvicorn --reload`
    (documented in server_log_buffer.py).
    """
    return server_log_buffer.query(
        since=since,
        level=level,
        logger_name=logger,
        q=q,
        limit=limit,
    )


@router.get("/stats", response_model=ServerLogStats)
def server_log_stats():
    """Current buffer occupancy + capacity. Useful for sanity-checking
    whether the handler is actually wired up after a `--reload`."""
    return {
        "size": server_log_buffer.size(),
        "maxlen": server_log_buffer.maxlen(),
    }
