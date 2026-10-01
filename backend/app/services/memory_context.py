# Path: app/services/memory_context.py
# File: memory_context.py
# Created: 2026-09-30 (DWB-610)
# Purpose: Assemble a human_memory agent's scored memory into the text injected
#          at spawn and SessionStart, replacing the sealed pointer with real
#          content: full text for band 8-10, one line for band 5-7, a count
#          for what is flagged below that. The single caller both injection
#          sites route through (app/services/memory_mode.memory_full_for).
# Caller: app/services/memory_mode.py
# Callees: app/services/memory_score.py (the derived score, the single scoring
#          read path), app/services/memory_format.py (the existing band
#          renderer - DWB-594's MemoryEntry/render, reused rather than
#          reimplemented)
# Data In: db: Session, agent: Agent
# Data Out: str | None - None means "nothing scored yet", the caller's cue to
#           fall back to the sealed pointer rather than inject an empty block
# Last Modified: 2026-09-30 (DWB-610)

"""The wiring DWB-610 was filed to close.

The 2026-09-30 human_memory audit found two things that both existed and never
met: `memory_score.scored_memory` computes a derived score and a band for
every memory, and `memory_format.render` already knows how to turn a list of
memory entries back into text. Nothing called the second with the first's
output. An agent in `human_memory` mode got `STOCK_MEMORY_SEALED_POINTER` at
both spawn (`agent.py:390`) and SessionStart (`hooks.py:65`) instead - a
pointer to the write/read endpoints, carrying zero memory content.

Miles's rule, restated here because it is the acceptance bar: memories scoring
8-10 arrive as full text, 5-7 get one line, 2-4 and 1 are consolidation's
business, not the agent's - they are counted, not read.

SCOPE, KEPT DELIBERATELY NARROW: this is wiring, not a new format. The band
boundaries live in `memory_score.py` (BAND_FULL_TEXT etc.) and stay there;
this module does not re-derive them. The text rendering for band 8-10 is
`memory_format.render`, unmodified; this module does not re-implement a
markdown writer. What this module owns is the one decision neither of those
had to make: how the three treatments combine into one string for a context
window.

WHY body LIVES ON THE SCORE RESPONSE NOW (DWB-610 amendment): `scored_memory`
used to return everything BUT the content - id, tier, band, score, and not the
one field this ticket needs. The alternative was a second query against
`agent_memories` keyed on the ids the score endpoint already resolved: two
reads of the same rows, which is the exact "two stores that both look
authoritative" failure section 7 opens with, just moved from write-time to
read-time. `body` was added to `ScoredMemoryEntry` instead, so there is one
read path for score and content together.

WHY `None` (NOT an empty string) MEANS "NOTHING SCORED YET": a project can be
in human_memory mode with zero tiered memories - freshly adopted, or a new
agent with nothing written. Injecting an empty block would look like a bug;
falling back to the sealed pointer says truthfully that the mode is on and
there is nothing to serve yet. The caller (`memory_mode.memory_full_for`)
makes that fallback decision; this module only reports what it has.
"""

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.services import memory_format, memory_score

# How much of a compressed (band 5-7) entry's body to show on its one line.
# Long enough to be recognisable, short enough that ten of them do not become
# the flood top-off was built to avoid (spec section 8's reasoning, carried
# over: a compressed band exists so the agent knows the lesson is there
# without paying full-text weight for it).
_ONE_LINE_CHARS = 160


def _one_line(body: str) -> str:
    """The first non-blank line of a memory body, collapsed and capped.

    Not `memory_format.split` - that module's job is round-tripping memory.md
    on disk, and this is a display truncation of already-known content, a
    different operation that would only borrow the wrong tool from that file.
    """
    for line in body.splitlines():
        stripped = line.strip().lstrip("-*+").strip()
        if stripped:
            if len(stripped) > _ONE_LINE_CHARS:
                return stripped[: _ONE_LINE_CHARS - 1].rstrip() + "…"
            return stripped
    return ""


def assemble_session_context(db: Session, agent: Agent) -> str | None:
    """The human_memory injection payload for one agent, or None if there is
    nothing scored to serve.

    Called with the SPECIFIC agent whose session is starting - the TL at
    SessionStart, the named worker at spawn-prepare - never a stand-in. Each
    agent's memory is scoped to `agent_id` throughout `agent_memories`, so
    serving anyone else's scored memory here would be handing an agent a
    colleague's lessons under its own name.
    """
    result = memory_score.scored_memory(db, agent_id=agent.id)
    if not result["computed"]:
        # Not human_memory, or the agent has no project. Both mean this
        # function has nothing to contribute; the caller decides what to show
        # instead (memory_mode only calls here when it already knows the
        # project is human_memory, so `computed: False` here means the agent
        # itself is unscoped - report nothing rather than guess).
        return None

    entries = result["entries"]
    full = [e for e in entries if e["band"] == memory_score.BAND_FULL_TEXT]
    compressed = [e for e in entries if e["band"] == memory_score.BAND_COMPRESSED]
    demote_count = len(result["demote"])
    evict_count = len(result["evict"])

    if not full and not compressed and not demote_count and not evict_count:
        return None

    sections: list[str] = []

    if full:
        # Reuse the existing renderer rather than hand-building markdown here
        # - DWB-594's `render` is the one place that turns MemoryEntry back
        # into memory.md-shaped text, and a second implementation is exactly
        # the drift the format module exists to prevent (see its own
        # docstring: "a splitter and a renderer that agree are the only proof
        # either is right").
        rendered = memory_format.render(
            [memory_format.MemoryEntry(body=e["body"]) for e in full]
        )
        sections.append(
            "## Memory - full text (score 8-10)\n" + rendered
        )

    if compressed:
        lines = "\n".join(f"- {_one_line(e['body'])}" for e in compressed)
        sections.append("## Memory - compressed (score 5-7)\n" + lines)

    if demote_count or evict_count:
        sections.append(
            "## Memory flagged for consolidation (not carried in full)\n"
            f"{demote_count} demotion candidate(s), {evict_count} at last pass "
            f"before eviction. See GET /api/agents/{agent.id}/memory/scored."
        )

    return "\n\n".join(sections)
