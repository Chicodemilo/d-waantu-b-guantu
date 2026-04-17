# Path: app/services/hook_tracking.py
# File: hook_tracking.py
# Created: 2026-04-09
# Purpose: Hook-based tracking service — handles Claude Code lifecycle hook events
# Caller: app/routers/hooks.py
# Callees: app/models/hook_session.py, app/services/tracking.py, app/models/alert.py
# Data In: db: Session, hook event JSON from Claude Code hooks
# Data Out: HookSession records, tracking_log events via tracking.py
# Last Modified: 2026-04-09

"""Service layer for passive hook-based time and token tracking.

Handles SessionStart, SessionEnd, and SubagentStop lifecycle hooks from
Claude Code. Creates hook_session records for state management and delegates
to tracking.py for authoritative event logging.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.ticket import Ticket, TicketStatus
from app.services import tracking

logger = logging.getLogger(__name__)

# Roles treated as overhead (not ticket work)
OVERHEAD_ROLES = {"team-lead", "pm"}


def handle_session_start(db: Session, hook_data: dict) -> HookSession:
    """Handle a SessionStart hook event.

    1. Extract session_id, transcript_path, cwd
    2. Idempotent — return existing if session_id already exists
    3. Resolve project from cwd
    4. Quick-read transcript for agentName
    5. Resolve agent, determine session type
    6. Create HookSession(status=active)
    7. Log start via tracking.py
    """
    session_id = hook_data.get("session_id", "")
    if not session_id:
        raise ValueError("session_id is required")

    # Idempotent: return existing session
    existing = db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )
    if existing:
        return existing

    transcript_path = hook_data.get("transcript_path")
    cwd = hook_data.get("cwd", "")

    # Resolve project from cwd
    project = _resolve_project(db, cwd)
    if not project:
        raise ValueError(f"No project found for cwd: {cwd}")

    # Try to get agent name from hook data or transcript
    agent_name = hook_data.get("agent_name")
    if not agent_name and transcript_path:
        agent_name = _read_agent_name_from_transcript(transcript_path)

    # Resolve agent and session type
    agent = resolve_agent(db, agent_name, project.id) if agent_name else None

    # Main CLI session (no agent name) → attribute as TL overhead
    if not agent:
        agent = _fallback_tl_agent(db, project.id)
        if agent:
            agent_name = agent.role

    session_type = _determine_session_type(agent)

    # Resolve work context for workers
    ticket = None
    sprint_id = None
    if agent and agent.role not in OVERHEAD_ROLES:
        ticket = _resolve_ticket(db, agent, project.id)
        if ticket:
            sprint_id = ticket.sprint_id

    session = HookSession(
        session_id=session_id,
        transcript_path=transcript_path,
        agent_id=agent.id if agent else None,
        project_id=project.id,
        ticket_id=ticket.id if ticket else None,
        sprint_id=sprint_id,
        status=HookSessionStatus.active,
        session_type=session_type,
        agent_name=agent_name,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Log start event through tracking.py
    if agent:
        if session_type in (HookSessionType.teammate, HookSessionType.subagent) and ticket:
            tracking.log_start(db, ticket.id, agent.id)
        elif session_type == HookSessionType.main or agent.role in OVERHEAD_ROLES:
            tracking.log_overhead_start(db, project.id, agent.id)

    return session


def handle_session_end(db: Session, hook_data: dict) -> HookSession:
    """Handle a SessionEnd or SubagentStop hook event.

    SubagentStop events are detected and routed to _handle_subagent_stop()
    which creates a separate HookSession keyed on agent_id, NOT session_id.
    This avoids colliding with the parent TL session.

    SessionEnd events follow the existing flow unchanged.
    """
    # Detect SubagentStop — route to dedicated handler
    if hook_data.get("hook_event_name") == "SubagentStop" or (
        hook_data.get("agent_type") and hook_data.get("agent_id")
    ):
        return _handle_subagent_stop(db, hook_data)

    session_id = hook_data.get("session_id", "")
    if not session_id:
        raise ValueError("session_id is required")

    hook_event = hook_data.get("hook_event")
    transcript_path = hook_data.get("transcript_path")

    # Find existing or create new session
    session = db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )

    if session and session.status == HookSessionStatus.completed:
        # Already processed — idempotent
        return session

    # Parse transcript for tokens and timing
    token_total = 0
    token_breakdown = None
    end_time = datetime.now(UTC)

    if transcript_path:
        parsed = parse_transcript(transcript_path)
        token_total = parsed["total_tokens"]
        token_breakdown = parsed["breakdown"]
        if parsed.get("end_time"):
            end_time = parsed["end_time"]

    if not session:
        # Session-end arrived without a prior start — create it now
        cwd = hook_data.get("cwd", "")
        project = _resolve_project(db, cwd)
        if not project:
            raise ValueError(f"No project found for cwd: {cwd}")

        agent_name = hook_data.get("agent_name")
        if not agent_name and transcript_path:
            agent_name = _read_agent_name_from_transcript(transcript_path)

        agent = resolve_agent(db, agent_name, project.id) if agent_name else None

        # Main CLI session (no agent name) → attribute as TL overhead
        if not agent:
            agent = _fallback_tl_agent(db, project.id)
            if agent:
                agent_name = agent.role

        session_type = _determine_session_type(agent)

        ticket = None
        sprint_id = None
        if agent and agent.role not in OVERHEAD_ROLES:
            ticket = _resolve_ticket(db, agent, project.id)
            if ticket:
                sprint_id = ticket.sprint_id

        session = HookSession(
            session_id=session_id,
            transcript_path=transcript_path,
            agent_id=agent.id if agent else None,
            project_id=project.id,
            ticket_id=ticket.id if ticket else None,
            sprint_id=sprint_id,
            status=HookSessionStatus.active,
            session_type=session_type,
            agent_name=agent_name,
        )
        db.add(session)
        db.flush()
    else:
        # Update transcript path if we have a better one
        if transcript_path and not session.transcript_path:
            session.transcript_path = transcript_path

        # Re-resolve agent if we didn't get one at session start
        if not session.agent_id:
            agent = None
            agent_name = None
            if transcript_path:
                agent_name = _read_agent_name_from_transcript(transcript_path)
            if agent_name:
                session.agent_name = agent_name
                agent = resolve_agent(db, agent_name, session.project_id)
            # Still no agent? Fall back to TL
            if not agent:
                agent = _fallback_tl_agent(db, session.project_id)
                if agent:
                    session.agent_name = agent.role
            if agent:
                    session.agent_id = agent.id
                    session.session_type = _determine_session_type(agent)
                    # Resolve ticket if worker
                    if agent.role not in OVERHEAD_ROLES:
                        ticket = _resolve_ticket(db, agent, session.project_id)
                        if ticket:
                            session.ticket_id = ticket.id
                            session.sprint_id = ticket.sprint_id

    # Update session with end data
    session.end_time = end_time
    session.total_tokens = token_total
    session.token_breakdown = token_breakdown
    session.status = HookSessionStatus.completed
    session.hook_event = hook_event

    db.commit()
    db.refresh(session)

    # Log stop + tokens through tracking.py
    agent = db.get(Agent, session.agent_id) if session.agent_id else None
    if agent:
        if session.ticket_id and agent.role not in OVERHEAD_ROLES:
            tracking.log_stop(db, session.ticket_id, agent.id)
            if token_total > 0:
                tracking.log_tokens(
                    db, session.ticket_id, agent.id, token_total, source="hook"
                )
        else:
            tracking.log_overhead_stop(db, session.project_id, agent.id)
            if token_total > 0:
                tracking.log_overhead_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )
    elif token_total > 0:
        # No TL agent on project — truly unattributed
        _create_unattributed_alert(db, session)

    return session


def parse_transcript(path: str) -> dict:
    """Parse a Claude Code JSONL transcript file for token usage and timing.

    Returns:
        {
            "total_tokens": int,
            "breakdown": {"input": int, "output": int, "cache_creation": int, "cache_read": int},
            "end_time": datetime | None,
        }
    """
    total = 0
    breakdown = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    last_timestamp = None

    transcript = Path(path)
    if not transcript.exists():
        logger.warning("Transcript not found: %s", path)
        return {"total_tokens": 0, "breakdown": breakdown, "end_time": None}

    try:
        with transcript.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Extract usage — nested under message.usage for assistant entries
                usage = entry.get("message", {}).get("usage") or entry.get("usage")
                if usage:
                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    total += inp + out + cache_create + cache_read
                    breakdown["input"] += inp
                    breakdown["output"] += out
                    breakdown["cache_creation"] += cache_create
                    breakdown["cache_read"] += cache_read

                # Track last timestamp for end_time
                ts = entry.get("timestamp")
                if ts:
                    try:
                        last_timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        pass
    except OSError:
        logger.warning("Could not read transcript: %s", path)
        return {"total_tokens": 0, "breakdown": breakdown, "end_time": None}

    return {
        "total_tokens": total,
        "breakdown": breakdown,
        "end_time": last_timestamp,
    }


def resolve_agent(db: Session, agent_name: str | None, project_id: int) -> Agent | None:
    """Resolve an agent from the transcript agent name.

    1. Match by agent.role == agent_name (primary — roles match teammate names)
    2. Fallback to agent.name match
    3. Scoped to project assignments via project_agents table
    """
    if not agent_name:
        return None

    # Get agent IDs assigned to this project
    assigned_ids = list(db.scalars(
        select(ProjectAgent.agent_id)
        .where(ProjectAgent.project_id == project_id)
    ).all())

    if not assigned_ids:
        return None

    # Primary: match by role (teammate names map to roles)
    agent = db.scalar(
        select(Agent)
        .where(Agent.id.in_(assigned_ids))
        .where(Agent.role == agent_name)
    )
    if agent:
        return agent

    # Fallback: match by name (case-insensitive)
    agent = db.scalar(
        select(Agent)
        .where(Agent.id.in_(assigned_ids))
        .where(Agent.name.ilike(agent_name))
    )
    if not agent:
        logger.warning(
            "resolve_agent: no match for agent_name=%r in project %d "
            "(Teams agentName may not match DWB agent role/name)",
            agent_name, project_id,
        )
    return agent


def list_sessions(
    db: Session,
    project_id: int | None = None,
    status: HookSessionStatus | None = None,
) -> list[HookSession]:
    """List hook sessions with optional filters."""
    stmt = select(HookSession)
    if project_id is not None:
        stmt = stmt.where(HookSession.project_id == project_id)
    if status is not None:
        stmt = stmt.where(HookSession.status == status)
    stmt = stmt.order_by(HookSession.created_at.desc())
    return list(db.scalars(stmt).all())


def get_session(db: Session, session_id: str) -> HookSession | None:
    """Get a single hook session by its Claude Code session_id."""
    return db.scalar(
        select(HookSession).where(HookSession.session_id == session_id)
    )


def _handle_subagent_stop(db: Session, hook_data: dict) -> HookSession:
    """Handle a SubagentStop hook event — creates a separate teammate session.

    SubagentStop sends agent_id (unique per subagent), agent_type (teammate
    role/name), and agent_transcript_path (subagent-specific transcript).
    The session_id in SubagentStop is the PARENT session — we must NOT
    look it up or modify it.
    """
    subagent_id = hook_data.get("agent_id", "")
    if not subagent_id:
        raise ValueError("agent_id is required for SubagentStop")

    # Idempotent: check if we already processed this subagent
    existing = db.scalar(
        select(HookSession).where(HookSession.session_id == subagent_id)
    )
    if existing and existing.status == HookSessionStatus.completed:
        return existing

    # Parse the subagent's transcript (NOT the parent's)
    agent_transcript_path = hook_data.get("agent_transcript_path")
    token_total = 0
    token_breakdown = None
    end_time = datetime.now(UTC)

    if agent_transcript_path:
        parsed = parse_transcript(agent_transcript_path)
        token_total = parsed["total_tokens"]
        token_breakdown = parsed["breakdown"]
        if parsed.get("end_time"):
            end_time = parsed["end_time"]

    # Resolve project from cwd
    cwd = hook_data.get("cwd", "")
    project = _resolve_project(db, cwd)
    if not project:
        raise ValueError(f"No project found for cwd: {cwd}")

    # Map agent_type to DWB agent (agent_type contains the role/name)
    agent_type = hook_data.get("agent_type")
    agent = resolve_agent(db, agent_type, project.id) if agent_type else None

    # If agent_type doesn't match a DWB agent (e.g. "Explore" subagent),
    # attribute to the TL as overhead
    if not agent:
        agent = _fallback_tl_agent(db, project.id)

    session_type = _determine_session_type(agent)

    # Resolve work context for workers
    ticket = None
    sprint_id = None
    if agent and agent.role not in OVERHEAD_ROLES:
        ticket = _resolve_ticket(db, agent, project.id)
        if ticket:
            sprint_id = ticket.sprint_id

    if existing:
        # Update the existing active session
        session = existing
        session.agent_id = agent.id if agent else None
        session.ticket_id = ticket.id if ticket else None
        session.sprint_id = sprint_id
        session.session_type = session_type
        session.agent_name = agent_type
    else:
        # Create new session keyed on subagent_id
        session = HookSession(
            session_id=subagent_id,
            transcript_path=agent_transcript_path,
            agent_id=agent.id if agent else None,
            project_id=project.id,
            ticket_id=ticket.id if ticket else None,
            sprint_id=sprint_id,
            status=HookSessionStatus.active,
            session_type=session_type,
            agent_name=agent_type,
        )
        db.add(session)
        db.flush()

    # Mark completed with token data
    session.end_time = end_time
    session.total_tokens = token_total
    session.token_breakdown = token_breakdown
    session.status = HookSessionStatus.completed
    session.hook_event = "SubagentStop"

    db.commit()
    db.refresh(session)

    # Log stop + tokens through tracking.py
    if agent:
        if session.ticket_id and agent.role not in OVERHEAD_ROLES:
            tracking.log_stop(db, session.ticket_id, agent.id)
            if token_total > 0:
                tracking.log_tokens(
                    db, session.ticket_id, agent.id, token_total, source="hook"
                )
        else:
            tracking.log_overhead_stop(db, session.project_id, agent.id)
            if token_total > 0:
                tracking.log_overhead_tokens(
                    db, session.project_id, agent.id, token_total, source="hook"
                )
    elif token_total > 0:
        _create_unattributed_alert(db, session)

    return session


# --- Internal helpers ---


def _resolve_project(db: Session, cwd: str) -> Project | None:
    """Match a working directory to a project by repo_path."""
    if not cwd:
        return None

    # Exact match first
    project = db.scalar(
        select(Project).where(Project.repo_path == cwd)
    )
    if project:
        return project

    # Prefix match — cwd may be a subdirectory of repo_path
    projects = list(db.scalars(
        select(Project).where(Project.repo_path.isnot(None))
    ).all())
    for p in projects:
        if p.repo_path and cwd.startswith(p.repo_path):
            return p

    return None


def _read_agent_name_from_transcript(path: str) -> str | None:
    """Quick-read the first few lines of a transcript for agentName."""
    transcript = Path(path)
    if not transcript.exists():
        return None

    try:
        with transcript.open("r") as f:
            for i, line in enumerate(f):
                if i > 20:  # Only check first 20 lines
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    agent_name = entry.get("agentName")
                    if agent_name:
                        return agent_name
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return None


def _fallback_tl_agent(db: Session, project_id: int) -> Agent | None:
    """Find the team-lead agent assigned to a project.

    Used as fallback when a main CLI session has no agent name — the human
    user running Claude Code directly is effectively the TL.
    """
    return db.scalar(
        select(Agent)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "team-lead")
        .limit(1)
    )


def _determine_session_type(agent: Agent | None) -> HookSessionType:
    """Determine session type from agent role."""
    if not agent:
        return HookSessionType.main
    if agent.role in OVERHEAD_ROLES:
        return HookSessionType.main
    return HookSessionType.teammate


def _resolve_ticket(db: Session, agent: Agent, project_id: int) -> Ticket | None:
    """Find the best ticket to attribute work to for a worker agent.

    Priority:
    1. In-progress ticket assigned to this agent
    2. Todo ticket assigned to this agent (most recently updated)
    3. In-review ticket assigned to this agent (most recently updated)
    4. Done ticket assigned to this agent (only if updated within last 5 minutes)
    5. None (unattributed)
    """
    # In-progress ticket assigned to this agent
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.in_progress)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: todo ticket assigned to this agent
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.todo)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: in_review ticket assigned to this agent
    # Workers move tickets to in_review before session ends, so SubagentStop
    # often fires after the status change.
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.in_review)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    if ticket:
        return ticket

    # Fallback: recently-done ticket assigned to this agent (within 5 minutes)
    # Catches cases where TL accepts a ticket quickly before SubagentStop fires.
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    ticket = db.scalar(
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .where(Ticket.assigned_agent_id == agent.id)
        .where(Ticket.status == TicketStatus.done)
        .where(Ticket.updated_at >= cutoff)
        .order_by(Ticket.updated_at.desc())
        .limit(1)
    )
    return ticket


def _create_unattributed_alert(db: Session, session: HookSession) -> None:
    """Create an alert for unattributed tokens."""
    # Find any agent assigned to the project to use as raised_by
    pa = db.scalar(
        select(ProjectAgent).where(ProjectAgent.project_id == session.project_id)
    )
    if not pa:
        return

    alert = Alert(
        project_id=session.project_id,
        raised_by_agent_id=pa.agent_id,
        title=f"Unattributed hook session: {session.session_id}",
        body=(
            f"Session {session.session_id} completed with {session.total_tokens} tokens "
            f"but could not be attributed to an agent. "
            f"Agent name from transcript: {session.agent_name}"
        ),
        severity=AlertSeverity.warning,
    )
    db.add(alert)
    db.commit()
