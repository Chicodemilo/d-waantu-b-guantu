# Path: app/services/server_log_handler.py
# File: server_log_handler.py
# Created: 2026-06-10
# Purpose: Custom logging.Handler that routes app-level records into the in-memory ring buffer (DWB-372)
# Caller: app/main.py (registered at startup)
# Callees: app/services/server_log_buffer.append
# Data In: logging.LogRecord
# Data Out: None (side-effects the ring buffer)
# Last Modified: 2026-06-10

"""Custom logging.Handler for the DWB-372 server-logs feed.

Goal: capture records emitted by app code (app.*, our services, our
routers) without drowning in uvicorn access-log noise or recursing on
SQLAlchemy's own engine/pool logger output.

Strategy: install on the root logger so we see everything, then drop
records whose `name` matches the noisy logger families. This is
opt-OUT rather than opt-IN because new app modules tend to use
`logging.getLogger(__name__)` (== `app.services.X`) and we don't want
them silently missing from the feed.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from app.services import server_log_buffer


# Logger names whose records are dropped. Match by prefix.
_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "uvicorn.access",
    "uvicorn.error",
    "uvicorn",
    "starlette",
    "sqlalchemy",
    "alembic",
    "asyncio",
    "fastapi",
    "watchfiles",
    "watchgod",
    "httpx",
    "httpcore",
    "urllib3",
)


def _is_excluded(name: str) -> bool:
    for prefix in _EXCLUDED_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            return True
    return False


def _format_exc(record: logging.LogRecord) -> str | None:
    if not record.exc_info:
        return None
    try:
        return "".join(traceback.format_exception(*record.exc_info))
    except Exception:
        return None


def _extract_extras(record: logging.LogRecord) -> dict[str, Any] | None:
    """Pull structured extras off a LogRecord.

    `logger.info("msg", extra={"foo": 1})` lands as attributes on the
    record. Filter to keys not in the standard LogRecord shape so we
    only persist user-supplied context.
    """
    standard = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "asctime", "taskName",
    }
    extras = {
        k: v for k, v in record.__dict__.items()
        if k not in standard and not k.startswith("_")
    }
    # Coerce non-JSON-safe values to repr so the buffer stays
    # serializable when the router returns it.
    safe: dict[str, Any] = {}
    for k, v in extras.items():
        try:
            # crude JSON safety check
            import json
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = repr(v)
    return safe or None


class RingBufferHandler(logging.Handler):
    """logging.Handler that converts records into ring-buffer entries.

    Never raises out: handler exceptions kill the logging call site, and
    the whole point here is to be a silent debug surface, not a new
    failure mode.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _is_excluded(record.name):
                return
            entry = {
                "logger_name": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
                "pathname": record.pathname,
                "lineno": record.lineno,
                "func_name": record.funcName,
                "created_at": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ),
                "exc_info": _format_exc(record),
                "context_json": _extract_extras(record),
            }
            server_log_buffer.append(entry)
        except Exception:
            # Silent on purpose - see class docstring.
            pass


def install(level: int = logging.INFO) -> RingBufferHandler:
    """Attach the handler to the root logger. Idempotent: removes any
    previously-installed RingBufferHandler before adding a fresh one so
    `uvicorn --reload` doesn't stack handlers and double-log every line.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RingBufferHandler):
            root.removeHandler(h)
    handler = RingBufferHandler(level=level)
    root.addHandler(handler)
    # Ensure the root level lets INFO through. We don't lower DEBUG by
    # default because some libs (httpx, etc.) flood debug; our handler
    # already excludes them but the root threshold gate is cheaper.
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handler
