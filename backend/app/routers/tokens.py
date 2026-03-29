from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.models.project import Project
from app.models.ticket import Ticket

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("/audit")
def token_audit(db: Session = Depends(get_db)):
    # Total ticket tokens
    total_ticket_tokens = db.scalar(
        select(func.coalesce(func.sum(Ticket.tokens_used), 0))
    )

    # Tokens by agent
    agent_rows = db.execute(
        select(
            Ticket.assigned_agent_id,
            Agent.name,
            Agent.role,
            func.coalesce(func.sum(Ticket.tokens_used), 0).label("total_tokens"),
        )
        .join(Agent, Ticket.assigned_agent_id == Agent.id)
        .where(Ticket.assigned_agent_id.isnot(None))
        .group_by(Ticket.assigned_agent_id, Agent.name, Agent.role)
        .order_by(func.sum(Ticket.tokens_used).desc())
    ).all()

    tokens_by_agent = [
        {"agent_id": row[0], "name": row[1], "role": row[2], "total_tokens": row[3]}
        for row in agent_rows
    ]

    # Tokens by project
    project_rows = db.execute(
        select(
            Project.id,
            Project.prefix,
            func.coalesce(func.sum(Ticket.tokens_used), 0).label("ticket_tokens"),
            Project.tl_overhead_tokens,
            Project.pm_overhead_tokens,
        )
        .outerjoin(Ticket, Ticket.project_id == Project.id)
        .group_by(Project.id, Project.prefix, Project.tl_overhead_tokens, Project.pm_overhead_tokens)
        .order_by(Project.id)
    ).all()

    tokens_by_project = [
        {
            "project_id": row[0],
            "prefix": row[1],
            "ticket_tokens": row[2],
            "tl_overhead": row[3],
            "pm_overhead": row[4],
            "total": row[2] + row[3] + row[4],
        }
        for row in project_rows
    ]

    # Discrepancies
    discrepancies = []

    agent_sum = sum(a["total_tokens"] for a in tokens_by_agent)
    if agent_sum != total_ticket_tokens:
        discrepancies.append(
            f"Agent token sum ({agent_sum}) != total ticket tokens ({total_ticket_tokens}). "
            f"Likely tickets with no assigned agent accounting for {total_ticket_tokens - agent_sum} tokens."
        )

    project_ticket_sum = sum(p["ticket_tokens"] for p in tokens_by_project)
    if project_ticket_sum != total_ticket_tokens:
        discrepancies.append(
            f"Project ticket token sum ({project_ticket_sum}) != total ticket tokens ({total_ticket_tokens})."
        )

    return {
        "total_ticket_tokens": total_ticket_tokens,
        "tokens_by_agent": tokens_by_agent,
        "tokens_by_project": tokens_by_project,
        "discrepancies": discrepancies,
    }
