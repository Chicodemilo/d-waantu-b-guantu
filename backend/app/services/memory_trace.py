# Path: app/services/memory_trace.py
# File: memory_trace.py
# Created: 2026-09-14
# Purpose: Server-side detection of whether an agent has written to their memory.md within a time window (DWB-519 write-on-close gates). Reads the ISO 8601 write-headings that every memory write stamps, so it needs no coupling to the memory-write endpoints themselves.
# Caller: app/services/sprint.py (sprint-close gate), app/routers/dwb_sessions.py (session-close gate)
# Callees: app/models (Agent, Project), filesystem (agent memory.md)
# Data In: db Session, Agent, since datetime
# Data Out: bool / datetime
# Last Modified: 2026-09-14

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project

# Every memory write (append_memory / record_session_complete, and DWB-518's
# condense) stamps its block with an ISO 8601 UTC heading built from
# datetime.now(timezone.utc).isoformat(timespec="seconds"), e.g.
#   ## 2026-09-14T16:14:59+00:00
#   ## 2026-09-14T16:14:59+00:00 - session <id>
# This heading IS the write trace - it is already server-side, so the gate
# reads it rather than adding a write-path column that would couple to (and
# collide with) the memory service. A bare "Z" suffix is tolerated for safety.
#
# DWB-564: this file (memory.md) is REWRITTEN, not just appended, by the
# condense/compact endpoints (app.services.agent.condense_memory /
# compact_memory), and a rewrite drops every heading it replaces. A
# condensing agent still passes this gate today ONLY because condense_memory
# stamps its own "## <ISO> - condensed" heading — see the load-bearing note
# on that function. compact_memory stamps no heading at all, so an agent
# whose only memory activity is a compact will read as a non-writer here
# regardless of when they actually wrote. If condense's heading shape ever
# changes (or condense is asked to stop stamping one), this function keeps
# working exactly as written and silently starts reporting real writers as
# non-writers — pinned by test_condense_write_gate_coupling_dwb564.py.
_HEADING_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)"
)


def _memory_md_path(project: Project, agent: Agent) -> Path:
    """Canonical memory.md path, mirroring agent._memory_dir (DWB-401)."""
    base = (project.repo_path or ".").rstrip("/")
    return Path(base) / ".dwb" / "memory" / project.prefix / agent.name / "memory.md"


def _as_utc(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC (DB timestamps are naive UTC)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_heading_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(dt)


def latest_memory_write_at(project: Project, agent: Agent) -> datetime | None:
    """Newest write-heading timestamp in the agent's memory.md, or None.

    Returns None when the file is missing/unreadable or carries no parseable
    heading. Scanning all headings (not just the first) is robust to the
    passive trim that historically dropped oldest blocks - the newest in-window
    write is always retained.
    """
    path = _memory_md_path(project, agent)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    latest: datetime | None = None
    for line in text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if not m:
            continue
        ts = _parse_heading_ts(m.group(1))
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def agent_wrote_since(db: Session, agent: Agent, since: datetime | None) -> bool:
    """True if the agent wrote to memory.md at/after ``since``.

    ``since=None`` means "any write ever on record" - used when a sprint has no
    start_date to anchor a window. A missing/unreadable memory file returns
    False: that is a genuine non-writer, which is the teeth of the gate.
    """
    if agent.project_id is None:
        return False
    project = db.get(Project, agent.project_id)
    if project is None:
        return False
    latest = latest_memory_write_at(project, agent)
    if latest is None:
        return False
    if since is None:
        return True
    return latest >= _as_utc(since)
