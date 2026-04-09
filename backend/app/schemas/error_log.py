# Path: app/schemas/error_log.py
# File: error_log.py
# Created: 2026-04-09
# Purpose: Pydantic schemas for error log create/read
# Caller: app/routers/errors.py
# Callees: pydantic
# Data In: HTTP request bodies
# Data Out: Validated error log data
# Last Modified: 2026-04-09

from datetime import datetime

from pydantic import BaseModel


class ErrorLogCreate(BaseModel):
    project_id: int | None = None
    agent_id: int | None = None
    source: str = "frontend"
    endpoint: str | None = None
    error_type: str | None = None
    message: str
    stack_trace: str | None = None
    file_path: str | None = None
    function_name: str | None = None
    line_number: int | None = None
    status_code: int | None = None


class ErrorLogRead(BaseModel):
    id: int
    project_id: int | None
    agent_id: int | None
    source: str
    endpoint: str | None
    error_type: str | None
    message: str
    stack_trace: str | None
    file_path: str | None
    function_name: str | None
    line_number: int | None
    status_code: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
