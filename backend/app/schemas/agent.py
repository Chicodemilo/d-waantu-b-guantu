# Path: app/schemas/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for agent CRUD
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: AgentCreate, AgentUpdate, AgentRead
# Last Modified: 2026-09-14 (DWB-517 memory_full; DWB-518 MemoryCondenseRequest/Response)

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
    # DWB-466: api_key is intentionally OMITTED. GET /api/agents/{id} (and the
    # POST-create echo) previously returned the key in cleartext. The key is a
    # secret; callers supply it on create and resolve agents by id/name
    # thereafter, so there is never a reason to read it back. AgentListRead
    # already excluded it; this brings the detail/create response in line.
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    name: str
    description: str | None
    role: str
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
    # DWB-352: condensed inline memory-usage rules from
    # app.config.memory_rules.MEMORY_USAGE_RULES (single source of truth,
    # <=600 chars). Surfaced so every spawn delivers the rules regardless
    # of whether the worker opens the full playbook.
    memory_usage_rules: str


# --- /spawn-prepare endpoint -----------------------------------------------

class SpawnPrepareRequest(BaseModel):
    role: str
    name: str
    project_prefix: str


class RelevantLesson(BaseModel):
    """DWB-524: a pointer-only lesson relevant to the spawning agent's tickets.

    Carries WHERE the lesson lives (source agent + memory entry heading/date),
    never the lesson text - the TL pastes these alongside memory_full."""

    tag: str
    weight: int
    source_agent: str | None = None
    memory_ref: str
    entry_heading: str | None = None
    date: str | None = None


class SpawnPrepareResponse(BaseModel):
    agent_id: int
    identity_prompt: str
    scratchpad_excerpt: str
    # DWB-517: the agent's FULL memory.md verbatim (empty string when none yet).
    # The excerpt above is kept for compat; this is the whole file so the TL
    # injects the agent's complete memory into the spawn prompt with no read.
    memory_full: str
    # DWB-524: top-N memory-domain lessons from OTHER agents matched to this
    # agent's assigned/queued tickets. Empty list when the corpus is empty.
    relevant_lessons: list[RelevantLesson] = []
    boundary_rules: str
    # DWB-341: absolute memory_dir path. The endpoint guarantees this dir +
    # its core files (identity.md, scratchpad.md, lessons.md,
    # recent_sessions.md) exist on return; agents reading the spawn payload
    # can rely on the path being live without a separate scaffold call.
    memory_dir: str
    # DWB-352: same constant the identify endpoint surfaces, so a TL building
    # a spawn prompt can drop the rules inline.
    memory_usage_rules: str


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


# --- /{id}/memory/append (DWB-358) ------------------------------------------


# Literal type pins the file enum at the schema layer; FastAPI returns 422
# automatically on a value outside the whitelist. The service layer also
# defends against this (defense in depth) and returns 400 if the schema is
# bypassed (e.g. direct service call from another module).
from typing import Literal


class MemoryAppendRequest(BaseModel):
    """POST /api/agents/{agent_id}/memory/append body (DWB-358).

    file: which of the three agent-owned memory files to append to.
          identity.md is system-generated and not accepted.
    content: the body of the appended block. The server prepends an ISO
             8601 UTC heading; the caller does NOT include the heading.
             Empty / whitespace-only content is refused at 400.
    session_id: optional; appears in the heading as "## <ts> - session <id>"
                so a human reading the file can tie the entry to a CC
                session. Omit when the append isn't session-scoped.
    """

    file: Literal["memory"]
    content: str
    session_id: str | None = None


class RedemptionVerdict(BaseModel):
    """DWB-537: outcome of the stick-redemption check run after an append.
    granted=True only when a `redeem:<score_event_id>` token passed every
    eligibility rule and the half-back score_event was written. reason always
    explains the verdict (including the plain "no redeem token" case)."""

    granted: bool
    reason: str


class MemoryAppendResponse(BaseModel):
    agent_id: int
    file: str
    path: str
    timestamp: str
    bytes_written: int
    redemption: RedemptionVerdict


class MemoryReadResponse(BaseModel):
    """GET /api/agents/{agent_id}/memory (DWB-532).

    content: memory.md verbatim.
    est_tokens: the SERVER estimate (config.token_budget.estimate_tokens), the
                same number append / session-complete / condense gate on.
    ceiling: the memory_main ceiling those writes enforce.
    headroom: ceiling - est_tokens; negative when the file is already over.
    """

    content: str
    est_tokens: int
    ceiling: int
    headroom: int


class MemoryCompactRequest(BaseModel):
    """POST /api/agents/{agent_id}/memory/compact body.

    Compaction is a full-file REPLACE (not an append): the agent submits the
    leaner, rewritten content for one memory file and the server overwrites it.

    file: which memory file to compact. identity.md is system-generated and
          not accepted.
    content: the COMPLETE compacted file contents (the server writes it
             verbatim, no heading is prepended). Refused if empty or if its
             estimated token count still exceeds the file's ceiling.
    """

    file: Literal["memory"]
    content: str


class MemoryCompactResponse(BaseModel):
    agent_id: int
    file: str
    path: str
    tokens: int
    ceiling: int
    bytes_written: int


class MemoryCondenseRequest(BaseModel):
    """POST /api/agents/{agent_id}/memory/condense body (DWB-518).

    The sanctioned memory rewrite: a full-file REPLACE of memory.md. The server
    stamps an ISO ``## <timestamp> - condensed`` heading and writes the result
    only if it is within the file's token ceiling (refused otherwise; nothing is
    silently dropped). identity.md is system-generated and not accepted.

    content: the COMPLETE rewritten memory.md body (the server prepends the
             condensed-at heading). Refused if empty or if the stamped result
             still exceeds the ceiling.
    """

    file: Literal["memory"]
    content: str


class MemoryCondenseResponse(BaseModel):
    agent_id: int
    file: str
    path: str
    tokens: int
    ceiling: int
    bytes_written: int
    # DWB-518: ISO 8601 UTC timestamp the server stamped into the condensed-at
    # heading it prepended to the rewritten file.
    condensed_at: str
