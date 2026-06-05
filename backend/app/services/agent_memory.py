# Path: app/services/agent_memory.py
# File: agent_memory.py
# Created: 2026-06-03
# Purpose: Scaffold an agent's memory directory — identity.md + empty scratchpad/lessons/recent_sessions
# Caller: app/services/agent.create_agent, app/services/project_agent.create_project_agent, manual endpoint
# Callees: app/models/agent, app/models/project
# Data In: db: Session, agent_id: int
# Data Out: ScaffoldResult (paths created, paths preserved, paths skipped)
# Last Modified: 2026-06-03

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project

logger = logging.getLogger(__name__)


_MEMORY_SUBPATH = ".claude/agents/memory"

# Files that the agent writes to. Created empty if missing, never overwritten.
_AGENT_OWNED_FILES = ("scratchpad.md", "lessons.md", "recent_sessions.md")


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
    should call this best-effort and catch — a memory-dir failure shouldn't
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

    # identity.md — always regenerate (system-generated)
    identity_path = memory_dir / "identity.md"
    try:
        identity_path.write_text(_build_identity_md(agent, project), encoding="utf-8")
        result.refreshed.append(str(identity_path))
    except OSError as e:
        raise ScaffoldError(
            "memory_dir_unwritable",
            f"could not write {identity_path}: {e}",
        )

    # Agent-owned files — touch only if missing
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


def _build_identity_md(agent: Agent, project: Project) -> str:
    """System-generated identity.md. Carries the on-spawn checklist + ISO rule."""
    created = (
        agent.created_at.date().isoformat() if agent.created_at else "unknown"
    )
    refreshed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"""# Identity — {agent.name}

> System-generated. Do not edit by hand — `scaffold_agent_dir(agent_id={agent.id})` regenerates this file each time.
> Last refreshed: {refreshed}

## Who you are

- **agent_id:** {agent.id}
- **name:** {agent.name}
- **role:** {agent.role}
- **project:** {project.prefix} ({project.name})
- **created:** {created}

## On Spawn — Read These First

Before doing anything else, read these files in order:

1. **Your role-specific playbook** — `.claude/agents/{{role}}.md` (if it exists)
2. **Your project rules** — `.claude/project_rules_worker.md`
3. **HANDOFF.md** — session continuity notes (current state, decisions, gotchas)
4. **ARCHITECTURE.md** — system design and data model
5. **README.md** — project overview, setup, API reference

This gives you full context without needing to ask the TL. If any of these files don't exist, proceed with what you have and flag it.

## Memory files

Three companion files live in this directory:

- `scratchpad.md` — your in-flight working notes; one block per session, append-only
- `lessons.md` — durable lessons learned across sessions; append a block when something is worth remembering
- `recent_sessions.md` — one-line index of past sessions; append-only

The DWB endpoint `POST /api/agents/{agent.id}/session-complete` writes all three for you at session end. You can also append directly when iterating.

## ISO 8601 entry rule

Every appended entry MUST start with an ISO 8601 UTC timestamp. The session-complete endpoint formats this for you. If you write directly, use:

```
## 2026-06-03T20:48:42+00:00 — session <session_id>
- summary: <one-line summary>
- tokens_used: <int>           (optional)
- lessons:                     (optional)
  - <lesson 1>
```

Never clobber prior entries. Always append.
"""
