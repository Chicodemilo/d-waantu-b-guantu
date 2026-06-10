# Path: app/routers/agents.py
# File: agents.py
# Created: 2026-03-29
# Purpose: Agent HTTP endpoints — CRUD + identify + consolidation ack
# Caller: app/main.py
# Callees: app/services/agent.py, app/services/agent_consolidation.py
# Data In: HTTP requests
# Data Out: JSON responses (AgentRead, AgentIdentifyResponse, AgentConsolidationAckRead)
# Last Modified: 2026-06-10

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.schemas.agent import (
    AgentCreate,
    AgentIdentifyRequest,
    AgentIdentifyResponse,
    AgentListRead,
    AgentRead,
    AgentUpdate,
    MarkerRequest,
    MarkerResponse,
    MemoryAppendRequest,
    MemoryAppendResponse,
    SessionCompleteRequest,
    SessionCompleteResponse,
    SpawnPrepareRequest,
    SpawnPrepareResponse,
)
from app.schemas.agent_consolidation_ack import (
    AgentConsolidationAckCreate,
    AgentConsolidationAckRead,
)
from app.services import agent as svc
from app.services import agent_consolidation as consolidation_svc

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentListRead])
def list_agents(
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_agents(db, role=role, is_active=is_active)


@router.post("/identify", response_model=AgentIdentifyResponse)
def identify_agent(data: AgentIdentifyRequest, db: Session = Depends(get_db)):
    """Resolve an agent identity from (role, name, project_prefix).

    404 if project or agent missing, 409 if multiple matches (post-DWB-287
    UNIQUE constraint makes this unreachable but kept for contract honesty).
    """
    try:
        return svc.identify_agent(
            db,
            role=data.role,
            name=data.name,
            project_prefix=data.project_prefix,
        )
    except svc.IdentifyError as e:
        status = 409 if e.code == "ambiguous" else 404
        raise HTTPException(status, e.detail)


@router.post("/spawn-prepare", response_model=SpawnPrepareResponse)
def spawn_prepare(data: SpawnPrepareRequest, db: Session = Depends(get_db)):
    """Return the markdown sections a TL injects into TeamCreate for a spawn.

    Wraps identify and adds an Identity / Recent Scratchpad / Boundary Rules
    block. boundary_rules pulls instructions scoped 'global' or scoped 'agent'
    for this agent (project-scope is excluded - those are environmental, not
    personal boundaries).

    DWB-341: auto-scaffolds the agent's memory dir (idempotent; preserves
    agent-owned files; never suffixes the dir name). 400 when the project
    has no repo_path set.
    """
    try:
        return svc.spawn_prepare_payload(
            db,
            role=data.role,
            name=data.name,
            project_prefix=data.project_prefix,
        )
    except svc.IdentifyError as e:
        if e.code == "repo_path_missing":
            status = 400
        elif e.code == "ambiguous":
            status = 409
        else:
            status = 404
        raise HTTPException(status, e.detail)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.post("", response_model=AgentRead, status_code=201)
def create_agent(data: AgentCreate, db: Session = Depends(get_db)):
    return svc.create_agent(db, data)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: int, data: AgentUpdate, db: Session = Depends(get_db)
):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return svc.update_agent(db, agent, data)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    svc.delete_agent(db, agent)


@router.post("/{agent_id}/session-complete", response_model=SessionCompleteResponse)
def session_complete(
    agent_id: int,
    data: SessionCompleteRequest,
    db: Session = Depends(get_db),
):
    """Append an ISO 8601 entry to the agent's scratchpad.md + recent_sessions.md.

    Creates the memory_dir on demand (precursor to DWB-293's full scaffolder).
    404 if agent missing or unscoped, 500 if the memory dir is unwritable.
    """
    try:
        return svc.record_session_complete(
            db,
            agent_id=agent_id,
            session_id=data.session_id,
            summary=data.summary,
            lessons=data.lessons,
            tokens_used=data.tokens_used,
        )
    except svc.SessionCompleteError as e:
        status = 500 if e.code == "memory_dir_unwritable" else 404
        raise HTTPException(status, e.detail)


@router.post(
    "/{agent_id}/consolidate-complete",
    response_model=AgentConsolidationAckRead,
    status_code=201,
)
def consolidate_complete(
    agent_id: int,
    data: AgentConsolidationAckCreate,
    db: Session = Depends(get_db),
):
    """Record that the agent has consolidated its owned files for the given sprint.

    400 if agent inactive, on a different project than the sprint, or owns
    over-ceiling files that lack per-file overrides (DWB-328).
    404 if agent or sprint missing. 409 if already acked.
    """
    ack, err, violations = consolidation_svc.create_ack(
        db,
        agent_id=agent_id,
        sprint_id=data.sprint_id,
        notes=data.notes,
        overrides=data.overrides,
    )
    if err == "agent_not_found":
        raise HTTPException(404, "Agent not found")
    if err == "sprint_not_found":
        raise HTTPException(404, "Sprint not found")
    if err == "agent_inactive":
        raise HTTPException(400, "Agent is not active")
    if err == "wrong_project":
        raise HTTPException(400, "Agent is not assigned to the sprint's project")
    if err == "over_ceiling_violations":
        raise HTTPException(400, {
            "error": "over_ceiling_files_must_be_trimmed_or_overridden",
            "violations": violations,
        })
    if err == "already_acked":
        raise HTTPException(409, "Agent has already acked consolidation for this sprint")
    return ack


@router.delete(
    "/{agent_id}/consolidate-complete/{sprint_id}",
    status_code=204,
)
def delete_consolidate_complete(
    agent_id: int,
    sprint_id: int,
    x_agent_id: int | None = Header(default=None, alias="X-Agent-ID"),
    db: Session = Depends(get_db),
):
    """TL-only: reject an existing ack so the agent must re-trim or re-justify.

    DWB-328: lets the team-lead invalidate a weak override. The caller's
    X-Agent-ID must resolve to a team-lead agent.

    401 if X-Agent-ID is missing or the caller doesn't exist.
    403 if the caller is not a team-lead.
    404 if no ack exists for (agent_id, sprint_id).
    """
    if x_agent_id is None:
        raise HTTPException(401, "X-Agent-ID header required")
    caller = db.get(Agent, x_agent_id)
    if not caller:
        raise HTTPException(401, "X-Agent-ID does not match a known agent")
    if caller.role != "team-lead":
        raise HTTPException(403, "Only team-lead agents may reject consolidation acks")

    deleted = consolidation_svc.delete_ack(db, agent_id=agent_id, sprint_id=sprint_id)
    if not deleted:
        raise HTTPException(404, "No ack found for this agent and sprint")
    return None


@router.post("/{agent_id}/marker", response_model=MarkerResponse, status_code=201)
def write_marker(
    agent_id: int,
    data: MarkerRequest,
    db: Session = Depends(get_db),
):
    """Write the session marker file the hook resolver reads (DWB-307).

    TL helper — replaces hand-rolling JSON. Backend knows agent
    name/role/project, so the request surface is just `{session_id}`.
    Writes to `<project.repo_path>/.claude/agents/active/<session_id>`.

    400 if session_id is empty or the agent has no project/repo_path.
    404 if the agent or its project is missing.
    500 if the marker dir/file cannot be written.
    """
    try:
        return svc.write_session_marker(
            db, agent_id=agent_id, session_id=data.session_id
        )
    except svc.MarkerError as e:
        if e.code in ("session_id_required", "agent_unscoped", "repo_path_missing"):
            status = 400
        elif e.code in ("marker_dir_unwritable", "marker_unwritable"):
            status = 500
        else:
            status = 404
        raise HTTPException(status, e.detail)


@router.post(
    "/{agent_id}/memory/append",
    response_model=MemoryAppendResponse,
    status_code=201,
)
def append_agent_memory(
    agent_id: int,
    data: MemoryAppendRequest,
    db: Session = Depends(get_db),
):
    """Server-side append to one of the agent's three memory files (DWB-358).

    Workaround for the Claude Code ink-renderer crash on permission
    prompts under .claude/: subagents can't Edit/Write their own memory
    files mid-session, but the FastAPI process has no permission dialog
    and can write on the agent's behalf.

    Body: { file: scratchpad|lessons|recent_sessions, content: str,
            session_id?: str }

    The server prepends an ISO 8601 UTC heading (matching the
    session-complete endpoint's heading format) and appends the result
    to the target file. Append-only; prior content is never overwritten.

    Returns 201 on successful append. Errors:
      - 400: invalid file enum, identity.md attempt, empty content,
             unscoped agent, project missing repo_path.
      - 404: agent or project not found.
      - 500: disk write failure (memory dir or file unwritable).
    """
    try:
        return svc.append_memory(
            db,
            agent_id=agent_id,
            file=data.file,
            content=data.content,
            session_id=data.session_id,
        )
    except svc.MemoryAppendError as e:
        if e.code in ("agent_not_found", "project_not_found"):
            status = 404
        elif e.code in (
            "file_protected",
            "invalid_file",
            "empty_content",
            "agent_unscoped",
            "repo_path_missing",
        ):
            status = 400
        elif e.code in ("memory_dir_unwritable", "memory_file_unwritable"):
            status = 500
        else:
            status = 500
        raise HTTPException(status, e.detail)


@router.post("/{agent_id}/scaffold-memory")
def scaffold_memory(agent_id: int, db: Session = Depends(get_db)):
    """Manually scaffold/refresh the agent's memory dir.

    Idempotent: identity.md is regenerated; scratchpad/lessons/recent_sessions
    are created only if missing (never overwritten). Returns the per-file
    disposition so callers can confirm what changed.
    """
    from app.services import agent_memory
    try:
        result = agent_memory.scaffold_agent_dir(db, agent_id)
    except agent_memory.ScaffoldError as e:
        status = 500 if e.code == "memory_dir_unwritable" else 404
        raise HTTPException(status, e.detail)
    return {
        "agent_id": result.agent_id,
        "memory_dir": result.memory_dir,
        "created": result.created,
        "preserved": result.preserved,
        "refreshed": result.refreshed,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
    }
