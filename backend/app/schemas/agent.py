# Path: app/schemas/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for agent CRUD
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: AgentCreate, AgentUpdate, AgentRead
# Last Modified: 2026-06-05

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    role: str
    api_key: str
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    role: str | None = None
    is_active: bool | None = None
    project_id: int | None = None


class AgentListRead(BaseModel):
    """Slim schema for list responses — excludes api_key."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    name: str
    description: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    name: str
    description: str | None
    role: str
    api_key: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --- /identify endpoint -----------------------------------------------------

class AgentIdentifyRequest(BaseModel):
    role: str
    name: str
    project_prefix: str


class InstructionPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: str
    title: str
    body: str


class AgentIdentifyResponse(BaseModel):
    agent_id: int
    name: str
    role: str
    project_id: int
    project_prefix: str
    # DWB-332: signal to the agent at startup whether this project is wired
    # to Jira. True when project.jira_base_url is set. Agents key Jira-side
    # decisions (dwb2jira invocations, jira_issue_key reads) on this.
    jira_enabled: bool
    memory_dir: str
    scratchpad_excerpt: str
    instructions: list[InstructionPayload]


# --- /spawn-prepare endpoint -----------------------------------------------

class SpawnPrepareRequest(BaseModel):
    role: str
    name: str
    project_prefix: str


class SpawnPrepareResponse(BaseModel):
    agent_id: int
    identity_prompt: str
    scratchpad_excerpt: str
    boundary_rules: str


# --- /{id}/session-complete endpoint ---------------------------------------

class SessionCompleteRequest(BaseModel):
    session_id: str
    summary: str
    lessons: list[str] | None = None
    tokens_used: int | None = None


class SessionCompleteResponse(BaseModel):
    agent_id: int
    session_id: str
    timestamp: str
    paths_written: list[str]
    bytes_written: int


# --- /{id}/marker endpoint --------------------------------------------------
# DWB-307: TL helper that writes the session marker file the hook resolver
# reads. Replaces hand-rolled JSON in TL prompts — backend already knows
# agent name/role/project so the call surface is just {session_id}.

class MarkerRequest(BaseModel):
    session_id: str


class MarkerResponse(BaseModel):
    agent_id: int
    session_id: str
    marker_path: str
    bytes_written: int
