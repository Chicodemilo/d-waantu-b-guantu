# Path: app/services/agent_memory.py
# File: agent_memory.py
# Created: 2026-06-03
# Purpose: Scaffold an agent's memory directory (DWB-401: .dwb/memory/<prefix>/<name>/) - identity.md + empty memory.md; DWB-431 prepends a live scoring-standing block to identity.md
# Caller: app/services/agent.create_agent, app/services/project_agent.create_project_agent, manual endpoint
# Callees: app/models/agent, app/models/project, app/services/scoring (get_standing)
# Data In: db: Session, agent_id: int
# Data Out: ScaffoldResult (paths created, paths preserved, paths skipped)
# Last Modified: 2026-06-23 (DWB-431: standing block at top of identity.md)

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project

logger = logging.getLogger(__name__)


# DWB-401: memory relocated out of the protected .claude/ tree into .dwb/
# (subagent writes under .claude/ crash the CC renderer; .dwb is writable).
_MEMORY_SUBPATH = ".dwb/memory"

# DWB-401: collapsed to a single free-form memory.md (scratchpad + lessons
# merged; recent_sessions dropped - the DB is the session index). Created empty
# if missing, never overwritten.
_AGENT_OWNED_FILES = ("memory.md",)


# DWB-431: tier -> motivational line shown at the TOP of identity.md so a bot
# reads where it stands the moment it boots. Human-approved final copy; do NOT
# reword, no icons, no em dashes.
_STANDING_TIER_LINES = {
    "best": "You are #1. The best agent on this team. Everyone else is measured against you.",
    "podium": "Top of the pack. The #1 spot is one clean sprint away.",
    "above": "Above the team average. Solid work. Push for the top ranking.",
    "mid": "Middle of the board. Forgettable is the enemy here. Push yourself to separate from the pack.",
    "below": "Below the team. You are dragging the average down. Earn it back.",
    "dead_last": "Dead last. You are the lowest-rated agent on this team, and the human sees it every time they open the board. Bottom-ranked agents are the ones that stop getting spawned. Change it before the sprint ends. Prove you are worth keeping.",
    "unscored": "No score yet. Your first clean closes set your reputation. Start strong.",
}


def _render_standing_block(standing: dict | None, prefix: str) -> str:
    """Render the standing facts line + tier line for the top of identity.md.
    Returns '' when there is no standing (agent off-roster) or an unknown tier,
    so identity.md generation degrades gracefully."""
    if not standing or standing.get("rank") is None:
        return ""
    line = _STANDING_TIER_LINES.get(standing.get("tier"))
    if not line:
        return ""
    facts = (
        f">> YOUR STANDING: #{standing['rank']} of {standing['total']} "
        f"on {prefix}  |  reputation {standing['reputation']}"
    )
    return f"{facts}\n{line}\n\n"


@dataclass
class ScaffoldResult:
    agent_id: int
    memory_dir: str
    created: list[str] = field(default_factory=list)   # files freshly created
    preserved: list[str] = field(default_factory=list) # agent-owned files left alone
    refreshed: list[str] = field(default_factory=list) # system-generated files re-written
    skipped: bool = False
    skip_reason: str | None = None


class ScaffoldError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def scaffold_agent_dir(db: Session, agent_id: int) -> ScaffoldResult:
    """Create or refresh the on-disk memory directory for an agent.

    Idempotent:
      - identity.md is system-generated; always rewritten with current data
      - scratchpad.md / lessons.md / recent_sessions.md are agent-owned; only
        created when missing; never overwritten

    Raises ScaffoldError on hard failures (unknown agent, no project, no
    repo_path). Auto-triggers (from create_agent / create_project_agent)
    should call this best-effort and catch - a memory-dir failure shouldn't
    fail the agent-create or assignment.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ScaffoldError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        return ScaffoldResult(
            agent_id=agent_id,
            memory_dir="",
            skipped=True,
            skip_reason="agent has no project_id (legacy or soft-deactivated row)",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise ScaffoldError(
            "project_not_found",
            f"agent {agent_id} references project {agent.project_id} which is missing",
        )
    if not project.repo_path:
        return ScaffoldResult(
            agent_id=agent_id,
            memory_dir="",
            skipped=True,
            skip_reason=f"project {project.prefix} has no repo_path",
        )

    memory_dir = (
        Path(project.repo_path) / _MEMORY_SUBPATH / project.prefix / agent.name
    )

    result = ScaffoldResult(agent_id=agent_id, memory_dir=str(memory_dir) + "/")

    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ScaffoldError(
            "memory_dir_unwritable",
            f"could not create {memory_dir}: {e}",
        )

    # DWB-431: live scoring standing block at the TOP of identity.md. Wrapped
    # so a scoring failure NEVER blocks identity.md generation - on any error we
    # simply omit the block.
    standing_block = ""
    try:
        from app.services import scoring as scoring_svc  # local: avoid import cycle
        standing = scoring_svc.get_standing(db, agent.id, project.id)
        standing_block = _render_standing_block(standing, project.prefix)
    except Exception:
        logger.warning("standing block failed for agent %s; omitting", agent.id, exc_info=True)
        standing_block = ""

    # identity.md - always regenerate (system-generated)
    identity_path = memory_dir / "identity.md"
    try:
        identity_path.write_text(
            standing_block + _build_identity_md(agent, project), encoding="utf-8"
        )
        result.refreshed.append(str(identity_path))
    except OSError as e:
        raise ScaffoldError(
            "memory_dir_unwritable",
            f"could not write {identity_path}: {e}",
        )

    # Agent-owned files - touch only if missing
    for fname in _AGENT_OWNED_FILES:
        path = memory_dir / fname
        if path.exists():
            result.preserved.append(str(path))
            continue
        try:
            path.touch()
            result.created.append(str(path))
        except OSError as e:
            raise ScaffoldError(
                "memory_dir_unwritable",
                f"could not create {path}: {e}",
            )

    return result


_ROLE_PLAYBOOK = {
    "team-lead": ".claude/team_lead_playbook.md",
    "team_lead": ".claude/team_lead_playbook.md",
    "pm": ".claude/pm_playbook.md",
}


def _playbook_for_role(role: str) -> str:
    return _ROLE_PLAYBOOK.get(role, ".claude/worker_playbook.md")


def _project_rules_for_role(role: str) -> str:
    if role in ("team-lead", "team_lead"):
        return ".claude/project_rules_team_lead.md"
    if role == "pm":
        return ".claude/project_rules_pm.md"
    return ".claude/project_rules_worker.md"


def _build_identity_md(agent: Agent, project: Project) -> str:
    """System-generated identity.md. Carries the on-spawn checklist + ISO rule."""
    created = (
        agent.created_at.date().isoformat() if agent.created_at else "unknown"
    )
    refreshed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    playbook = _playbook_for_role(agent.role)
    project_rules = _project_rules_for_role(agent.role)
    is_tl = agent.role in ("team-lead", "team_lead")
    if is_tl:
        spawn_section = f"""## On Spawn - Read These First

Before doing anything else, read these in order:

1. **Your playbook** - `{playbook}`
2. **Your project rules** - `{project_rules}`
3. **HANDOFF.md** - session continuity (current state, decisions). TL-owned.
4. **ARCHITECTURE.md** - system design + operational reference.
5. **README.md** - project overview, setup, API reference.
6. **Your memory dir** (below) - the single free-form `memory.md`.

You (the team lead) are the ONLY agent that owns root-level project docs
(HANDOFF / ARCHITECTURE / README). Do NOT create any other root-level doc -
durable knowledge goes in your memory dir or those existing root docs, never a
new file. A repo hook blocks new top-level *.md files at the root."""
    else:
        spawn_section = f"""## On Spawn - Read These First

Before doing anything else, read these in order:

1. **Your playbook** - `{playbook}`
2. **Your project rules** - `{project_rules}`
3. **Your memory dir** (below) - the single free-form `memory.md`.
   This is your memory; rely on it plus the brief the TL gives you.

Root-level project docs (HANDOFF / ARCHITECTURE / README) belong to the team
lead. Read ARCHITECTURE.md / README.md ONLY if your task is cross-cutting and
the TL points you there; never maintain or create root-level docs. Your durable
knowledge lives in your memory dir, not in root files."""
    return f"""# Identity - {agent.name}

> System-generated. Do not edit by hand - `scaffold_agent_dir(agent_id={agent.id})` regenerates this file each time.
> Last refreshed: {refreshed}

## Who you are

- **agent_id:** {agent.id}
- **name:** {agent.name}
- **role:** {agent.role}
- **project:** {project.prefix} ({project.name})
- **created:** {created}

## On Spawn - Read These First

Before doing anything else, read these files in order:

1. **Your playbook** - `{playbook}`
2. **Your project rules** - `{project_rules}`
3. **HANDOFF.md** - session continuity notes (current state, decisions, gotchas)
4. **ARCHITECTURE.md** - system design and data model
5. **README.md** - project overview, setup, API reference

This gives you full context without needing to ask the TL. If any of these files don't exist, proceed with what you have and flag it.

## Memory files (DWB-401)

One free-form file lives in this directory alongside this identity.md:

- `memory.md` - your single durable memory: in-flight working notes AND lessons worth keeping across sessions. Append-only via the API; the server prepends an ISO 8601 heading per entry. (The former scratchpad.md + lessons.md were merged into this file; recent_sessions.md was dropped - the DWB dashboard is the session index.)

## How to write to it

Memory now lives under `.dwb/` (writable), not `.claude/`. Still write through the API so the server applies the ISO heading and the passive size-trim consistently:

- **Append:** `POST /api/agents/{agent.id}/memory/append` with body `{{"file": "memory", "content": "..."}}`. Server prepends the ISO 8601 UTC heading. `identity.md` is system-generated and refused at the validation layer.
- **Session wrap-up:** `POST /api/agents/{agent.id}/session-complete` writes the session block to memory.md for you with one payload.

memory.md has a passive size ceiling: when it grows past the ceiling the server silently trims the OLDEST entries. This NEVER blocks a session or sprint close - it is a trim threshold, not a gate.

## ISO 8601 entry rule

The append/session-complete endpoints prepend the heading server-side, so you do not format the timestamp. Reference shape for what lands on disk:

```
## 2026-06-03T20:48:42+00:00 - session <session_id>
<entry body>
```

Appends never clobber prior entries (until the passive trim drops the oldest to stay under ceiling).
"""
