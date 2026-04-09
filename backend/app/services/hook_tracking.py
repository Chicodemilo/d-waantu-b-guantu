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
from datetime import datetime
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

    1. Find or create HookSession
    2. Parse transcript for tokens and timestamps
    3. Resolve agent and work context
    4. Log stop + tokens via tracking.py
    5. Update session: completed, total_tokens, end_time
    """
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
    end_time = datetime.utcnow()

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
    elif token_total > 0:
        # Unattributed tokens — create an alert
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

                # Extract usage from API response entries
                usage = entry.get("usage")
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
    3. None (unattributed)
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
