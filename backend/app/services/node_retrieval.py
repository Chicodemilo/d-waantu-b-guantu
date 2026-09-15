# Path: app/services/node_retrieval.py
# File: node_retrieval.py
# Created: 2026-09-14
# Purpose: Retrieval-into-work lane (DWB-524). Turns the node graph (DWB-522/523)
#          into work context: relevant_lessons() matches an agent's assigned/queued
#          ticket text against memory-domain nodes and returns pointer-only lesson
#          refs (source agent + entry heading + date, resolved from the agent's
#          memory.md at query time); related_nodes() returns a ticket's related
#          lessons / sessions / code files via the same match service. Empty corpus
#          degrades to empty lists.
# Caller: app/services/agent.spawn_prepare_payload, app/routers/tickets.py
# Callees: app/services/node_match (match_nodes), app/models (Ticket)
# Data In: db: Session, project/agent/ticket + repo_path
# Data Out: list[dict] lessons / dict of related node groups (pointers only)
# Last Modified: 2026-09-14

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.node import NodePointerKind
from app.models.ticket import Ticket, TicketStatus
from app.services.node_match import match_nodes

# Ticket states whose text seeds a spawn's relevant-lessons query: work the agent
# is about to pick up (assigned + not yet closed).
_ACTIVE_TICKET_STATES = (TicketStatus.todo, TicketStatus.in_progress)

# A memory entry heading written by the memory API: "## <ISO8601>" optionally
# followed by " - session <id>". Used to resolve the entry a matched tag lives in.
_HEADING_RE = re.compile(r"^##\s+(.*\S)\s*$")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+(?:[+-]\d{2}:\d{2}|Z)?")


def _agent_from_memory_ref(ref: str) -> str | None:
    """Extract the source agent name from a memory pointer ref.

    Memory refs look like ``.dwb/memory/<PREFIX>/<AgentName>/memory.md`` (see
    node_touch.memory_provider), so the agent is the parent directory name.
    Returns None if the ref does not have that shape.
    """
    try:
        parent = Path(ref).parent.name
    except (ValueError, OSError):
        return None
    return parent or None


def _tag_matcher(tag: str) -> re.Pattern:
    # Same identifier-part boundary the grounding lanes use (underscore/camel is a
    # separator, a trailing alphanumeric is not) so we find the tag on its line.
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(tag)}(?![A-Za-z0-9])", re.IGNORECASE)


def _resolve_memory_entry(
    repo_path: str | None, ref: str, tag: str
) -> tuple[str | None, str | None]:
    """Resolve the (entry_heading, date) a matched tag lives under in a memory.md.

    Barry's memory grounding is whole-file (one pointer per memory.md, no line
    refs), so we recover the entry at query time: read the file, find the first
    line carrying the tag, walk UP to the nearest ``## <ISO>`` heading, and return
    that heading + its ISO date. Best-effort: (None, None) when repo_path is
    missing, the file is unreadable, or no heading precedes the hit.
    """
    if not repo_path:
        return None, None
    try:
        lines = (Path(repo_path) / ref).read_text(errors="replace").splitlines()
    except (OSError, UnicodeError):
        return None, None
    matcher = _tag_matcher(tag)
    hit_idx: int | None = None
    for i, line in enumerate(lines):
        if matcher.search(line):
            hit_idx = i
            break
    if hit_idx is None:
        return None, None
    for j in range(hit_idx, -1, -1):
        m = _HEADING_RE.match(lines[j])
        if m:
            heading = m.group(1)
            iso = _ISO_RE.search(heading)
            return heading, (iso.group(0) if iso else None)
    return None, None


def relevant_lessons(
    db: Session,
    project,
    agent,
    *,
    top_n: int = 5,
) -> list[dict]:
    """Top-N memory-domain lessons relevant to an agent's assigned/queued tickets.

    Matches the concatenated title+description of the agent's todo/in_progress
    tickets against the node graph and keeps nodes grounded in the memory domain.
    Each lesson is POINTERS ONLY (no memory content - the TL already injects
    memory_full): tag, weight, the source agent, the memory.md ref, and the entry
    heading + date resolved from that file. The spawning agent's OWN memory is
    skipped (already in memory_full). Empty corpus / no tickets -> [].
    """
    tickets = list(
        db.execute(
            select(Ticket).where(
                Ticket.project_id == project.id,
                Ticket.assigned_agent_id == agent.id,
                Ticket.status.in_(_ACTIVE_TICKET_STATES),
            )
        ).scalars().all()
    )
    if not tickets:
        return []

    text = " ".join(f"{t.title} {t.description or ''}" for t in tickets)
    _query_tags, matches = match_nodes(db, project.id, text)
    repo_path = getattr(project, "repo_path", None)

    # Group memory lessons per matched node (tag), preserving the weight-desc node
    # order. Then interleave BREADTH-FIRST across tags so top_n surfaces DIVERSE
    # concepts rather than one high-weight tag repeated across every agent that
    # mentioned it (e.g. a generic 'doc' node grounded in five memories).
    per_tag: list[list[dict]] = []
    seen: set[tuple[str, str]] = set()
    for node, _neighbors in matches:
        node_lessons: list[dict] = []
        for p in node.pointers:
            if p.kind != NodePointerKind.memory:
                continue
            source_agent = _agent_from_memory_ref(p.ref)
            # Skip the spawning agent's own memory - it's already injected.
            if source_agent and source_agent == agent.name:
                continue
            key = (node.tag, p.ref)
            if key in seen:
                continue
            seen.add(key)
            heading, date = _resolve_memory_entry(repo_path, p.ref, node.tag)
            node_lessons.append({
                "tag": node.tag,
                "weight": node.weight,
                "source_agent": source_agent,
                "memory_ref": p.ref,
                "entry_heading": heading,
                "date": date,
            })
        if node_lessons:
            per_tag.append(node_lessons)

    lessons: list[dict] = []
    depth = 0
    while len(lessons) < top_n and any(depth < len(nl) for nl in per_tag):
        for nl in per_tag:
            if depth < len(nl):
                lessons.append(nl[depth])
                if len(lessons) >= top_n:
                    break
        depth += 1
    return lessons


def related_nodes(
    db: Session,
    project,
    text: str,
    *,
    top_n: int = 10,
) -> dict:
    """Related nodes for a piece of text (a ticket), grouped by domain (DWB-524).

    Runs the match service and buckets each matched node's pointers into lessons
    (memory), sessions (session), and code (code+doc file refs). Pointers only.
    Empty corpus -> empty groups. ``query_tags`` is echoed for transparency.
    """
    query_tags, matches = match_nodes(db, project.id, text)
    repo_path = getattr(project, "repo_path", None)

    lessons: list[dict] = []
    sessions: list[dict] = []
    code: list[dict] = []
    for node, _neighbors in matches:
        for p in node.pointers:
            if p.kind == NodePointerKind.memory:
                heading, date = _resolve_memory_entry(repo_path, p.ref, node.tag)
                lessons.append({
                    "tag": node.tag, "weight": node.weight,
                    "source_agent": _agent_from_memory_ref(p.ref),
                    "memory_ref": p.ref, "entry_heading": heading, "date": date,
                })
            elif p.kind == NodePointerKind.session:
                sessions.append({
                    "tag": node.tag, "weight": node.weight, "ref": p.ref,
                })
            elif p.kind in (NodePointerKind.code, NodePointerKind.doc):
                code.append({
                    "tag": node.tag, "weight": node.weight, "kind": p.kind.value,
                    "ref": p.ref, "sha": p.sha,
                    "line_start": p.line_start, "line_end": p.line_end,
                })

    return {
        "query_tags": query_tags,
        "lessons": lessons[:top_n],
        "sessions": sessions[:top_n],
        "code": code[:top_n],
    }
