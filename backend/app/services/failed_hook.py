# Path: app/services/failed_hook.py
# File: failed_hook.py
# Created: 2026-06-03
# Purpose: Record a FailedHook row when a hook endpoint can't process its payload
# Caller: app/routers/hooks.py (and any other hook receiver added later)
# Callees: app/database.SessionLocal, app/models/failed_hook.FailedHook
# Data In: hook_event name, status_code, raw_payload, error_message
# Data Out: None
# Last Modified: 2026-06-03

import logging

from app import database
from app.models.failed_hook import FailedHook

logger = logging.getLogger(__name__)

_PAYLOAD_SNIPPET_LIMIT = 2000


def log_failed_hook(
    *,
    hook_event: str | None,
    status_code: int | None,
    raw_payload: str | dict | bytes | None,
    error: str,
) -> None:
    """Insert a FailedHook row on a fresh session.

    Uses a dedicated session so a poisoned request session can't block the
    write. Swallows any logging-side exception — the goal is to stop *silent*
    hook failures, not to add a new failure mode.
    """
    snippet: str | None = None
    if raw_payload is not None:
        if isinstance(raw_payload, bytes):
            try:
                raw_payload = raw_payload.decode("utf-8", errors="replace")
            except Exception:
                raw_payload = repr(raw_payload)
        snippet = str(raw_payload)[:_PAYLOAD_SNIPPET_LIMIT]

    db = database.SessionLocal()
    try:
        row = FailedHook(
            hook_event=hook_event,
            status_code=status_code,
            payload_snippet=snippet,
            error=error[:65000],
        )
        db.add(row)
        db.commit()
    except Exception:
        logger.exception("failed_hook logger could not persist row")
        db.rollback()
    finally:
        db.close()
