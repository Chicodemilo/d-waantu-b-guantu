# Path: app/schemas/agent_consolidation_ack.py
# File: agent_consolidation_ack.py
# Created: 2026-06-04
# Purpose: Pydantic schemas for agent consolidation acks
# Caller: app/routers/agents.py, app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: AgentConsolidationAckCreate, AgentConsolidationAckRead
# Last Modified: 2026-06-05

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentConsolidationAckCreate(BaseModel):
    sprint_id: int
    notes: str | None = None
    # DWB-328: per-file override map {filename: reason}. Required when the
    # agent's owned files include over-ceiling entries; reason must be a
    # non-empty string.
    overrides: dict[str, str] | None = None


class AgentConsolidationAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    sprint_id: int
    acked_at: datetime
    notes: str | None
    overrides: dict[str, str] | None = None
