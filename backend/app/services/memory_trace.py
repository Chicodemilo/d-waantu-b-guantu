# Path: app/services/memory_trace.py
# File: memory_trace.py
# Created: 2026-09-14
# Purpose: Server-side detection of whether an agent has written to their memory.md within a time window (DWB-519 write-on-close gates). DWB-564: two independent sources, taking whichever is LATER — agents.last_memory_write_at (set directly by the write endpoints) and memory.md's own filesystem mtime (catches a write that went around those endpoints). The original ISO-heading content scan is retired as a gate source; latest_memory_write_at survives only as a standalone provenance utility.
# Caller: app/services/sprint.py (sprint-close gate), app/routers/dwb_sessions.py (session-close gate)
# Callees: app/models (Agent, Project), filesystem (agent memory.md)
# Data In: db Session, Agent, since datetime
# Data Out: bool / datetime
# Last Modified: 2026-09-16 (DWB-564: effective_last_write_at = max(column, mtime))

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project

# DWB-564 history: agent_wrote_since used to work by scanning memory.md for
# an ISO 8601 UTC heading (every memory write stamps one, e.g.
# "## 2026-09-14T16:14:59+00:00"), deliberately avoiding any write-path state
# to stay decoupled from the memory service. That decoupling turned out to be
# the wrong side of a worse coupling: memory.md is REWRITTEN, not just
# appended, by condense/compact (app.services.agent.condense_memory /
# compact_memory), and a rewrite drops every heading it replaces. A
# condensing agent kept passing the gate ONLY because condense_memory happens
# to stamp its own "## <ISO> - condensed" heading, which is exactly the shape
# DWB-560 encourages agents to condense DOWN to; compact_memory stamps no
# heading at all, so an agent whose only memory activity was a compact always
# read as a non-writer, unconditionally. Two real agents hit the condense
# version of this in one evening.
#
# The fix has two independent sources, and effective_last_write_at takes
# whichever is LATER:
#   1. agents.last_memory_write_at - set directly by _record_memory_write
#      (app/services/agent.py) inside all four write endpoints. Exact for
#      every sanctioned write, immune to what the file's content looks like.
#   2. memory.md's own filesystem mtime - catches a write that went AROUND
#      those endpoints (nothing technically prevents an agent's own Edit/
#      Write tool from targeting `.dwb/`, unlike `.claude/`; the worker
#      playbook has to explicitly warn against it, which is itself evidence
#      the path is real, not hypothetical).
# Neither alone is enough: the column misses an off-API write; a column-only
# design also has a subtler gap the max() fixes - an agent who wrote through
# the API on Monday (column set) and then wrote again OUTSIDE the API on
# Friday (mtime moves, column doesn't) would read as stale under column-only.
# Taking the max of both sources is what neither alone gets right.
#
# `.dwb/` is gitignored (.gitignore:38), so no checkout, restore, or other
# git operation can move memory.md's mtime; only an actual write (through
# the API or directly) can. The one real gap that isn't solved for free:
# scaffold_agent_dir's first-run `.touch()` (app/services/agent_memory.py)
# creates an EMPTY memory.md, which would set mtime to scaffold time on a
# file nobody has written to yet - see _mtime_utc's empty-file guard.
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

    DWB-564: NOT used by agent_wrote_since (the gate) anymore - kept as a
    standalone provenance utility. Reused by
    backend/scripts/backfill_last_memory_write_at.py to populate the column
    for existing rows from their current memory.md, and by
    test_memory_lessons_only_dwb560.py's check that a lessons-free
    session-complete still stamps a heading, independent of what the gate
    reads.

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


def _mtime_utc(path: Path) -> datetime | None:
    """The file's own last-modified time, or None if it doesn't exist, isn't
    stat-able, or is EMPTY.

    DWB-564: the empty-file case is the guard scaffold_agent_dir's first-run
    `.touch()` needs. That call creates a zero-byte memory.md before the
    agent has ever written anything; without this guard, an agent scaffolded
    inside a sprint/session window would read as "wrote just now" purely
    from being created.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size == 0:
        return None
    return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def effective_last_write_at(db: Session, agent: Agent) -> datetime | None:
    """The best-known "agent wrote to memory" timestamp: whichever is LATER
    of agents.last_memory_write_at (DWB-564 - set directly by the write
    endpoints) and memory.md's own mtime (catches a write that went around
    them). See the module comment for why neither source alone is enough.
    """
    candidates: list[datetime] = []
    if agent.last_memory_write_at is not None:
        candidates.append(_as_utc(agent.last_memory_write_at))
    if agent.project_id is not None:
        project = db.get(Project, agent.project_id)
        if project is not None:
            mtime = _mtime_utc(_memory_md_path(project, agent))
            if mtime is not None:
                candidates.append(mtime)
    return max(candidates) if candidates else None


def agent_wrote_since(db: Session, agent: Agent, since: datetime | None) -> bool:
    """True if the agent wrote to memory at/after ``since``.

    DWB-564: reads effective_last_write_at (max of the column and mtime),
    not memory.md's content - see the module comment for why the
    heading-only design was replaced.

    ``since=None`` means "any write ever on record" - used when a sprint has no
    start_date to anchor a window. No evidence at all (column unset AND no
    usable mtime, or an unscoped agent) returns False: that is a genuine
    non-writer, which is the teeth of the gate.
    """
    latest = effective_last_write_at(db, agent)
    if latest is None:
        return False
    if since is None:
        return True
    return latest >= _as_utc(since)
