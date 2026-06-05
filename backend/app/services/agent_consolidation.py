# Path: app/services/agent_consolidation.py
# File: agent_consolidation.py
# Created: 2026-06-04
# Purpose: Service for the consolidation gate — agent acks + status payload + owner mapping + trim-or-override enforcement
# Caller: app/routers/agents.py, app/routers/projects.py, app/services/sprint.py
# Callees: AgentConsolidationAck, Agent, Project, Sprint, compute_token_budget
# Data In: db: Session, project/sprint/agent ids, optional notes, optional overrides
# Data Out: AgentConsolidationAck rows; status dicts; violation lists
# Last Modified: 2026-06-05

"""Consolidation gate service.

The consolidation gate is satisfied when every active agent who **participated
in the sprint** has posted a consolidation ack. Each agent owns a set of files
(see ``_OWNER_MAP`` below) and is responsible for keeping them inside their
token ceilings — when a sprint closes, they ack that they've reviewed (and
trimmed if needed) their files for that cycle.

DWB-326 narrowed the required-ack set from "all active agents on the project"
to "active agents who actually participated in the sprint" — see
:func:`participants_for_sprint` for the signal union.

DWB-328 added trim-or-override enforcement: ack creation refuses when the
agent's owned files include over-ceiling entries unless every offender has a
non-empty reason in the ``overrides`` map.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_consolidation_ack import AgentConsolidationAck
from app.models.project import Project
from app.models.sprint import Sprint
from app.routers.projects import compute_token_budget


# File-name (as returned by token-budget) -> list of owner roles.
# Files not listed here have no enforced owner and will not appear under any
# agent's owned_over_ceiling_files. The mapping uses the same `name` strings
# emitted by compute_token_budget.
_OWNER_MAP: dict[str, list[str]] = {
    # Repo-root docs — team-lead owns
    "CLAUDE.md": ["team-lead"],
    "HANDOFF.md": ["team-lead"],
    "ARCHITECTURE.md": ["team-lead"],
    "README.md": ["team-lead"],
    "INITIAL.md": ["team-lead"],
    # Per-role playbooks + project rules (agent defs are 8-line stubs — not owned)
    ".claude/team_lead_playbook.md": ["team-lead"],
    ".claude/project_rules_team_lead.md": ["team-lead"],
    ".claude/pm_playbook.md": ["pm"],
    ".claude/project_rules_pm.md": ["pm"],
    # Worker-shared files — every worker role is responsible
    ".claude/worker_playbook.md": ["frontend-worker", "backend-worker", "system-ops", "tester"],
    ".claude/project_rules_worker.md": ["frontend-worker", "backend-worker", "system-ops", "tester"],
}


def _slim_file_entry(f: dict) -> dict:
    """Strip down a token-budget entry to the fields the consolidation UI needs."""
    return {
        "name": f["name"],
        "tokens": f["tokens"],
        "ceiling": f["ceiling"],
        "status": f["status"],
    }


def _build_owner_index(
    active_agents: list[Agent],
) -> tuple[dict[str, list[Agent]], dict[str, Agent]]:
    """Pre-index active agents by role and by name for token-budget owner lookup."""
    agents_by_role: dict[str, list[Agent]] = {}
    for a in active_agents:
        agents_by_role.setdefault(a.role, []).append(a)
    agent_by_name: dict[str, Agent] = {a.name: a for a in active_agents}
    return agents_by_role, agent_by_name


def _owned_files_from_budget(
    budget_files: list[dict],
    agents_by_role: dict[str, list[Agent]],
    agent_by_name: dict[str, Agent],
) -> dict[int, list[dict]]:
    """Map each active agent id → list of warning/over files they own."""
    files_by_owner: dict[int, list[dict]] = {
        a.id: [] for agents in agents_by_role.values() for a in agents
    }
    for f in budget_files:
        if f["status"] == "ok":
            continue
        if f.get("agent_name"):
            owner_agent = agent_by_name.get(f["agent_name"])
            if owner_agent is not None:
                files_by_owner[owner_agent.id].append(_slim_file_entry(f))
            continue
        owner_roles = _OWNER_MAP.get(f["name"], [])
        for role in owner_roles:
            for owner_agent in agents_by_role.get(role, []):
                files_by_owner[owner_agent.id].append(_slim_file_entry(f))
    return files_by_owner


def over_ceiling_files_for_agent(
    db: Session, project: Project, agent: Agent
) -> list[dict]:
    """Return the list of files this agent owns that are at status='over'.

    Used by DWB-328 enforcement: only over-ceiling files (not warnings) demand
    a trim or override. The list is empty when the agent's owned files are all
    inside ceiling.
    """
    if not project.repo_path:
        return []
    try:
        budget = compute_token_budget(db, project)
    except ValueError:
        return []

    # Only this agent's row matters, but the owner index needs the full active
    # roster because shared files (worker.md, etc.) map by role.
    active_agents = list(db.scalars(
        select(Agent)
        .where(Agent.project_id == project.id, Agent.is_active.is_(True))
    ).all())
    agents_by_role, agent_by_name = _build_owner_index(active_agents)
    files_by_owner = _owned_files_from_budget(
        budget["files"], agents_by_role, agent_by_name
    )
    owned = files_by_owner.get(agent.id, [])
    return [f for f in owned if f["status"] == "over"]


def create_ack(
    db: Session,
    agent_id: int,
    sprint_id: int,
    notes: str | None,
    overrides: dict[str, str] | None = None,
) -> tuple[AgentConsolidationAck | None, str | None, list[dict] | None]:
    """Create a consolidation ack. Returns (ack, error_code, violations).

    DWB-328: enforces trim-or-override. If the agent owns any over-ceiling
    files, every offender's filename must appear in ``overrides`` with a
    non-empty reason. Otherwise returns error_code="over_ceiling_violations"
    and a violations list naming the unjustified files.

    error_code is one of:
      - None on success (ack is the created row, violations is None)
      - "agent_not_found"
      - "agent_inactive"
      - "sprint_not_found"
      - "wrong_project"            (agent's project != sprint's project)
      - "over_ceiling_violations"  (violations populated; ack is None)
      - "already_acked"            (unique constraint hit; idempotent caller decides)
    """
    agent = db.get(Agent, agent_id)
    if not agent:
        return None, "agent_not_found", None
    if not agent.is_active:
        return None, "agent_inactive", None

    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        return None, "sprint_not_found", None

    # Agent must be assigned to the sprint's project. With per-project agents
    # (DWB-287), this is a direct project_id comparison.
    if agent.project_id != sprint.project_id:
        return None, "wrong_project", None

    # DWB-328 enforcement: every over-ceiling owned file must either be
    # trimmed (no longer in the list) or accompanied by a non-empty override.
    project = db.get(Project, sprint.project_id)
    over_files = over_ceiling_files_for_agent(db, project, agent) if project else []
    overrides_map = overrides or {}
    violations: list[dict] = []
    for f in over_files:
        reason = overrides_map.get(f["name"])
        if not reason or not isinstance(reason, str) or not reason.strip():
            violations.append({
                "file": f["name"],
                "tokens": f["tokens"],
                "ceiling": f["ceiling"],
            })
    if violations:
        return None, "over_ceiling_violations", violations

    ack = AgentConsolidationAck(
        agent_id=agent_id,
        sprint_id=sprint_id,
        notes=notes,
        overrides=overrides_map or None,
    )
    db.add(ack)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None, "already_acked", None
    db.refresh(ack)
    return ack, None, None


def delete_ack(
    db: Session, agent_id: int, sprint_id: int
) -> bool:
    """Delete an existing ack. Returns True if a row was deleted, False if missing.

    Caller (router) is responsible for authorizing this — DWB-328 reserves it
    for team-lead agents who want to reject a weak override.
    """
    ack = db.scalar(
        select(AgentConsolidationAck).where(
            AgentConsolidationAck.agent_id == agent_id,
            AgentConsolidationAck.sprint_id == sprint_id,
        )
    )
    if not ack:
        return False
    db.delete(ack)
    db.commit()
    return True


def get_consolidation_status(
    db: Session, project: Project, sprint_id: int
) -> dict:
    """Return the consolidation status payload for a given sprint.

    Computes per-agent: acked flag, acked_at, and the list of files they own
    that are at warning/over status in the current token-budget scan.
    """
    sprint = db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project.id:
        # Caller (router) handles this. Return an empty-ish payload to keep
        # the contract simple for any future internal callers.
        return {
            "sprint_id": sprint_id,
            "force_consolidation": project.force_consolidation,
            "gate_satisfied": True,
            "participants": [],
            "agents": [],
        }

    # DWB-326: filter the per-agent blocks to actual sprint participants.
    # Non-participants don't need to ack; reporting them as "unacked" was the
    # rubber-stamp trap.
    participant_ids = participants_for_sprint(db, sprint)
    active_agents = list(db.scalars(
        select(Agent)
        .where(
            Agent.project_id == project.id,
            Agent.is_active.is_(True),
            Agent.id.in_(participant_ids) if participant_ids else Agent.id.is_(None),
        )
        .order_by(Agent.name)
    ).all())

    # Acks already posted for this sprint, keyed by agent_id
    ack_rows = list(db.scalars(
        select(AgentConsolidationAck)
        .where(AgentConsolidationAck.sprint_id == sprint_id)
    ).all())
    acks_by_agent = {a.agent_id: a for a in ack_rows}

    # Token-budget scan — only included if repo_path is set. If absent, no
    # owned-files info is available; the gate still operates on acks alone.
    files_by_owner: dict[int, list[dict]] = {a.id: [] for a in active_agents}
    if project.repo_path:
        try:
            budget = compute_token_budget(db, project)
        except ValueError:
            budget = {"files": []}
        agents_by_role, agent_by_name = _build_owner_index(active_agents)
        files_by_owner = _owned_files_from_budget(
            budget["files"], agents_by_role, agent_by_name
        )

    agent_blocks = []
    for a in active_agents:
        ack = acks_by_agent.get(a.id)
        agent_blocks.append({
            "agent_id": a.id,
            "name": a.name,
            "role": a.role,
            "acked": ack is not None,
            "acked_at": ack.acked_at.isoformat() if ack and ack.acked_at else None,
            "overrides": ack.overrides if ack else None,
            "owned_over_ceiling_files": files_by_owner.get(a.id, []),
        })

    if project.force_consolidation:
        gate_satisfied = all(b["acked"] for b in agent_blocks) if agent_blocks else True
    else:
        gate_satisfied = True

    return {
        "sprint_id": sprint_id,
        "force_consolidation": project.force_consolidation,
        "gate_satisfied": gate_satisfied,
        "participants": sorted(participant_ids),
        "agents": agent_blocks,
    }


def participants_for_sprint(db: Session, sprint: Sprint) -> set[int]:
    """Return the set of agent_ids who participated in this sprint.

    Participation signal is the union of any of:
      * Ticket assigned to the agent in the sprint
      * Comment authored by the agent on a ticket in the sprint
      * tracking_log row with ``sprint_id == sprint.id`` and a non-null agent_id
      * hook_session with ``sprint_id == sprint.id`` and a non-null agent_id
      * activity_log row on the same project, created between sprint start and end

    activity_log has no ``sprint_id`` column so the sprint window is applied via
    ``created_at`` (start_date 00:00 → end_date 23:59:59). When the sprint has
    no start_date, the activity_log signal is skipped — there's no defensible
    window to attribute activity to.
    """
    from datetime import datetime

    from app.models.activity_log import ActivityLog
    from app.models.comment import Comment
    from app.models.hook_session import HookSession
    from app.models.ticket import Ticket
    from app.models.tracking_log import TrackingLog

    ids: set[int] = set()

    # 1. Tickets assigned in the sprint
    rows = db.scalars(
        select(Ticket.assigned_agent_id)
        .where(Ticket.sprint_id == sprint.id, Ticket.assigned_agent_id.is_not(None))
        .distinct()
    ).all()
    ids.update(r for r in rows if r is not None)

    # 2. Comments on tickets in the sprint
    rows = db.scalars(
        select(Comment.author_agent_id)
        .join(Ticket, Comment.ticket_id == Ticket.id)
        .where(Ticket.sprint_id == sprint.id, Comment.author_agent_id.is_not(None))
        .distinct()
    ).all()
    ids.update(r for r in rows if r is not None)

    # 3. tracking_log entries scoped to the sprint
    rows = db.scalars(
        select(TrackingLog.agent_id)
        .where(TrackingLog.sprint_id == sprint.id, TrackingLog.agent_id.is_not(None))
        .distinct()
    ).all()
    ids.update(r for r in rows if r is not None)

    # 4. hook_sessions scoped to the sprint
    rows = db.scalars(
        select(HookSession.agent_id)
        .where(HookSession.sprint_id == sprint.id, HookSession.agent_id.is_not(None))
        .distinct()
    ).all()
    ids.update(r for r in rows if r is not None)

    # 5. activity_log within the sprint window
    if sprint.start_date:
        start_dt = datetime.combine(sprint.start_date, datetime.min.time())
        stmt = (
            select(ActivityLog.agent_id)
            .where(ActivityLog.project_id == sprint.project_id)
            .where(ActivityLog.agent_id.is_not(None))
            .where(ActivityLog.created_at >= start_dt)
        )
        if sprint.end_date:
            end_dt = datetime.combine(sprint.end_date, datetime.max.time())
            stmt = stmt.where(ActivityLog.created_at <= end_dt)
        rows = db.scalars(stmt.distinct()).all()
        ids.update(r for r in rows if r is not None)

    return ids


def unacked_agents_for_sprint(db: Session, sprint: Sprint) -> list[Agent]:
    """Return active agents who participated in this sprint and have not acked.

    Used by the sprint-close gate enforcement path. DWB-326: the required-ack
    set is the intersection of (a) active agents on the project, (b) agents who
    participated per :func:`participants_for_sprint`. Non-participants are not
    asked to rubber-stamp.
    """
    participant_ids = participants_for_sprint(db, sprint)
    if not participant_ids:
        return []
    active = list(db.scalars(
        select(Agent)
        .where(
            Agent.project_id == sprint.project_id,
            Agent.is_active.is_(True),
            Agent.id.in_(participant_ids),
        )
        .order_by(Agent.name)
    ).all())
    if not active:
        return []
    acked_ids = set(db.scalars(
        select(AgentConsolidationAck.agent_id)
        .where(AgentConsolidationAck.sprint_id == sprint.id)
    ).all())
    return [a for a in active if a.id not in acked_ids]
