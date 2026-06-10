# Path: app/routers/client_logs.py
# File: client_logs.py
# Created: 2026-06-10
# Purpose: HTTP endpoints for frontend telemetry feed (DWB-371) - batch POST + filtered GET
# Caller: app/main.py
# Callees: app/services/client_log.py
# Data In: HTTP requests (batch logs from frontend, TL queries)
# Data Out: ClientLogBatchResponse, list[ClientLogRead]
# Last Modified: 2026-06-10

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.client_log import ClientLogLevel
from app.schemas.client_log import ClientLogBatchResponse, ClientLogRead
from app.services import client_log as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/client-logs", tags=["client-logs"])


@router.post("", response_model=ClientLogBatchResponse, status_code=200)
def post_client_logs(
    records: list[dict[str, Any]] = Body(..., embed=False),
    db: Session = Depends(get_db),
):
    """Accept a batch of client log records. Never-5xx contract: malformed
    records are dropped individually and reported in the rejections list;
    the rest still land. An empty batch is a no-op (received=0).

    The body is `list[dict]` (not `list[ClientLogCreate]`) on purpose:
    pydantic-strict batch validation would 422 the whole request on a
    single bad record, defeating the lenient ingestion contract spec'd
    in the ticket. The service re-validates each item.
    """
    try:
        result = svc.insert_batch(db, records)
        return result
    except Exception as e:
        logger.exception("post_client_logs error")
        # Keep the never-5xx contract. Return the shape the schema
        # promises, with everything zeroed and a reason on the side
        # channel via headers (not surfaced in the response_model).
        return {
            "received": len(records) if isinstance(records, list) else 0,
            "accepted": 0,
            "rejected": 0,
            "rejections": [{"index": -1, "errors": [{"msg": str(e)}]}],
            "trimmed": 0,
        }


@router.get("", response_model=list[ClientLogRead])
def list_client_logs(
    since: datetime | None = Query(None, description="ISO 8601 - filter to records with created_at >= since"),
    level: ClientLogLevel | None = Query(None),
    category: str | None = Query(None, max_length=64),
    route: str | None = Query(None, max_length=500),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Most-recent-first listing with optional filters. Defaults to the
    last 100 rows; bounded at 1000 so a typo doesn't dump 10k records."""
    return svc.list_logs(
        db,
        since=since,
        level=level,
        category=category,
        route=route,
        limit=limit,
    )
