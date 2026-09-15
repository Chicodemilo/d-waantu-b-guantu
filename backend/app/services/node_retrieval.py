# Path: app/services/node_retrieval.py
# File: node_retrieval.py
# Created: 2026-09-14
# Purpose: Retrieval-into-work lane (DWB-524, ranking reworked in DWB-545). Turns
#          the node graph (DWB-522/523) into work context: relevant_lessons()
#          matches an agent's assigned/queued ticket text against memory-domain
#          nodes and returns pointer-only lesson refs (source agent + entry heading
#          + date, resolved from the agent's memory.md at query time);
#          related_nodes() returns a ticket's related lessons / sessions / code
#          files via the same match service. Both rank by SPECIFICITY (rare +
#          multi-part tags first), drop the most popular tags, collapse code
#          pointers to one per file, and cap each group. Empty corpus degrades to
#          empty lists.
# Caller: app/services/agent.spawn_prepare_payload, app/routers/tickets.py
# Callees: app/services/node_match (match_nodes), app/models (Ticket, Node)
# Data In: db: Session, project/agent/ticket + repo_path
# Data Out: list[dict] lessons / dict of related node groups (pointers only)
# Last Modified: 2026-09-15 (DWB-545: specificity ranking, popularity cutoff, per-file collapse, caps)

from __future__ import annotations

import math
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.node import NodePointer, NodePointerKind
from app.models.ticket import Ticket, TicketStatus
from app.services.node_match import match_nodes
from app.services.node_registry import node_token_counts

# Ticket states whose text seeds a spawn's relevant-lessons query: work the agent
# is about to pick up (assigned + not yet closed).
_ACTIVE_TICKET_STATES = (TicketStatus.todo, TicketStatus.in_progress)

# A memory entry heading written by the memory API: "## <ISO8601>" optionally
# followed by " - session <id>". Used to resolve the entry a matched tag lives in.
_HEADING_RE = re.compile(r"^##\s+(.*\S)\s*$")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+(?:[+-]\d{2}:\d{2}|Z)?")


# --- DWB-545 specificity ranking ---------------------------------------------
# Retrieval used to order by Node.weight, which is a TF-IDF score computed at
# REGISTRATION time over the whole corpus. At corpus scale that still crowns
# broadly-grounded tags: "review" (weight 119) topped every ticket's results,
# pointing at HANDOFF lines and five agents' memory files, and two unrelated
# tickets returned byte-identical output. Retrieval wants the opposite of
# popularity - the tag that is RARE and therefore says something specific about
# THIS ticket. So ranking here is computed per query from the pointer graph and
# never reads Node.weight.

# A tag with 2+ parts ("stick-redemption", "post-commit", "DWB-537") names a
# concept rather than a word, so it outranks an equally-rare single word. Small
# on purpose: it breaks ties toward phrases without letting a common hyphenated
# token beat a genuinely rare one.
MULTI_PART_BOOST = 1.5

# Popularity cutoff: a tag whose distinct-document frequency sits in the top 5%
# of the project's tags is boilerplate for retrieval purposes and is dropped.
# Applied only when the project has enough nodes for a percentile to mean
# anything, and never applied when it would empty the result (a query whose ONLY
# matches are popular tags still gets them - a thin answer beats no answer).
POPULARITY_PERCENTILE = 0.95
_POPULARITY_MIN_NODES = 20

# Hard cap per output group (lessons / sessions / code) and on relevant_lessons.
MAX_PER_GROUP = 10

# Pivoted length normalization for the file-scored code group. A file's score is
# divided by (its pointer count ** this exponent). Without it the longest files
# win every query by sheer surface area: HANDOFF.md and the playbooks mention
# everything, so they outranked the source files a ticket is actually about.
# Full cosine normalization (0.5) overcorrects and pushes big-but-relevant source
# files out, so this uses the partial exponent the IR literature calls pivoted
# normalization. Anything in 0.25-0.35 behaves the same on the DWB corpus; 0.3 is
# the middle of that band.
LENGTH_NORMALIZATION_EXPONENT = 0.3


def pointer_df(node) -> int:
    """Document frequency of a node: how many distinct (kind, ref) documents
    ground it. Per-line pointer lanes (DWB-525/526) emit many pointers into one
    file, so counting distinct documents - not pointers - is what keeps a
    single heavily-tagged file from reading as a widespread concept."""
    return len({(p.kind, p.ref) for p in node.pointers})


def specificity_score(tag: str, df: int, total_docs: int, tf: int = 1) -> float:
    """Rank score for one matched tag: TF-IDF over the query, phrases first.

    Three factors, each doing one job:
      - IDF ``log((N + 1) / (df + 1))``: rarity. A tag in almost every document
        scores ~0; a tag in two documents scores high.
      - TF ``1 + log(tf)``: how often the QUERY (the ticket text) says the tag.
        Rarity alone crowns whatever obscure word the description happened to use
        once; a ticket that repeats "stick redemption" is telling us what it is
        about. Damped so a tag said ten times does not bury one said three times.
      - MULTI_PART_BOOST when the tag has 2+ parts ("stick-redemption",
        "post-commit", "DWB-537"): a phrase names a concept, a word does not.

    Returns 0.0 for a tag with no pointers (it cannot be evidence of anything).
    """
    if df <= 0:
        return 0.0
    n = max(total_docs, df)
    idf = math.log((n + 1) / (df + 1))
    tf_weight = 1.0 + math.log(tf) if tf > 1 else 1.0
    boost = MULTI_PART_BOOST if "-" in tag else 1.0
    return max(idf, 0.0) * tf_weight * boost


def _corpus_doc_count(db: Session, project_id: int) -> int:
    """Distinct (kind, ref) documents grounding anything in this project = the
    N of the IDF above. 0 for an empty corpus."""
    pairs = (
        select(NodePointer.kind, NodePointer.ref)
        .where(NodePointer.project_id == project_id)
        .distinct()
        .subquery()
    )
    return int(db.execute(select(func.count()).select_from(pairs)).scalar() or 0)


def _file_lengths(db: Session, project_id: int, refs: list[str]) -> dict[str, int]:
    """Pointer count per ref = a proxy for how much taggable text a file holds.

    Used as the document length in the pivoted normalization above. One query for
    the whole candidate set (no N+1); refs absent from the result default to 1.
    """
    if not refs:
        return {}
    rows = db.execute(
        select(NodePointer.ref, func.count())
        .where(NodePointer.project_id == project_id, NodePointer.ref.in_(refs))
        .group_by(NodePointer.ref)
    ).all()
    return {ref: int(count) for ref, count in rows}


def _popularity_cutoff(db: Session, project_id: int) -> int | None:
    """Document frequency at POPULARITY_PERCENTILE across the project's tags.

    Nodes with a df ABOVE this are dropped from retrieval. Returns None when the
    project has fewer than _POPULARITY_MIN_NODES tags, where a percentile over a
    handful of values would cut real results for no reason.
    """
    pairs = (
        select(NodePointer.node_id, NodePointer.kind, NodePointer.ref)
        .where(NodePointer.project_id == project_id)
        .distinct()
        .subquery()
    )
    dfs = sorted(
        int(row[0])
        for row in db.execute(
            select(func.count()).select_from(pairs).group_by(pairs.c.node_id)
        ).all()
    )
    if len(dfs) < _POPULARITY_MIN_NODES:
        return None
    idx = max(0, math.ceil(POPULARITY_PERCENTILE * len(dfs)) - 1)
    return dfs[idx]


def rank_matches(
    db: Session, project_id: int, matches: list, query_text: str = ""
) -> list[tuple]:
    """Order matched nodes by specificity and drop the most popular tags.

    Takes the (node, neighbors) pairs from match_nodes and returns
    ``[(node, score), ...]`` best-first (score desc, then tag asc for a stable
    order). ``query_text`` supplies the term frequencies; omit it and every tag
    is scored as if mentioned once. The popularity cutoff is skipped when it
    would drop every match.
    """
    if not matches:
        return []
    total_docs = _corpus_doc_count(db, project_id)
    tf_by_tag = node_token_counts(query_text) if query_text else {}
    scored = [
        (
            node,
            specificity_score(
                node.tag, pointer_df(node), total_docs, tf_by_tag.get(node.tag, 1)
            ),
        )
        for node, _neighbors in matches
    ]
    cutoff = _popularity_cutoff(db, project_id)
    if cutoff is not None:
        kept = [(node, sc) for node, sc in scored if pointer_df(node) <= cutoff]
        if kept:
            scored = kept
    scored.sort(key=lambda pair: (-pair[1], pair[0].tag))
    return scored


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
    top_n: int = MAX_PER_GROUP,
) -> list[dict]:
    """Top-N memory-domain lessons relevant to an agent's assigned/queued tickets.

    Matches the concatenated title+description of the agent's todo/in_progress
    tickets against the node graph and keeps nodes grounded in the memory domain.
    Each lesson is POINTERS ONLY (no memory content - the TL already injects
    memory_full): tag, weight, score, the source agent, the memory.md ref, and the
    entry heading + date resolved from that file. The spawning agent's OWN memory
    is skipped (already in memory_full). Empty corpus / no tickets -> [].

    DWB-545: tags are ordered by specificity_score (rare + multi-part first) with
    the popularity cutoff applied, then interleaved BREADTH-FIRST across tags so
    top_n surfaces DIVERSE concepts rather than one tag repeated across every
    agent that happened to mention it.
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

    per_tag: list[list[dict]] = []
    seen: set[tuple[str, str]] = set()
    for node, score in rank_matches(db, project.id, matches, text):
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
                "score": round(score, 4),
                "source_agent": source_agent,
                "memory_ref": p.ref,
                "entry_heading": heading,
                "date": date,
            })
        if node_lessons:
            per_tag.append(node_lessons)

    cap = min(top_n, MAX_PER_GROUP)
    lessons: list[dict] = []
    depth = 0
    while len(lessons) < cap and any(depth < len(nl) for nl in per_tag):
        for nl in per_tag:
            if depth < len(nl):
                lessons.append(nl[depth])
                if len(lessons) >= cap:
                    break
        depth += 1
    return lessons


def _interleave(per_tag: list[list[dict]], cap: int) -> list[dict]:
    """Take entries BREADTH-FIRST across per-tag lists, best tag first.

    Straight concatenation lets the top tag spend the whole budget: "connection"
    grounds twenty frontend files, so ten slots became ten files of one concept.
    Round-robin gives the best tag its best entry, then the second tag its best,
    and so on, so a capped group spans as many distinct concepts as it has slots.
    """
    out: list[dict] = []
    depth = 0
    while len(out) < cap and any(depth < len(entries) for entries in per_tag):
        for entries in per_tag:
            if depth < len(entries):
                out.append(entries[depth])
                if len(out) >= cap:
                    break
        depth += 1
    return out


def related_nodes(
    db: Session,
    project,
    text: str,
    *,
    top_n: int = MAX_PER_GROUP,
) -> dict:
    """Related nodes for a piece of text (a ticket), grouped by domain (DWB-524).

    Runs the match service, ranks the matches by specificity (DWB-545), and
    buckets each matched node's pointers into lessons (memory), sessions
    (session), and code (code+doc file refs). Pointers only. ``query_tags`` is
    echoed for transparency; empty corpus -> empty groups.

    Two rules keep the output worth its tokens:
      - the code group is scored and deduped per FILE (one entry per file,
        anchored at its first line range and labelled with the best-ranked tag
        that grounds it), so ten code entries name ten places rather than ten
        lines of one file;
      - every group is capped at ``top_n`` (at most MAX_PER_GROUP), best-first.
    """
    query_tags, matches = match_nodes(db, project.id, text)
    repo_path = getattr(project, "repo_path", None)
    cap = min(top_n, MAX_PER_GROUP)

    lessons_by_tag: list[list[dict]] = []
    sessions_by_tag: list[list[dict]] = []
    # ref -> accumulated file score + the pointer/tag that best explains it.
    files: dict[str, dict] = {}

    for node, score in rank_matches(db, project.id, matches, text):
        rounded = round(score, 4)
        tag_lessons: list[dict] = []
        tag_sessions: list[dict] = []
        mentions: dict[str, list] = {}

        for p in node.pointers:
            if p.kind == NodePointerKind.memory:
                heading, date = _resolve_memory_entry(repo_path, p.ref, node.tag)
                tag_lessons.append({
                    "tag": node.tag, "weight": node.weight, "score": rounded,
                    "source_agent": _agent_from_memory_ref(p.ref),
                    "memory_ref": p.ref, "entry_heading": heading, "date": date,
                })
            elif p.kind == NodePointerKind.session:
                tag_sessions.append({
                    "tag": node.tag, "weight": node.weight, "score": rounded,
                    "ref": p.ref,
                })
            elif p.kind in (NodePointerKind.code, NodePointerKind.doc):
                entry = mentions.get(p.ref)
                if entry is None:
                    mentions[p.ref] = [p, 1]
                else:
                    entry[1] += 1
                    # Keep the FIRST line range as the file's anchor.
                    if (p.line_start or 0) < (entry[0].line_start or 0):
                        entry[0] = p

        # Score FILES, not tag hits. A file's relevance is how much of the
        # query's specific vocabulary it carries: every matched tag contributes
        # its score, damped by how often the file mentions it. The file that
        # carries the most of the ticket's concepts wins, which is the file an
        # agent should actually open - a tag-first ordering instead spent all ten
        # slots on whichever files the single top tag happened to touch.
        for ref, (p, count) in mentions.items():
            contribution = score * (1.0 + math.log(count) if count > 1 else 1.0)
            slot = files.get(ref)
            if slot is None:
                files[ref] = {
                    "score": contribution, "pointer": p, "tag": node.tag,
                    "weight": node.weight, "best": score,
                }
            else:
                slot["score"] += contribution
                # The label stays the best-ranked tag that grounds this file.
                if score > slot["best"]:
                    slot.update(pointer=p, tag=node.tag, weight=node.weight, best=score)

        if tag_lessons:
            lessons_by_tag.append(tag_lessons)
        if tag_sessions:
            sessions_by_tag.append(tag_sessions)

    # Pivoted length normalization: divide out the file's size so a sprawling
    # doc cannot outrank a focused source file just by mentioning more things.
    lengths = _file_lengths(db, project.id, list(files))
    for ref, slot in files.items():
        length = max(lengths.get(ref, 1), 1)
        slot["score"] /= length ** LENGTH_NORMALIZATION_EXPONENT

    code = [
        {
            "tag": slot["tag"], "weight": slot["weight"],
            "score": round(slot["score"], 4),
            "kind": slot["pointer"].kind.value, "ref": ref,
            "sha": slot["pointer"].sha,
            "line_start": slot["pointer"].line_start,
            "line_end": slot["pointer"].line_end,
        }
        for ref, slot in sorted(
            files.items(), key=lambda kv: (-kv[1]["score"], kv[0])
        )
    ]

    return {
        "query_tags": query_tags,
        "lessons": _interleave(lessons_by_tag, cap),
        "sessions": _interleave(sessions_by_tag, cap),
        "code": code[:cap],
    }
