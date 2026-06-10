# Path: app/services/git_hook.py
# File: git_hook.py
# Created: 2026-06-10
# Purpose: Process post-commit git hook payloads - parse ticket keys from commit messages and auto-close in_progress/in_review tickets (DWB-345)
# Caller: app/routers/hooks.py
# Callees: app/models (project, ticket, agent, project_agent), app/services/ticket
# Data In: db: Session, repo_path: str, commit_message: str, commit_sha: str
# Data Out: PostCommitResult dict with closed/skipped/unknown lists
# Last Modified: 2026-06-10

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.ticket import Ticket, TicketStatus
from app.schemas.ticket import TicketUpdate
from app.services import ticket as ticket_svc

logger = logging.getLogger(__name__)


# Statuses where auto-closing on commit is meaningful. backlog/todo are
# excluded - skipping the review surface by typing a key in a commit message
# would defeat the purpose. done is excluded for idempotency (already closed).
_AUTOCLOSE_FROM = {TicketStatus.in_progress, TicketStatus.in_review}


def _canonical_path(p: str) -> str:
    """Normalize a repo_path for equality comparison.

    Handles trailing slashes, relative vs absolute, and symlink resolution
    so a hook invoking from a clone with a slightly different path style
    still matches the project row.
    """
    try:
        return str(Path(p).resolve())
    except (OSError, RuntimeError):
        return p.rstrip("/")


def _find_project_by_repo_path(db: Session, repo_path: str) -> Project | None:
    """Resolve the project whose repo_path matches the given path.

    Tries an exact match first (DB-side), then falls back to a canonicalized
    Python-side comparison so symlink / trailing-slash differences don't
    cause the hook to silently no-op.
    """
    exact = db.scalar(select(Project).where(Project.repo_path == repo_path))
    if exact is not None:
        return exact

    target = _canonical_path(repo_path)
    candidates = db.scalars(
        select(Project).where(Project.repo_path.is_not(None))
    ).all()
    for project in candidates:
        if project.repo_path and _canonical_path(project.repo_path) == target:
            return project
    return None


def _resolve_tl_agent_id(db: Session, project_id: int) -> int | None:
    """Find the team-lead agent assigned to the project, if any.

    Used to attribute the auto-PATCH to a real agent (so status_history and
    activity logs aren't anonymous). Returns None if no TL is assigned; the
    caller falls back to ticket.assigned_agent_id-driven attribution.
    """
    stmt = (
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(
            ProjectAgent.project_id == project_id,
            Agent.role == "team-lead",
            Agent.is_active.is_(True),
        )
        .limit(1)
    )
    return db.scalar(stmt)


def _parse_ticket_keys(commit_message: str, prefix: str) -> list[str]:
    """Extract unique <PREFIX>-NNN tokens from a commit message.

    Prefix is scoped per-project so a DWB commit can't accidentally close
    a CI ticket if both prefixes appear in the same message. Preserves
    first-occurrence order so the result is stable across re-parses.
    """
    pattern = re.compile(rf"\b{re.escape(prefix)}-(\d+)\b")
    seen: set[str] = set()
    out: list[str] = []
    for match in pattern.finditer(commit_message):
        key = f"{prefix}-{match.group(1)}"
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def process_post_commit(
    db: Session,
    *,
    repo_path: str,
    commit_message: str,
    commit_sha: str,
) -> dict:
    """Parse a commit message for ticket keys belonging to the project at
    repo_path and auto-close any that are in_progress or in_review.

    Returns a dict with three lists for hook-side logging:
      - closed:  [{ticket_key, ticket_id, prior_status}] - PATCHed to done
      - skipped: [{ticket_key, ticket_id, status, reason}] - not eligible
      - unknown: [ticket_key] - parsed but no matching ticket on this project

    Plus a top-level `project_id` (or None when repo_path didn't resolve)
    and `commit_sha` echoed back for log correlation.

    Idempotent: re-running on the same commit produces an all-skipped
    result (already done). Silent no-op when no project matches the
    repo_path - the hook can fire from any clone without crashing.
    """
    result = {
        "project_id": None,
        "project_prefix": None,
        "commit_sha": commit_sha,
        "closed": [],
        "skipped": [],
        "unknown": [],
    }

    project = _find_project_by_repo_path(db, repo_path)
    if project is None:
        result["reason"] = "no_project_for_repo_path"
        return result

    result["project_id"] = project.id
    result["project_prefix"] = project.prefix

    keys = _parse_ticket_keys(commit_message, project.prefix)
    if not keys:
        result["reason"] = "no_ticket_keys_in_message"
        return result

    tl_agent_id = _resolve_tl_agent_id(db, project.id)

    for key in keys:
        ticket = db.scalar(
            select(Ticket).where(
                Ticket.project_id == project.id,
                Ticket.ticket_key == key,
            )
        )
        if ticket is None:
            result["unknown"].append(key)
            continue

        if ticket.status not in _AUTOCLOSE_FROM:
            result["skipped"].append({
                "ticket_key": key,
                "ticket_id": ticket.id,
                "status": ticket.status.value,
                "reason": (
                    "already_done"
                    if ticket.status == TicketStatus.done
                    else "not_in_autoclose_set"
                ),
            })
            continue

        prior = ticket.status.value
        # Attribute the auto-close to the TL when available; fall back to
        # the ticket's assigned agent so tracking_log still gets a body.
        # update_ticket reads assigned_agent_id off the ticket for tracking,
        # so the TL attribution shows up in status_history.changed_by_agent_id
        # only when we set it before the call - we do so by stashing it.
        original_assignee = ticket.assigned_agent_id
        if tl_agent_id is not None:
            ticket.assigned_agent_id = tl_agent_id
        try:
            ticket_svc.update_ticket(
                db, ticket, TicketUpdate(status=TicketStatus.done)
            )
        finally:
            # Restore assignee so the auto-close doesn't reassign the
            # ticket as a side effect.
            if tl_agent_id is not None and original_assignee != tl_agent_id:
                ticket.assigned_agent_id = original_assignee
                db.commit()
        result["closed"].append({
            "ticket_key": key,
            "ticket_id": ticket.id,
            "prior_status": prior,
        })
        logger.info(
            "git_hook: auto-closed %s (id=%s, %s -> done) from commit %s",
            key, ticket.id, prior, commit_sha[:8],
        )

    return result
