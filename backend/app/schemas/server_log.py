# Path: app/schemas/server_log.py
# File: server_log.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for the in-memory server-log feed (DWB-372)
# Caller: app/routers/server_logs.py
# Callees: pydantic
# Data In: ring-buffer dict entries
# Data Out: ServerLogRead, ServerLogStats
# Last Modified: 2026-06-10

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ServerLogRead(BaseModel):
    logger_name: str
    level: str
    message: str
    pathname: str | None = None
    lineno: int | None = None
    func_name: str | None = None
    created_at: datetime
    exc_info: str | None = None
    context_json: dict[str, Any] | None = None


class ServerLogStats(BaseModel):
    size: int
    maxlen: int | None
