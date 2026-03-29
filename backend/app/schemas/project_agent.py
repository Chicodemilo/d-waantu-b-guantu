# Path: app/schemas/project_agent.py
# File: project_agent.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for project-agent assignments
# Caller: app/routers/project_agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: ProjectAgentCreate, ProjectAgentRead
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectAgentCreate(BaseModel):
    project_id: int
    agent_id: int


class ProjectAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    agent_id: int
    assigned_at: datetime
