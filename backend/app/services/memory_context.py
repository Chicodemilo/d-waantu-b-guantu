# Path: app/services/memory_context.py
# File: memory_context.py
# Created: 2026-09-30 (DWB-610)
# Purpose: Assemble a human_memory agent's scored memory into the text injected
#          at spawn and SessionStart, replacing the sealed pointer with real
#          content: full text for band 8-10, the author's stored `condensed`
#          line for band 5-7, and the author's keywords per row for the 2-4
#          and 1 bands. The single caller both injection sites route through
#          (app/services/memory_mode.memory_full_for).
# Caller: app/services/memory_mode.py
# Callees: app/services/memory_score.py (the derived score, the single scoring
#          read path), app/services/memory_format.py (the existing band
#          renderer - DWB-594's MemoryEntry/render, reused rather than
#          reimplemented)
# Data In: db: Session, agent: Agent
# Data Out: str | None - None means "nothing scored yet", the caller's cue to
#           fall back to the sealed pointer rather than inject an empty block
# Last Modified: 2026-10-08 (DWB-659: the 2-4 and 1 bands render each row's id
#                and keywords instead of a bare aggregate count, bounded per
#                band, with NULL keywords distinguished from empty ones.
#                Previous entry: DWB-658: the 5-7 band carries the author's
#                stored `condensed` instead of a truncation of the body's
#                first line. `_one_line` and `_ONE_LINE_CHARS` are DELETED,
#                not left unused, so no second path can silently work)

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
business, not the agent's.

THAT LAST CLAUSE USED TO END "they are counted, not read", AND DWB-659 CHANGED
IT. The boundary it draws is intact - those two bands still carry no bodies and
no condensed lines - but a bare count turned out to serve the rule badly: an
agent told only "6 demotion candidates" cannot tell what it is about to lose,
which is the one thing the bottom bands exist to warn it about. They now carry
each row's id and the author's keywords, bounded per band. Updated here rather
than left standing, because a docstring that describes a mechanism by what it
does NOT do is exactly the kind that goes quietly false the day it ships.

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

WHAT DWB-658 CHANGED, AND WHAT IT DID NOT: the 5-7 band now renders the
author's stored `condensed` column instead of a truncation of the body's first
line, and `_one_line` is deleted rather than left unused. The band boundaries,
the scoring, the 8-10 renderer and this module's scope are all untouched. See
`_condensed_line` for the reasoning and for the fallback's removal condition.

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

# Marks a 5-7 line that the AUTHOR DID NOT WRITE. See `_condensed_line`.
_LEGACY_EXCERPT_NOTE = "[auto-excerpt, not the author's line]"

# A DISPLAY BOUND ON WHATEVER LINE WE RENDER, AND IT IS NOT THE THING DWB-658
# DELETED. The distinction is the whole point, so it is written out rather
# than assumed:
#
#   - Truncating a BODY to manufacture a one-liner is what `_one_line` did and
#     what this ticket killed. It can cut before the lesson arrives, so it
#     changes WHICH IDEA the band carries. Never do that again.
#   - Bounding a line that has ALREADY been chosen as the lesson - by its
#     author, or by the fallback - loses a tail. It cannot swap the setup in
#     for the point, because the point was picked before this ran.
#
# Needed because the write gate (DWB-657) deliberately applies NO character
# cap: a count is a proxy for "carries the lesson not the setup" and is wrong
# in both directions, refusing a good 200-character lesson while passing a
# useless 60-character one. That ruling is correct for the GATE and it leaves
# an author free to paste a whole body into `condensed`, which would defeat
# the only reason the 5-7 band is abbreviated. Bounding for display is this
# module's job, not the gate's.
#
# 400 is deliberately generous. A real one-line lesson runs 60-180 characters,
# so nothing honest is touched and only a pasted body is cut.
_RENDERED_LINE_CHARS = 400


def _condensed_line(entry: dict) -> str:
    """The one line band 5-7 carries for a memory: the author's stored
    `condensed` when there is one, the body's first line when there is not.

    WHY THE STORED LINE AND NOT A TRUNCATION (DWB-658). The deleted
    `_one_line` took the body's first non-blank line and cut it at 160
    characters. That is correct exactly when the first line IS the lesson. For
    a memory that opens with setup and lands the point three sentences in, it
    carried the setup, dropped the lesson, and still read as a summary - a
    display that looks identical whether it worked or not, which is this
    project's recurring defect rather than a new one. `condensed` is supplied
    by the author at write time (DWB-657 refuses a write without it) precisely
    because only the author knows which sentence is the point.

    THIS IS A QUALITY CHANGE, NOT A PERFORMANCE ONE. Assembly is microseconds
    over a handful of rows. Nothing here is a cache and nothing here should be
    turned into one.

    THE FALLBACK IS A TEMPORARY BRIDGE, NOT INTENDED BEHAVIOUR, AND IT IS
    MARKED IN THE OUTPUT ON PURPOSE. All 832 rows that existed when DWB-658
    landed have NULL `condensed`, because 654 had to land the column nullable
    to migrate against them at all. Those rows must still serve - an agent
    does not stop having memory because a column is new - so they fall back to
    the body's first line.

    But an UNMARKED fallback would reproduce the exact bug this ticket exists
    to fix, silently, on every one of those rows: the reader would have no way
    to tell an author's lesson from a machine's guess at one, which is the
    same two-realities-one-answer shape named above. So a fallback line carries
    `_LEGACY_EXCERPT_NOTE` and an author's line carries nothing. Cheap, and it
    makes the band honest while the backfill is still outstanding.

    REMOVAL CONDITION, written down so the next reader does not preserve this
    as a feature: DWB-655 backfills the existing rows and DWB-656 flips both
    columns to NOT NULL. Once 656 has landed, no row can reach this function
    with a NULL `condensed` by any path, and the entire fallback branch plus
    `_LEGACY_EXCERPT_NOTE` should be deleted rather than kept "just in case".
    If it is still here after 656, that is the dead defensive code this
    codebase keeps accumulating, and deleting it is the correct action.

    BOTH PATHS ARE BOUNDED FOR DISPLAY, and that is not a reinstatement of
    `_one_line`. See `_RENDERED_LINE_CHARS` for why the two are different acts:
    this bound is applied AFTER the lesson has been chosen, so it can shorten
    a line but can never substitute the setup for the point. The write gate
    deliberately caps nothing, which is correct for the gate and is exactly
    what leaves this module holding the budget.
    """
    condensed = (entry.get("condensed") or "").strip()
    if condensed:
        return _bounded(condensed)

    for line in (entry.get("body") or "").splitlines():
        stripped = line.strip().lstrip("-*+").strip()
        if stripped:
            return f"{_bounded(stripped)} {_LEGACY_EXCERPT_NOTE}"
    return ""


def _bounded(line: str) -> str:
    """Cut an already-chosen line to the display bound, marking the cut.

    The ellipsis matters: a silently cut line reads as a complete thought that
    simply ends oddly, which is the same "looks like it worked" problem in
    miniature. A reader should be able to tell the tail is missing.
    """
    if len(line) <= _RENDERED_LINE_CHARS:
        return line
    return line[: _RENDERED_LINE_CHARS - 1].rstrip() + "…"


# --- bands 2-4 and 1 (DWB-659) ------------------------------------------
#
# THE BUDGET IS THE POINT. These bands are abbreviated BECAUSE they are low
# value - 2-4 is flagged for demotion and 1 is the last pass before eviction.
# DWB-659 makes them inspectable, not readable: an agent should be able to
# tell what it is about to lose without paying anything like full-text weight
# for it. Keywords per row, never bodies and never condensed lines.
#
# Each bucket gets its OWN cap rather than sharing one pool. A shared pool
# sorted demote-first would let fifty demotion candidates crowd out three
# eviction rows, and the eviction rows are the urgent ones - they are the
# memories actually about to go. A per-bucket cap cannot starve either side.
_FLAGGED_ROWS_PER_BAND = 4
# A keyword list is two or three short terms by DWB-657's write rule. These
# two bounds are not a display policy, they are a guard against a malformed
# row: the column is JSON and nothing constrains its contents until DWB-656,
# so a single pathological row must not be able to blow the context budget.
_KEYWORDS_PER_ROW = 5
_KEYWORD_CHARS = 40

# WHY TWO DIFFERENT EMPTY STATES, SPELLED OUT RATHER THAN BLANK. A blank
# entry reads as "this memory has no keywords". For every row written before
# DWB-657 that is false: nobody was ever ASKED for any. Those are different
# facts about different realities and a display that gives one answer for both
# is the failure this codebase keeps shipping. NULL means we do not know;
# a chosen state gets a named value.
#
# WHICH OF THESE IS ACTUALLY REACHABLE, MEASURED RATHER THAN ASSUMED (Barry,
# five probes against the live DWB-657 gate): `[]`, `[""]`, a blank
# `condensed` and an omitted `condensed` are all refused 400, and a
# comma-joined string is a 422. In the live table: 832 rows with keywords
# NULL, ZERO rows with keywords `[]`. So through the API, NULL is the only
# empty state that exists today, and it means exactly "written before anyone
# was asked".
#
# `[]` is kept handled anyway because it is STORABLE at the database level -
# unreachable from outside is not the same as impossible, and a careless
# DWB-655 backfill is the realistic way the first one appears. That is a
# cheap branch against a state that would otherwise render as a bare blank.
#
# RETIREMENT: after DWB-655 backfills and DWB-656 flips both columns NOT NULL,
# NULL stops being reachable and `_KEYWORDS_NEVER_ASKED` becomes dead. Remove
# it deliberately then rather than letting it be found later.
#
# ONE CAVEAT ON THAT RETIREMENT, because it is not purely a backfill question:
# `memory_promote.py` and `memory_decide.py` both construct AgentMemory
# without either field and are not behind the write gate, so machine-minted
# rows with NULL keywords may keep arriving after the backfill. That is parked
# for Miles and is not this ticket's problem, but it means the NULL branch may
# outlive 656 - check before deleting it.
_KEYWORDS_NEVER_ASKED = "(no keywords - predates the field, nobody was asked)"
_KEYWORDS_RECORDED_EMPTY = "(keywords recorded, but empty)"


def _keywords_line(entry: dict) -> str:
    """The keywords for one flagged row, bounded, with the two empty states
    kept distinct. See the constants above for why that distinction exists.
    """
    keywords = entry.get("keywords")
    if keywords is None:
        return _KEYWORDS_NEVER_ASKED

    # `keywords` is a JSON column, so until DWB-656 constrains it anything
    # JSON can hold is reachable by a raw write. A bare string is the likely
    # shape of a mistake and is worth rendering rather than discarding; it is
    # wrapped rather than iterated, because iterating a string would render
    # it one character per keyword.
    if isinstance(keywords, str):
        keywords = [keywords]
    elif not isinstance(keywords, list):
        keywords = [str(keywords)]

    terms = [str(k).strip() for k in keywords]
    terms = [t for t in terms if t]
    if not terms:
        return _KEYWORDS_RECORDED_EMPTY

    shown = [t[:_KEYWORD_CHARS] for t in terms[:_KEYWORDS_PER_ROW]]
    line = ", ".join(shown)
    if len(terms) > _KEYWORDS_PER_ROW:
        line += f", +{len(terms) - _KEYWORDS_PER_ROW} more"
    return line


def _flagged_band(heading: str, rows: list[dict]) -> list[str]:
    """One bucket of the flagged section: a heading carrying the TRUE total,
    then up to `_FLAGGED_ROWS_PER_BAND` rows of keywords.

    The count in the heading is the full bucket size, not the number shown, so
    the section never understates what is at stake just because it is bounded.
    """
    if not rows:
        return []

    out = [f"{heading} - {len(rows)}:"]
    for entry in rows[:_FLAGGED_ROWS_PER_BAND]:
        out.append(f"- #{entry['id']}  {_keywords_line(entry)}")
    hidden = len(rows) - _FLAGGED_ROWS_PER_BAND
    if hidden > 0:
        out.append(f"- ... {hidden} more not shown")
    return out


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
    # DWB-659: the ROWS, not `result["demote"]` / `result["evict"]`, which are
    # id lists and carry no keywords. Membership is identical - scored_memory
    # builds those two lists with exactly this band predicate over exactly
    # this `entries` list - so this is the same set reached by a path that
    # still has the row on it, not a second opinion about which rows qualify.
    demote = [
        e for e in entries if e["band"] == memory_score.BAND_DEMOTION_CANDIDATE
    ]
    evict = [
        e for e in entries if e["band"] == memory_score.BAND_LAST_CONSOLIDATION
    ]

    if not full and not compressed and not demote and not evict:
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
        lines = "\n".join(f"- {_condensed_line(e)}" for e in compressed)
        sections.append("## Memory - compressed (score 5-7)\n" + lines)

    if demote or evict:
        lines = ["## Memory flagged for consolidation (not carried in full)"]
        lines += _flagged_band("Demotion candidates (score 2-4)", demote)
        lines += _flagged_band("Last pass before eviction (score 1)", evict)
        lines.append(f"See GET /api/agents/{agent.id}/memory/scored.")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)
