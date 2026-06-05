# Path: app/schemas/project_agent.py
# File: project_agent.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for project-agent assignments + team listing
# Caller: app/routers/project_agents.py, app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: ProjectAgentCreate, ProjectAgentRead, ProjectTeamMember, ProjectTeamRead
# Last Modified: 2026-06-05

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


# DWB-313 — single-roundtrip team listing for GET /api/projects/{id}/team
class ProjectTeamMember(BaseModel):
    agent_id: int
    name: str
    role: str
    is_active: bool
    assigned_at: datetime


class ProjectTeamRead(BaseModel):
    project_id: int
    project_prefix: str
    agents: list[ProjectTeamMember]
