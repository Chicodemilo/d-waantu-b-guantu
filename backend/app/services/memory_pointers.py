# Path: app/services/memory_pointers.py
# File: memory_pointers.py
# Created: 2026-10-28 (DWB-692)
# Purpose: Ground the node graph's MEMORY domain on the corpus that is actually
#          live. On a human_memory project that is the `agent_memories` rows; on
#          a stock project it is still the on-disk memory.md files, and this
#          module delegates there untouched. Registered over node_touch's
#          file-only default via register_source_provider('memory', ...).
# Caller: imported at app startup (app/main.py) for the registration side effect
# Callees: app/services/node_touch (register_source_provider, memory_provider),
#          app/services/memory_mode (is_human_memory), app/models (AgentMemory,
#          Agent)
# Data In: db: Session, project, repo_path
# Data Out: list[SourceUnit] with kind="memory"
# Last Modified: 2026-10-28 (DWB-692)

"""DWB-692: the memory index pointed at files nobody is allowed to read.

THE DEFECT, WITH ITS NUMBERS. `node_touch.memory_provider` globs
`<repo>/.dwb/memory/<prefix>/*/memory.md` and nothing ever overrode it. Measured
on a running instance on 2026-10-28, by importing `app.main` and reading the
assembled registry rather than by grepping for the call:

    code    -> code_pointers.code_provider   [OVERRIDE]
    doc     -> doc_pointers.doc_provider     [OVERRIDE]
    memory  -> node_touch.memory_provider    [default]

And the index those files produced, read out of the pointer table rather than
inferred from the provider: 3,479 memory-kind pointers across 15 distinct refs,
every one a `.md` path, ZERO referencing a row. Meanwhile the live corpus on the
three human_memory projects is 1,221 `agent_memories` rows that nothing indexes.
On DWB those files last changed 2026-10-01 and are SEALED under DWB-589, so
every pointer retrieval returned named a frozen file agents are forbidden to
open.

Note the shape, because it is the reason this survived: the provider ran,
succeeded, and returned units. Nothing errored. The lane was loudest about being
healthy exactly where it was most wrong.

A STOCK PROJECT IS NOT AFFECTED AND IS NOT TOUCHED. This is the constraint the
whole change hangs on and it is why this is a mode-aware override rather than a
replacement. Scoped per project on 2026-10-28:

    DWB   human_memory  598 rows   8 files (2026-10-01)  AFFECTED
    IND   human_memory  615 rows   7 files (2026-10-06)  AFFECTED
    T650  human_memory    8 rows   0 files               AFFECTED (empty, not stale)
    CI    stock            0 rows  8 files (2026-10-26)  correct as built
    D2J / RVP / GSF  stock, with real content in those files
    DEMO / SLT / SL2 / AIC / T650S  no memory either way

For the four stock projects the FILE IS THE LIVE CORPUS and the old provider is
exactly right - CI's files were written two days before this was written. A
global swap would have broken four working projects to fix three. T650 is a
third flavour worth naming: human_memory with no files at all, so the old
provider returned `[]` and succeeded, and its memory domain was empty rather
than stale.

GROUNDED ON `condensed`, NOT `body`, AND THE COST IS WHY BUT NOT ONLY WHY.
Measured with the real tokenizer before building: `condensed` yields ~15.4k
pointers across DWB and IND (4.4x the current 3,479) where `body` yields ~46k
(13x). That matters against `relevant_lessons`' 5s budget and `node_match`'s
107-second incident. But the better argument is what the field IS: one line, the
author's own summary of the lesson, mandatory non-blank since DWB-657 and
written to be read. Widening to include bodies later is a one-line change;
narrowing after the index has grown is not.

THE REF CARRIES THE AGENT, DELIBERATELY, AND THAT IS NOT COSMETIC.
`node_retrieval._agent_from_memory_ref` derives `source_agent` by taking the
PARENT DIRECTORY of the ref. A bare row id would have returned None there and
every retrieved lesson would have come back with `source_agent: null` - no
error, no empty list, just a quietly unattributed answer. So the ref keeps a
path shape, `agent_memories/<PREFIX>/<AgentName>/<row id>`, and that helper
reads the agent out of it unchanged. `memory_id_from_ref` below is the other
half, for callers that want the row back.

CROSS-AGENT RETRIEVAL IS NOT A NEW EXPOSURE, which was checked rather than
assumed before this was built. `relevant_lessons` already returns OTHER agents'
lessons - all 3,479 existing pointers name another agent's file - and the
payload has always carried `source_agent` so attribution survives. DWB-630
sealed reading the FILE; it did not rule that a lesson may not reach another
agent. This continues the existing design on a different storage shape.

WHAT THIS MODULE DOES NOT DO. It does not change the spawn payload. A
row-grounded pointer is what MAKES `relevant_lessons` able to carry a lesson's
`condensed` line, which is DWB-685's acceptance criterion, but delivering it is
that ticket's job and not this one's. This lane fixes WHAT IS INDEXED.
"""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import memory_mode
from app.services.node_registry import SourceUnit

# The ref prefix that marks a pointer as row-grounded rather than file-grounded.
# Kept path-shaped on purpose - see the module docstring on `_agent_from_memory_ref`.
ROW_REF_ROOT = "agent_memories"

# Tiers worth indexing. `raw` is excluded because it is the untiered state a row
# is written in before consolidation has judged it, so indexing it would surface
# lessons the system has not yet decided are lessons.
_INDEXED_TIERS = (MemoryTier.core, MemoryTier.scar, MemoryTier.working)


def row_ref(project_prefix: str, agent_name: str, memory_id: int) -> str:
    """The ref for one memory row: `agent_memories/<PREFIX>/<Agent>/<id>`."""
    return f"{ROW_REF_ROOT}/{project_prefix}/{agent_name}/{memory_id}"


def memory_id_from_ref(ref: str) -> int | None:
    """The row id a row-grounded ref points at, or None if it is not one.

    Returns None rather than raising for a file ref, because both shapes are
    live at once: stock projects still ground on `.dwb/memory/.../memory.md`.
    """
    if not ref or not ref.startswith(f"{ROW_REF_ROOT}/"):
        return None
    try:
        return int(Path(ref).name)
    except (ValueError, TypeError):
        return None


def _row_units(db: Session, project) -> list[SourceUnit]:
    """One SourceUnit per indexable memory row on this project."""
    agents = list(
        db.execute(select(Agent).where(Agent.project_id == project.id))
        .scalars()
        .all()
    )
    if not agents:
        return []
    by_id = {a.id: a for a in agents}

    rows = list(
        db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.agent_id.in_(list(by_id)),
                AgentMemory.tier.in_(_INDEXED_TIERS),
            )
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )

    prefix = getattr(project, "prefix", None) or "?"
    units: list[SourceUnit] = []
    for row in rows:
        text = (row.condensed or "").strip()
        if not text:
            # Pre-DWB-657 rows carry no condensed line. Skipped rather than
            # falling back to `body`: the fallback would silently index a
            # different field for part of the corpus, and the resulting mix
            # would be impossible to tell apart at any later read.
            continue
        agent = by_id.get(row.agent_id)
        name = getattr(agent, "name", None) or str(row.agent_id)
        units.append(
            SourceUnit(
                kind="memory",
                ref=row_ref(prefix, name, row.id),
                text=text,
            )
        )
    return units


def memory_provider(db: Session, project, repo_path: str) -> list[SourceUnit]:
    """Mode-aware memory source provider for `node_touch.nodeify`.

    human_memory -> the live `agent_memories` rows.
    stock        -> delegates to node_touch's file sweep, unchanged.

    Best-effort per the provider contract: returns [] on any failure rather
    than letting a grounding pass take down a nodeify run.
    """
    from app.services import node_touch

    try:
        if not memory_mode.is_human_memory(project):
            return node_touch.memory_provider(db, project, repo_path)
        return _row_units(db, project)
    except Exception:  # noqa: BLE001 - provider contract is best-effort
        import logging

        logging.getLogger(__name__).warning(
            "memory_provider failed for project_id=%s",
            getattr(project, "id", None),
            exc_info=True,
        )
        return []


def _register_provider() -> None:
    """Plug the mode-aware provider into the nodeify full pass.

    Import-time side effect, same shape as `doc_pointers` and `code_pointers`.
    Wrapped so it can never crash import - and note that this wrapping is
    exactly why the provider set has to be checked on a RUNNING instance rather
    than by grepping for this call: a silent failure here looks identical in
    source to a successful registration.
    """
    try:
        from app.services import node_touch

        node_touch.register_source_provider("memory", memory_provider)
    except Exception:  # noqa: BLE001 - provider registration is best-effort
        import logging

        logging.getLogger(__name__).warning(
            "memory_provider registration skipped", exc_info=True
        )


# Landing the override (DWB-692): REPLACES node_touch's file-only memory_provider
# with the mode-aware one. Safe to register globally - node_touch's nodeify tests
# clear _PROVIDER_OVERRIDES via an autouse fixture, so this only takes effect in
# production, and a stock project is delegated straight back to the old provider.
_register_provider()
