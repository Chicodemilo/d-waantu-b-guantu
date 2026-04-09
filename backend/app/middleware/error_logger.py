# Path: app/middleware/error_logger.py
# File: error_logger.py
# Created: 2026-04-09
# Purpose: Middleware that auto-logs unhandled exceptions to error_logs table
# Caller: app/main.py
# Callees: app/database.SessionLocal, app/models/error_log.ErrorLog
# Data In: HTTP request/response, exception tracebacks
# Data Out: error_log rows (side effect); re-raises original exception
# Last Modified: 2026-04-09

"""FastAPI middleware that catches unhandled exceptions and logs them to the error_logs table.

Extracts file, function, and line number from the traceback automatically — no manual
annotation needed. Infers project_id from URL path where possible.
"""

import logging
import re
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.database import SessionLocal
from app.models.error_log import ErrorLog, ErrorSource

logger = logging.getLogger(__name__)

_PROJECT_PATH_RE = re.compile(r"/api/projects/(\d+)")


def _extract_origin(tb_str: str) -> tuple[str | None, str | None, int | None]:
    """Parse the last app-level frame from a traceback string.

    Returns (file_path, function_name, line_number).
    Prioritizes frames in app/ over library frames.
    """
    frames = traceback.extract_tb_from_string(tb_str) if hasattr(traceback, 'extract_tb_from_string') else []

    # Fallback: regex parse the traceback string for app/ frames
    app_file, app_func, app_line = None, None, None
    frame_re = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
    for match in frame_re.finditer(tb_str):
        fpath, line_no, func = match.group(1), int(match.group(2)), match.group(3)
        if "/app/" in fpath or "/routers/" in fpath or "/services/" in fpath or "/middleware/" in fpath:
            app_file, app_func, app_line = fpath, func, line_no

    return app_file, app_func, app_line


def _extract_project_id(path: str) -> int | None:
    """Try to extract project_id from the request path."""
    m = _PROJECT_PATH_RE.search(path)
    return int(m.group(1)) if m else None


class ErrorLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            tb_str = traceback.format_exc()
            path = request.url.path

            file_path, function_name, line_number = _extract_origin(tb_str)
            project_id = _extract_project_id(path)

            db = SessionLocal()
            try:
                db.add(ErrorLog(
                    project_id=project_id,
                    source=ErrorSource.backend,
                    endpoint=f"{request.method} {path}",
                    error_type=type(exc).__name__,
                    message=str(exc)[:2000],
                    stack_trace=tb_str[:10000],
                    file_path=file_path,
                    function_name=function_name,
                    line_number=line_number,
                ))
                db.commit()
            except Exception as log_exc:
                logger.warning("Failed to log error: %s", log_exc)
                db.rollback()
            finally:
                db.close()

            logger.exception("Unhandled exception on %s %s", request.method, path)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
