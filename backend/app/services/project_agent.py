# Path: app/services/project_agent.py
# File: project_agent.py
# Created: 2026-03-29
# Purpose: Project-agent assignment CRUD + team listing with liveness (DWB-387); idempotent create (DWB-365 invariant pairing)
# Caller: app/routers/project_agents.py, app/routers/projects.py
# Callees: app/models/project_agent.py, app/models/hook_session.py
# Data In: db: Session, ProjectAgentCreate, project_id
# Data Out: list[ProjectAgent], ProjectAgent, team-listing rows
# Last Modified: 2026-06-12

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.hook_session import HookSession
from app.models.project_agent import ProjectAgent
from app.schemas.project_agent import ProjectAgentCreate

# DWB-387: how recent a hook_sessions event must be for an agent to count as
# "presumed live". 15 min is comfortably wider than the marker-sweeper cadence
# and the longest hook_session a parked-idle Claude Code teammate stays silent
# between SubagentStops, but tight enough that a dead worker shows up as
# offline before the next sprint planning window.
PRESUMED_LIVE_THRESHOLD_MINUTES = 15


def list_project_agents(
    db: Session,
    project_id: int | None = None,
    agent_id: int | None = None,
) -> list[ProjectAgent]:
    stmt = select(ProjectAgent)
    if project_id:
        stmt = stmt.where(ProjectAgent.project_id == project_id)
    if agent_id:
        stmt = stmt.where(ProjectAgent.agent_id == agent_id)
    return list(db.scalars(stmt).all())


def get_project_agent(db: Session, pa_id: int) -> ProjectAgent | None:
    return db.get(ProjectAgent, pa_id)


def create_project_agent(db: Session, data: ProjectAgentCreate) -> ProjectAgent:
    # DWB-365: idempotent. create_agent now inserts the bridge automatically
    # for any agent with project_id set, so callers that also POST
    # /api/project-agents (legacy two-step flow) would otherwise trip the
    # uq_project_agent UNIQUE constraint. Return the existing row instead.
    existing = db.scalar(
        select(ProjectAgent).where(
            ProjectAgent.project_id == data.project_id,
            ProjectAgent.agent_id == data.agent_id,
        )
    )
    if existing is not None:
        return existing

    pa = ProjectAgent(**data.model_dump())
    db.add(pa)
    db.commit()
    db.refresh(pa)
    # Best-effort scaffold for the assigned agent (DWB-293) — idempotent if the
    # dir already exists. Local import to avoid circularity with agent_memory.
    from app.services import agent_memory
    try:
        agent_memory.scaffold_agent_dir(db, pa.agent_id)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "scaffold_agent_dir failed for agent_id=%s on project_agent assign: %s",
            pa.agent_id, e,
        )
    return pa


def delete_project_agent(db: Session, pa: ProjectAgent) -> None:
    db.delete(pa)
    db.commit()


def list_project_team(
    db: Session, project_id: int, include_inactive: bool = False
) -> list[dict]:
    """DWB-313 / DWB-387: single-roundtrip team listing for a project, with liveness.

    Joins project_agents → agents and LEFT JOINs a per-agent
    MAX(COALESCE(end_time, start_time)) over hook_sessions to surface
    last_seen and a computed presumed_live (within PRESUMED_LIVE_THRESHOLD_MINUTES).

    Defaults to active-only; pass include_inactive=True for the full historical
    roster.
    """
    last_seen_subq = (
        select(
            HookSession.agent_id.label("agent_id"),
            func.max(
                func.coalesce(HookSession.end_time, HookSession.start_time)
            ).label("last_seen"),
        )
        .where(HookSession.agent_id.is_not(None))
        .group_by(HookSession.agent_id)
        .subquery()
    )

    stmt = (
        select(
            Agent.id.label("agent_id"),
            Agent.name,
            Agent.role,
            Agent.is_active,
            ProjectAgent.assigned_at,
            last_seen_subq.c.last_seen,
        )
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .join(
            last_seen_subq,
            last_seen_subq.c.agent_id == Agent.id,
            isouter=True,
        )
        .where(ProjectAgent.project_id == project_id)
    )
    if not include_inactive:
        stmt = stmt.where(Agent.is_active.is_(True))
    stmt = stmt.order_by(ProjectAgent.assigned_at.asc())

    # hook_sessions timestamps are naive UTC (DateTime without timezone);
    # match that on the comparison side so the subtraction stays in the same
    # frame and we don't accidentally compare aware to naive.
    threshold = datetime.utcnow() - timedelta(
        minutes=PRESUMED_LIVE_THRESHOLD_MINUTES
    )

    return [
        {
            "agent_id": row.agent_id,
            "name": row.name,
            "role": row.role,
            "is_active": row.is_active,
            "assigned_at": row.assigned_at,
            "last_seen": row.last_seen,
            "presumed_live": (
                row.last_seen is not None and row.last_seen >= threshold
            ),
        }
        for row in db.execute(stmt).all()
    ]
