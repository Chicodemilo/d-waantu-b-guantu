# Path: app/schemas/status_history.py
# File: status_history.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for status history reads
# Caller: app/routers/tickets.py
# Callees: pydantic
# Data In: DB rows
# Data Out: StatusHistoryRead
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    old_status: str
    new_status: str
    changed_at: datetime
    changed_by_agent_id: int | None
