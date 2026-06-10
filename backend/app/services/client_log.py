# Path: app/services/client_log.py
# File: client_log.py
# Created: 2026-06-10
# Purpose: Insert / query / retention-trim service for client_logs (DWB-371)
# Caller: app/routers/client_logs.py
# Callees: app/models/client_log.py
# Data In: db: Session, validated ClientLogCreate items, query filters
# Data Out: insert summary dict, list[ClientLog]
# Last Modified: 2026-06-10

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.client_log import ClientLog, ClientLogLevel
from app.schemas.client_log import ClientLogCreate

logger = logging.getLogger(__name__)


# Insert-time retention cap. Once total rows exceed CAP, drop the oldest
# (count - CAP) by id (== insertion order). Cap chosen at 10k per the
# ticket: ~1MB at a generous 100 bytes/row, comfortable in MySQL.
DEFAULT_RETENTION_CAP = 10_000


def insert_batch(
    db: Session,
    raw_records: list[dict[str, Any]],
    *,
    retention_cap: int = DEFAULT_RETENTION_CAP,
) -> dict[str, Any]:
    """Insert a batch of client-log records, dropping malformed ones
    individually.

    The ticket spec is explicit: a single bad record must not lose the
    whole batch. We re-validate each record against ClientLogCreate here
    so the lenient batch endpoint can pass through whatever the body
    contains; valid records land, invalid ones are reported back with
    their index + the pydantic error so the emitter can be repaired.

    Retention: after the batch lands, total rows are compared to the cap.
    Excess (oldest by id) is deleted in a single DELETE ... WHERE id IN
    (subselect) statement. Trim count is returned so the caller can
    surface it for telemetry.
    """
    accepted: list[ClientLog] = []
    rejections: list[dict[str, Any]] = []

    for idx, raw in enumerate(raw_records):
        try:
            record = ClientLogCreate.model_validate(raw)
        except ValidationError as e:
            rejections.append({
                "index": idx,
                "errors": e.errors(),
            })
            continue
        accepted.append(
            ClientLog(
                source=record.source,
                level=record.level,
                category=record.category,
                message=record.message,
                context_json=record.context_json,
                route=record.route,
                occurred_at=record.occurred_at,
            )
        )

    if accepted:
        db.add_all(accepted)
        db.commit()

    trimmed = _trim_to_cap(db, retention_cap)

    return {
        "received": len(raw_records),
        "accepted": len(accepted),
        "rejected": len(rejections),
        "rejections": rejections,
        "trimmed": trimmed,
    }


def _trim_to_cap(db: Session, cap: int) -> int:
    """Delete oldest rows (by id ASC == insertion order) so the table
    holds at most `cap` rows. Returns the number of rows deleted.

    Uses a subquery to pick exactly the surplus ids; a single DELETE
    statement on the table directly. Cap 0 is treated as unlimited.
    """
    if cap <= 0:
        return 0
    total = db.scalar(select(func.count()).select_from(ClientLog)) or 0
    surplus = total - cap
    if surplus <= 0:
        return 0
    # Pick the oldest `surplus` ids and delete them.
    oldest_ids = db.scalars(
        select(ClientLog.id).order_by(ClientLog.id.asc()).limit(surplus)
    ).all()
    if not oldest_ids:
        return 0
    db.execute(delete(ClientLog).where(ClientLog.id.in_(oldest_ids)))
    db.commit()
    return len(oldest_ids)


def list_logs(
    db: Session,
    *,
    since: datetime | None = None,
    level: ClientLogLevel | None = None,
    category: str | None = None,
    route: str | None = None,
    limit: int = 100,
) -> list[ClientLog]:
    """Most-recent-first listing with optional filters.

    Limit is bounded at the router level (1..1000); enforce a sane
    default here too in case a non-HTTP caller forgets.
    """
    if limit <= 0:
        limit = 1
    if limit > 1000:
        limit = 1000

    stmt = select(ClientLog)
    if since is not None:
        stmt = stmt.where(ClientLog.created_at >= since)
    if level is not None:
        stmt = stmt.where(ClientLog.level == level)
    if category is not None:
        stmt = stmt.where(ClientLog.category == category)
    if route is not None:
        stmt = stmt.where(ClientLog.route == route)
    stmt = stmt.order_by(ClientLog.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())
