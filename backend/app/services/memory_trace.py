# Path: app/services/memory_trace.py
# File: memory_trace.py
# Created: 2026-09-14
# Purpose: Server-side detection of whether an agent has written to their memory.md within a time window (DWB-519 write-on-close gates). DWB-564: two independent sources, taking whichever is LATER — agents.last_memory_write_at (set directly by the write endpoints) and memory.md's own filesystem mtime (catches a write that went around those endpoints). The original ISO-heading content scan is retired as a gate source; latest_memory_write_at survives only as a standalone provenance utility.
# Caller: app/services/sprint.py (sprint-close gate), app/routers/dwb_sessions.py (session-close gate)
# Callees: app/models (Agent, Project), filesystem (agent memory.md)
# Data In: db Session, Agent, since datetime
# Data Out: bool / datetime
# Last Modified: 2026-09-29 (DWB-589: human_memory proves participation from agent_memories, not from stock memory.md)

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory
from app.models.project import MemoryMode, Project

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


def _human_memory_wrote_since(
    db: Session, agent: Agent, since: datetime | None
) -> bool:
    """DWB-589: participation proved from the human_memory store itself.

    Counts rows in ``agent_memories``, and deliberately nothing else.

    WHY NOT the two stock sources. On a switched project both of them lie in the
    same direction, and a gate that can be satisfied by a store the project is
    forbidden to use has no teeth:

    1. ``memory.md`` mtime. A pre-switch write, or any direct file write, sits
       in the window and passes an agent who never touched the new store.
       ``.dwb/`` is writable - only the playbook warns against it - so this is
       reachable, not theoretical.
    2. ``agents.last_memory_write_at``. Stamped at write time by BOTH the stock
       writes and DWB-586's raw write, so it cannot distinguish the two, and it
       records when the column last moved rather than when the store gained a
       row. A backdated or migrated row leaves the two disagreeing.

    Both were shown failing against the old gate before this function existed;
    the tests that caught them are in tests/test_human_memory_enforcement_dwb589.py.

    WHY NOT journal entries. The journal is the STORY store (spec section 5) and
    it is deliberately free to sprawl. Counting it would let an agent satisfy a
    write-on-close gate with an episode instead of a lesson, which is the
    distinction DWB-560 already fought for when it cut session narration out of
    memory.md. Participation means a lesson landed.

    ``created_at`` is the clock here rather than ``created_session_id``, because
    the gate's window is a sprint's calendar span and a session reference cannot
    be compared to it without a second join that answers the same question less
    directly. Note this is NOT the decay clock: section 3's clock is sessions,
    and nothing that decays reads this.
    """
    stmt = select(func.count()).select_from(AgentMemory).where(
        AgentMemory.agent_id == agent.id
    )
    if since is not None:
        # DB timestamps are naive UTC; normalise before comparing or the
        # comparison silently does the wrong thing across the tz boundary.
        bound = _as_utc(since).astimezone(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(AgentMemory.created_at >= bound)
    return db.execute(stmt).scalar_one() > 0


def agent_wrote_since(db: Session, agent: Agent, since: datetime | None) -> bool:
    """True if the agent wrote to memory at/after ``since``.

    DWB-564: for a STOCK project this reads effective_last_write_at (max of the
    column and mtime), not memory.md's content - see the module comment for why
    the heading-only design was replaced.

    DWB-589: for a ``human_memory`` project it reads the human_memory store
    instead. Spec section 7 hard rule 1 seals stock memory on those projects, so
    proving participation from a sealed store would be proving it from somewhere
    the agent is forbidden to write. See _human_memory_wrote_since.

    DWB-586's raw write stamps ``last_memory_write_at`` like every other memory
    write, so the POSITIVE case needed no branch at all and this one changes
    nothing about it. The branch exists for the NEGATIVE: without it an agent
    with no row in the new store still passed on a stale stock mtime, and the
    gate's teeth are entirely in the negative.

    ``since=None`` means "any write ever on record" - used when a sprint has no
    start_date to anchor a window. No evidence at all (column unset AND no
    usable mtime, or an unscoped agent) returns False: that is a genuine
    non-writer, which is the teeth of the gate.
    """
    project = (
        db.get(Project, agent.project_id) if agent.project_id is not None else None
    )
    if project is not None and project.memory_mode == MemoryMode.human_memory:
        return _human_memory_wrote_since(db, agent, since)

    latest = effective_last_write_at(db, agent)
    if latest is None:
        return False
    if since is None:
        return True
    return latest >= _as_utc(since)
