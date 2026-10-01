# Path: app/routers/agents.py
# File: agents.py
# Created: 2026-03-29
# Purpose: Agent HTTP endpoints — CRUD + identify + consolidation ack
# Caller: app/main.py
# Callees: app/services/agent.py, app/services/agent_consolidation.py, app/services/raw_memory.py, app/services/memory_score.py
# Data In: HTTP requests
# Data Out: JSON responses (AgentRead, AgentIdentifyResponse, AgentConsolidationAckRead)
# Last Modified: 2026-09-30 (DWB-603/Miles ruling: GET /{id}/memory/scored is
#                pure again - firing moved to memory_consult.consult_scars)

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
    MemoryCompactRequest,
    MemoryCompactResponse,
    MemoryCondenseRequest,
    MemoryCondenseResponse,
    MemoryReadResponse,
    SessionCompleteRequest,
    SessionCompleteResponse,
    SpawnPrepareRequest,
    SpawnPrepareResponse,
)
from app.schemas.agent_consolidation_ack import (
    AgentConsolidationAckCreate,
    AgentConsolidationAckRead,
)
from app.schemas.agent_memory import RawMemoryCreate, RawMemoryResponse
from app.schemas.memory_score import ScoredMemoryResponse
from app.services import agent as svc
from app.services import agent_consolidation as consolidation_svc
from app.services import memory_mode as memory_mode_svc
from app.services import memory_score as memory_score_svc
from app.services import raw_memory as raw_memory_svc

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
    """Append an ISO 8601 entry to the agent's memory.md.

    Creates the memory_dir on demand (precursor to DWB-293's full scaffolder).
    404 if agent missing or unscoped, 500 if the memory dir is unwritable.

    DWB-582: `session_id` is OPTIONAL (the server resolves it from the agent's
    most recent hook_session) and `lessons` takes a bare string as well as a
    list. Both were required in shapes a subagent could not reliably produce,
    so every worker fell back to the append path and the primary path's
    failure was invisible because the fallback always worked.
    """
    # DWB-589: spec section 7 hard rule 1 - stock memory is not written on a
    # human_memory project. Runs BEFORE the write so nothing lands, and names
    # the endpoint to use instead (a refusal that cannot say what to do instead
    # drops the lesson the agent is holding right now).
    try:
        memory_mode_svc.assert_stock_write_allowed(db, agent_id, "session-complete")
    except memory_mode_svc.StockMemorySealed as e:
        raise HTTPException(409, e.detail)
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
        if e.code == "memory_dir_unwritable":
            status = 500
        elif e.code == "over_ceiling":
            # DWB-518: over_ceiling is an actionable refusal (condense first).
            status = 400
        else:
            status = 404
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


@router.get("/{agent_id}/memory", response_model=MemoryReadResponse)
def read_agent_memory(agent_id: int, db: Session = Depends(get_db)):
    """DWB-532: memory.md content plus the server's token estimate.

    Returns {content, est_tokens, ceiling, headroom} using the shared
    estimator in config/token_budget.py, so a condense can be sized against
    the real gate number instead of trial and error. Errors:
      - 404: agent / project not found, or the agent has no memory.md yet
             (detail names the agent).
      - 400: unscoped agent, project missing repo_path.
      - 500: file exists but is unreadable.
    """
    try:
        return svc.read_memory(db, agent_id=agent_id)
    except svc.MemoryReadError as e:
        if e.code in ("agent_not_found", "project_not_found", "memory_missing"):
            status = 404
        elif e.code in ("agent_unscoped", "repo_path_missing"):
            status = 400
        else:
            status = 500
        raise HTTPException(status, e.detail)


@router.get("/{agent_id}/memory/scored", response_model=ScoredMemoryResponse)
def read_scored_memory(agent_id: int, db: Session = Depends(get_db)):
    """DWB-585: every memory for this agent with its DERIVED score and band,
    plus the demote / evict / promote candidate lists.

    THE LISTS ARE PRODUCED HERE, BY CODE, and that is the requirement rather
    than an implementation detail. Miles's ruling: the consolidation math is
    programmatic. The model does the SCAN and the rewrite; it does not decide
    what to demote. A playbook paragraph saying "consider demoting things" is
    the version this endpoint replaces, so nothing that reads this may fall
    back to prose when the response is empty.

    `computed` separates "nothing to do" from "nothing ran": three empty lists
    are the right answer for a tidy agent AND for a project that never turned
    human_memory on, and those are opposite facts.

    NOTE FOR DWB-589, which refuses stock-memory operations when human_memory
    is on: this route sits under the same `/memory` path as the stock file
    endpoints but is NOT one of them. The refusal there has to be per-route. A
    prefix-wide block would disable the endpoint that makes human_memory mode
    work, in exactly the mode that needs it.

    DWB-603/MILES-RULING (2026-09-30): THIS GET HAS NO SIDE EFFECT, AND MUST
    NEVER GROW ONE. An earlier version of DWB-603 fired `fired_count` on every
    scar-family row returned here, reasoning this was the only "reached for"
    signal the store had. Miles ruled that reasoning wrong: this route is
    called from spawn/SessionStart injection (`memory_context.py`) and from
    DWB-613's dashboard panel, and neither is a deliberate consultation -
    "deploy doesn't count as a read... outside of normal startup." A read
    fires only when it is a genuine question ("have I made this error
    before?"), which this endpoint, by construction, never asks - it always
    returns everything, which is exactly why it must stay pure. The real
    consultation path is `memory_consult.consult_scars` (DWB-603 cont'd).

    Errors:
      - 404: agent not found.
    """
    try:
        return memory_score_svc.scored_memory(db, agent_id=agent_id)
    except memory_score_svc.MemoryScoreError as e:
        raise HTTPException(404, e.detail)


@router.post(
    "/{agent_id}/memory/append",
    response_model=MemoryAppendResponse,
    status_code=201,
)
def append_agent_memory(
    agent_id: int,
    data: MemoryAppendRequest,
    db: Session = Depends(get_db),
    x_agent_id: int | None = Header(default=None, alias="X-Agent-ID"),
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

    DWB-537: if the body carries a `redeem:<score_event_id>` token the
    stick-redemption chain runs AFTER the write; X-Agent-ID must equal the
    path agent_id for a grant. The verdict rides the response as
    `redemption: {granted, reason}` and never changes the status code.

    Returns 201 on successful append. Errors:
      - 400: invalid file enum, identity.md attempt, empty content,
             unscoped agent, project missing repo_path.
      - 404: agent or project not found.
      - 500: disk write failure (memory dir or file unwritable).
    """
    # DWB-589: spec section 7 hard rule 1 - stock memory is not written on a
    # human_memory project. Runs BEFORE the write so nothing lands, and names
    # the endpoint to use instead (a refusal that cannot say what to do instead
    # drops the lesson the agent is holding right now).
    try:
        memory_mode_svc.assert_stock_write_allowed(db, agent_id, "memory/append")
    except memory_mode_svc.StockMemorySealed as e:
        raise HTTPException(409, e.detail)
    try:
        return svc.append_memory(
            db,
            agent_id=agent_id,
            file=data.file,
            content=data.content,
            session_id=data.session_id,
            caller_agent_id=x_agent_id,
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
            # DWB-518: append refused because it would exceed the ceiling. The
            # detail names tokens + ceiling and tells the agent to condense.
            "over_ceiling",
        ):
            status = 400
        elif e.code in ("memory_dir_unwritable", "memory_file_unwritable"):
            status = 500
        else:
            status = 500
        raise HTTPException(status, e.detail)


@router.post(
    "/{agent_id}/memory/compact",
    response_model=MemoryCompactResponse,
    status_code=200,
)
def compact_agent_memory(
    agent_id: int,
    data: MemoryCompactRequest,
    db: Session = Depends(get_db),
):
    """Compact (full-file replace) the agent's memory.md, verbatim.

    The agent submits a leaner rewrite of the whole file; the server
    overwrites it ONLY if the result is within the file's token ceiling. A
    result still over ceiling is refused (DWB-518: 400, was a silent trim under
    DWB-401) - that refusal is the hard gate (it cannot be satisfied by a no-op,
    and empty content is rejected so the file cannot be blanked to pass). No
    heading is stamped; see the condense endpoint for the heading-stamped rewrite.

    Errors: 404 agent/project missing; 400 still over ceiling / bad file /
    empty content / unscoped agent / no repo_path; 500 disk write failure.
    """
    # DWB-589: spec section 7 hard rule 1 - stock memory is not written on a
    # human_memory project. Runs BEFORE the write so nothing lands, and names
    # the endpoint to use instead (a refusal that cannot say what to do instead
    # drops the lesson the agent is holding right now).
    try:
        memory_mode_svc.assert_stock_write_allowed(db, agent_id, "memory/compact")
    except memory_mode_svc.StockMemorySealed as e:
        raise HTTPException(409, e.detail)
    try:
        return svc.compact_memory(
            db, agent_id=agent_id, file=data.file, content=data.content
        )
    except svc.MemoryCompactError as e:
        if e.code in ("agent_not_found", "project_not_found"):
            status = 404
        elif e.code in (
            "still_over_ceiling",
            "file_protected",
            "invalid_file",
            "empty_content",
            "agent_unscoped",
            "repo_path_missing",
        ):
            # DWB-518: still_over_ceiling is now an actionable 400 (trim more),
            # consistent with the append/session-complete/condense refusals.
            status = 400
        else:
            status = 500
        raise HTTPException(status, e.detail)


@router.post(
    "/{agent_id}/memory/condense",
    response_model=MemoryCondenseResponse,
    status_code=200,
)
def condense_agent_memory(
    agent_id: int,
    data: MemoryCondenseRequest,
    db: Session = Depends(get_db),
):
    """DWB-518: condense (full-file replace) the agent's memory.md.

    The sanctioned rewrite path the over-ceiling append/session-complete refusal
    points at. The agent submits the leaner full-file content; the server stamps
    an ISO ``## <timestamp> - condensed`` heading, validates the result is under
    the ceiling, and replaces the file. A submission still over ceiling is
    refused 400 (trim more and resubmit). identity.md is refused; empty content
    is refused so the file cannot be blanked to pass.

    Errors: 404 agent/project missing; 400 still over ceiling / bad file /
    empty content / unscoped agent / no repo_path; 500 disk write failure.
    """
    # DWB-589: spec section 7 hard rule 1 - stock memory is not written on a
    # human_memory project. Runs BEFORE the write so nothing lands, and names
    # the endpoint to use instead (a refusal that cannot say what to do instead
    # drops the lesson the agent is holding right now).
    try:
        memory_mode_svc.assert_stock_write_allowed(db, agent_id, "memory/condense")
    except memory_mode_svc.StockMemorySealed as e:
        raise HTTPException(409, e.detail)
    try:
        return svc.condense_memory(
            db, agent_id=agent_id, file=data.file, content=data.content
        )
    except svc.MemoryCondenseError as e:
        if e.code in ("agent_not_found", "project_not_found"):
            status = 404
        elif e.code in (
            "still_over_ceiling",
            "file_protected",
            "invalid_file",
            "empty_content",
            "agent_unscoped",
            "repo_path_missing",
        ):
            status = 400
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


@router.post(
    "/{agent_id}/memories",
    response_model=RawMemoryResponse,
    status_code=201,
)
def append_raw_memory(
    agent_id: int,
    data: RawMemoryCreate,
    db: Session = Depends(get_db),
):
    """Append one RAW, untiered memory row for this agent (DWB-586).

    Spec docs/human_memory_spec.md section 4: a session appends raw and
    unsorted, because tiering in the moment rubber-stamps in-the-moment
    salience, which is the judgment consolidation exists to make.

    Body: { body, context_key?, cost?, caught_by?, surprised?, tier? }

    cost / caught_by / surprised are spec section 4's moment-tags, and they live
    on the MEMORY rather than the journal (section 6 as amended 2026-09-29):
    all three are read against memories, and the SCAN gates on `cost`.

    `tier` is refused, always, with the reason. Section 7 hard rule 5 puts CORE
    behind a human ruling or logged cross-context evidence, and section 4 puts
    every other tier behind consolidation. The field is accepted by the schema
    only so the attempt can be answered rather than silently written as `raw`.

    A write with NO open DWB session is ACCEPTED, not refused: losing the lesson
    because the bookkeeping was not ready is the worse outcome. The response
    says which happened in `session_state` (`open` | `none_open`) alongside
    `created_session_id`, because a null id alone cannot distinguish "nothing
    was open" from "nobody looked".

    Stamps agents.last_memory_write_at like every other memory write, so the
    DWB-519 write-on-close gate sees a human_memory agent's participation with
    no mode-aware branch (DWB-589 verifies rather than rebuilds this).

    Returns 201. Errors:
      - 400: empty body, any tier at all, unscoped agent.
      - 404: agent or project not found.
    """
    try:
        return raw_memory_svc.append_raw_memory(
            db,
            agent_id=agent_id,
            body=data.body,
            context_key=data.context_key,
            cost=data.cost,
            caught_by=data.caught_by,
            surprised=data.surprised,
            tier=data.tier,
        )
    except raw_memory_svc.RawMemoryWriteError as e:
        if e.code in ("agent_not_found", "project_not_found"):
            status = 404
        else:
            status = 400
        raise HTTPException(status, e.detail)
