# Path: app/services/memory_revert.py
# File: memory_revert.py
# Created: 2026-09-30 (DWB-595)
# Purpose: The REVERT flow - render agent_memories back to a stock memory.md
#          ordered by tier then score, journaling everything that will not fit
#          BEFORE it is dropped. The journal itself survives untouched.
# Caller: DWB-595's revert endpoint / the reverting transition
# Callees: app/services/memory_format (the shared renderer),
#          app/services/memory_score (the one decay curve),
#          app/config/token_budget (the one ceiling)
# Data In: db Session, Project
# Data Out: RevertPlan per agent (kept, dropped, rendered text)
# Last Modified: 2026-10-01 (DWB-617: ceiling cited by name, not by a stale number;
#                DWB-611: scar_context_bound collapsed into scar -
#                one scar heading and one slot in _TIER_ORDER, not two)

"""Render the store back to a flat file, losing only what will not fit.

THE CEILING IS THE WHOLE PROBLEM. Stock memory caps at memory_main (see
config/token_budget.py) and the
store has no such limit, so a revert is lossy BY CONSTRUCTION and the only
question is whether the loss is controlled. What does not fit is dropped
LOWEST SCORE FIRST, and everything dropped is written to the journal before it
leaves.

ORDER MATTERS AND IT IS TESTABLE. Spec section 7 hard rule 4: "Anything leaving
memory lands in the journal first. Journal, then rewrite. Losing it in flight is
the one unrecoverable mistake in the design." So every drop is journaled first,
and the FILE IS WRITTEN LAST - after every journal entry for that agent has
landed. A crash anywhere in between loses nothing: the store is still intact,
the flat file is still the old one, and the journal has gained entries that are
merely early.

THE JOURNAL SURVIVES FROZEN AND UNTOUCHED (ruled by Miles). This module only
ever APPENDS to it. Not deleted, and not flattened into the file, and the
reasoning belongs here as much as in the ticket: DELETING loses content
outright, and FLATTENING blows the memory.md ceiling instantly because the
journal sprawls by design. Section 5: "Memory must shrink; the journal may
sprawl. Opposite pressures, which is precisely why they are two stores and not
one." Pouring the sprawling store into the shrinking one is the one combination
guaranteed to fail.

Frozen means a later re-adopt gets it back intact, which is what makes revert a
reversible decision rather than a destructive one.

TIERING IS LOST, and that is the documented cost rather than a defect. The
toggle warning already says switching back "loses the tiering"; this module is
what makes that warning true. Tier survives only as the section heading a lesson
is rendered under, which a re-adopt will read as a heading and not as a tier -
correctly, because a tier that survived a round trip would be a judgement nobody
made on the way back.

IT DOES NOT RENDER OVER CONTENT IT NEVER CARRIED (TL ruling, 2026-09-30). A
lesson skipped during the adopt has no row in the store, so it is not rendered,
and writing this file would otherwise overwrite the intact original without it -
the recovery path becoming the deletion. That is closed on the ADOPT side, where
every skip is journaled before the row goes terminal (DWB-594's decide path), so
nothing reaches this point unpreserved. The guard here is the assertion in
`plan`: a revert on a project whose adopt skipped entries still finds them in the
journal, because that is where they were put.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.token_budget import ceiling_for_file, estimate_tokens
from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.services import memory_format
from app.services import memory_score

# Tier order in the rendered file. CORE first because it never fades and is
# what a reader most needs at the top; `raw` last because it is the absence of
# a judgement, not a tier, and a reverting project may still hold rows that
# consolidation never reached.
#
# DWB-611: one SCAR slot, not two. `scar_context_bound` collapsed into `scar` -
# Miles's ruling is four buckets, all scars context-bound, so a row's
# context_key (set or not) is no longer a different TIER, just a column that
# may or may not be populated on the one scar tier there is.
_TIER_ORDER: list[MemoryTier] = [
    MemoryTier.core,
    MemoryTier.scar,
    MemoryTier.working,
    MemoryTier.raw,
]

_TIER_HEADING = {
    MemoryTier.core: "CORE",
    MemoryTier.scar: "SCAR",
    MemoryTier.working: "WORKING",
    MemoryTier.raw: "UNSORTED",
}

# What a `raw` row scores for ordering. `memory_score.score` REFUSES raw - it
# has no curve because it has no tier yet - so the sort needs its own answer
# rather than crashing or silently skipping the row. Below every real score, so
# untiered rows are the first to be dropped for space: they are the ones no
# judgement was ever made about, which makes them the cheapest to lose and the
# ones most likely to be noise.
_RAW_SORT_SCORE = -1

JOURNAL_TAGS_DROPPED = ["revert", "dropped-for-space"]


@dataclass
class AgentRevert:
    """One agent's revert: what survived, what did not, and the file to write."""

    agent_id: int
    agent_name: str
    path: Path
    kept: list[AgentMemory] = field(default_factory=list)
    dropped: list[AgentMemory] = field(default_factory=list)
    rendered: str = ""

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


@dataclass
class RevertPlan:
    agents: list[AgentRevert] = field(default_factory=list)

    @property
    def total_dropped(self) -> int:
        return sum(a.dropped_count for a in self.agents)


def _memory_md_path(project: Project, agent: Agent) -> Path:
    base = (project.repo_path or ".").rstrip("/")
    return Path(base) / ".dwb" / "memory" / project.prefix / agent.name / "memory.md"


def _sort_score(db: Session, memory: AgentMemory) -> int:
    if memory.tier == MemoryTier.raw:
        return _RAW_SORT_SCORE
    since = memory_score.sessions_since_reinforced(db, memory)
    # None means the row has no clock origin. Treated as maximally decayed for
    # ORDERING only: a memory nobody can date is the weakest claim on limited
    # space, and inventing a fresh score for it would let an undatable row
    # displace one with real evidence behind it.
    return memory_score.score(memory.tier, since if since is not None else 10_000)


def _entry_for(memory: AgentMemory) -> memory_format.MemoryEntry:
    return memory_format.MemoryEntry(
        body=memory.body,
        heading_path=(_TIER_HEADING[memory.tier],),
        kind="bullet",
    )


def _render(memories: list[AgentMemory]) -> str:
    return memory_format.render([_entry_for(m) for m in memories])


def plan(db: Session, project: Project) -> RevertPlan:
    """Work out, per agent, what fits and what has to go. Writes NOTHING.

    Ordered by tier, then by score descending, then by id so the result is
    deterministic when scores tie - without that last key the same store could
    render two different files and a re-adopt would enumerate different
    candidates each time.

    Dropping is lowest-score-first, which is the reverse of the render order, so
    the entries that go are the ones the decay curve already says are closest to
    leaving anyway.
    """
    result = RevertPlan()
    ceiling = ceiling_for_file("memory.md")

    agents = (
        db.execute(
            select(Agent)
            .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
            .where(ProjectAgent.project_id == project.id)
            .where(Agent.is_active.is_(True))
            .order_by(Agent.id.asc())
        )
        .scalars()
        .all()
    )

    for agent in agents:
        memories = list(
            db.execute(
                select(AgentMemory).where(AgentMemory.agent_id == agent.id)
            )
            .scalars()
            .all()
        )
        scored = [(m, _sort_score(db, m)) for m in memories]
        # Render order: tier, then score desc, then id for determinism.
        scored.sort(
            key=lambda pair: (
                _TIER_ORDER.index(pair[0].tier),
                -pair[1],
                pair[0].id,
            )
        )
        # Kept in RENDER order, carrying each score so the drop loop does not
        # have to recompute or look one up.
        remaining = list(scored)
        dropped: list[AgentMemory] = []

        # Drop lowest score first until it fits. The size is recomputed each
        # pass rather than estimated once, because the renderer emits a heading
        # only when the tier CHANGES: removing the last entry of a tier removes
        # its heading too, so a single up-front calculation would drop more
        # than necessary.
        while remaining and estimate_tokens(
            _render([m for m, _s in remaining])
        ) > ceiling:
            # Lowest score wins; ties broken by position so the drop comes off
            # the END of the render order. Without that tie-break the choice
            # among equal scores depends on list order and the same store could
            # render two different files.
            worst = min(
                range(len(remaining)), key=lambda i: (remaining[i][1], -i)
            )
            dropped.append(remaining.pop(worst)[0])

        kept = [m for m, _s in remaining]

        result.agents.append(
            AgentRevert(
                agent_id=agent.id,
                agent_name=agent.name,
                path=_memory_md_path(project, agent),
                kept=kept,
                dropped=dropped,
                rendered=_render(kept),
            )
        )

    return result


def _journal_dropped(db: Session, agent_revert: AgentRevert) -> None:
    """Write every dropped memory to the journal. Called BEFORE the file write.

    Append-only, like every other journal write in this system. The journal is
    never read, rewritten or emptied here: it survives a revert frozen and
    intact, which is what makes a later re-adopt able to get this content back.
    """
    for memory in agent_revert.dropped:
        db.add(
            JournalEntry(
                agent_id=memory.agent_id,
                tags=list(JOURNAL_TAGS_DROPPED),
                body=memory.body,
            )
        )


def execute(db: Session, project: Project) -> RevertPlan:
    """Journal what will not fit, then write each agent's flat file.

    THE ORDER IS THE CONTRACT. Every journal entry for an agent is flushed
    BEFORE that agent's file is written, so a failure at any point leaves the
    store intact, the old flat file intact, and at worst some journal entries
    that are merely early. The one unrecoverable outcome - content gone from
    both stores - is unreachable.

    Does not commit and does not change `memory_mode`: DWB-593's edges own the
    mode, and the caller owns the transaction.
    """
    result = plan(db, project)

    for agent_revert in result.agents:
        _journal_dropped(db, agent_revert)
        # Flushed before the write, per hard rule 4. Not merely added: an
        # unflushed add is still only in the session, and the file write below
        # touches the filesystem, which no transaction can undo.
        db.flush()

        agent_revert.path.parent.mkdir(parents=True, exist_ok=True)
        agent_revert.path.write_text(agent_revert.rendered, encoding="utf-8")

    return result
