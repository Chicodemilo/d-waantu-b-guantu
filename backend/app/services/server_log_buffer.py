# Path: app/services/server_log_buffer.py
# File: server_log_buffer.py
# Created: 2026-06-10
# Purpose: In-process bounded ring buffer for app-level log records, queried via /api/server-logs (DWB-372)
# Caller: app/services/server_log_handler.py (writes), app/routers/server_logs.py (reads)
# Callees: collections.deque, threading.Lock
# Data In: log record dicts from the custom logging.Handler
# Data Out: filtered list of record dicts for GET /api/server-logs
# Last Modified: 2026-06-10

"""In-memory ring buffer for backend log capture.

Trade-off chosen here (DWB-372): a thread-safe deque + lock is the
simplest path that solves the actual use case (TL queries the API
moments after seeing a symptom). It does NOT survive `uvicorn --reload`
- the buffer is module-level state and dies with the worker. The
ticket explicitly accepts this as long as the limitation is documented,
and the use case (debug-in-the-moment, no code edit between trigger
and query) tolerates it.

If persistence across reload becomes load-bearing later (e.g. CI is
piping prod logs through this), the swap-in is: switch the deque for a
table-backed store with the same append/query surface. The router and
handler don't need to change.
"""

import threading
from collections import deque
from datetime import datetime
from typing import Any


# Bounded ring. 2000 records ~ 200KB at 100 bytes each, comfortable.
# Override via configure_buffer() during tests so retention can be
# exercised without filling 2000 entries.
_DEFAULT_MAX = 2000

_buffer: deque[dict[str, Any]] = deque(maxlen=_DEFAULT_MAX)
_lock = threading.Lock()


def configure_buffer(maxlen: int) -> None:
    """Reset the buffer with a new max length. Test-only seam - the
    production startup path leaves the deque at its default size."""
    global _buffer
    with _lock:
        _buffer = deque(maxlen=maxlen)


def append(record: dict[str, Any]) -> None:
    """Push a single record into the buffer. Atomic under the lock so a
    concurrent query can iterate a stable snapshot."""
    with _lock:
        _buffer.append(record)


def clear() -> None:
    """Drop every buffered record. Used by tests and by an explicit TL
    reset endpoint if one is ever added."""
    with _lock:
        _buffer.clear()


def size() -> int:
    with _lock:
        return len(_buffer)


def maxlen() -> int | None:
    with _lock:
        return _buffer.maxlen


def query(
    *,
    since: datetime | None = None,
    level: str | None = None,
    logger_name: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return matching records, most-recent first.

    Filtering is in-Python because the buffer is small. Snapshot once
    under the lock, then filter without holding it so a long query can't
    block the logging path. Limit is bounded at the router (1..1000).
    """
    if limit <= 0:
        limit = 1
    if limit > 1000:
        limit = 1000

    with _lock:
        snapshot = list(_buffer)

    # Most-recent first.
    snapshot.reverse()

    out: list[dict[str, Any]] = []
    needle = q.lower() if q else None
    level_upper = level.upper() if level else None
    for rec in snapshot:
        if since is not None and rec["created_at"] < since:
            continue
        if level_upper is not None and rec["level"] != level_upper:
            continue
        if logger_name is not None and rec["logger_name"] != logger_name:
            continue
        if needle is not None and needle not in rec["message"].lower():
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out
