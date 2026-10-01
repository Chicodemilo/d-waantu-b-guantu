# Path: app/services/memory_mode.py
# File: memory_mode.py
# Created: 2026-09-29 (DWB-589)
# Purpose: Enforce spec section 7 hard rule 1 - when a project runs
#          human_memory, stock DWB memory is not written and not read. Holds
#          the per-route write seal and the pointer the sealed read paths
#          return in place of stock memory.md content.
# Caller: app/routers/agents.py (write seal), app/services/agent.py
#         (tl_memory_for_project, spawn-prepare memory_full)
# Callees: app/models/agent, app/models/project, app/services/memory_context
#          (DWB-610: assembled scored memory, in place of the pointer, when
#          there is any to serve)
# Data In: db Session, agent_id or Project
# Data Out: bool / the pointer string / assembled memory text / StockMemorySealed
# Last Modified: 2026-09-30 (DWB-610: memory_full_for takes optional db+agent
#                and serves memory_context's assembled output over the sealed
#                pointer when there is scored content)

"""Hard rule 1, put in the API instead of in prose.

Spec `docs/human_memory_spec.md` section 7, hard rule 1, verbatim: "When
`human_memory` is on, it is the ONLY memory. Stock DWB memory is not written,
not read, not consulted. Not a fallback, not a cache, not a second opinion."

Section 7 opens by naming the failure mode, and it is worth keeping in view
because it is NOT the obvious one: "The failure mode is not 'the wrong memory is
used.' It is **two memories that both look authoritative and disagree.**"

That is why this module seals READS as well as writes. Sealing only the writes
leaves a switched project feeding agents the frozen stock file at spawn while
their writes land in the new store - two homes, both looking authoritative,
drifting apart from the first write. A half-sealed rule is worse than none,
because it looks enforced and nobody checks it again.

SCOPE, CARRIED DELIBERATELY AND NOT TO BE QUIETLY DROPPED: this seals DWB's own
API. The harness's file-based memory belongs to Claude Code, not to DWB, so the
PreToolUse hook in scripts/hooks/ is the only lever there and it is a weaker
one - anything that does not route through PreToolUse goes around it. This rule
is enforced, not airtight, and the difference should survive into whatever gets
written about it.
"""

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import MemoryMode, Project

# What a sealed READ path returns in place of stock memory.md content.
#
# A pointer rather than an empty string, and that mirrors hard rule 2's
# treatment of the harness store: it "holds ONE thing: a pointer saying durable
# memory lives in DWB, with the API shape." An empty string would be honest but
# mute - an agent handed nothing cannot tell "this project has no memory yet"
# from "your memory lives somewhere else now", and the second needs an action.
STOCK_MEMORY_SEALED_POINTER = (
    "This project runs `human_memory` mode. Stock DWB memory (memory.md) is "
    "sealed: not written, not read, not consulted (spec section 7, hard rule 1).\n"
    "Your durable memory lives in the memory store:\n"
    "  write   POST /api/agents/{agent_id}/memories "
    '{"body": "...", "cost": "none|low|high", '
    '"caught_by": "me|worker|human|ci", "surprised": true|false}\n'
    "  read    GET  /api/agents/{agent_id}/memory/scored\n"
    "Episodes go to the journal, which is never read whole:\n"
    "  write   POST /api/journal {\"agent_id\": N, \"body\": \"...\", \"tags\": [...]}\n"
    "  search  GET  /api/journal?tags=...&term=...&date_from=...\n"
)

# The replacement each sealed WRITE route names in its refusal.
#
# Per-route rather than one generic sentence: a refusal that cannot say what to
# do instead is a wall, and the agent hitting it has a lesson in hand right now
# that it is about to drop on the floor.
_WRITE_REPLACEMENT = {
    "memory/append": "POST /api/agents/{agent_id}/memories",
    "memory/condense": "POST /api/agents/{agent_id}/memories",
    # Named in the refusal even though AC1 lists only three routes. compact is a
    # full-file replace of stock memory.md - condense's sibling in the playbook -
    # and sealing three while leaving it open is a wiggle-out: an agent refused
    # on condense reaches for compact and gets the same effect. The ticket exists
    # because this rule was required to be un-wiggle-out-able.
    "memory/compact": "POST /api/agents/{agent_id}/memories",
    "session-complete": "POST /api/agents/{agent_id}/memories",
}

# Routes under the memory surface that stay OPEN under human_memory, each with
# the reason written down rather than remembered.
#
# This is the allowlist the structural test in
# tests/test_human_memory_enforcement_dwb589.py checks every POST memory route
# against. A new stock write route that is neither sealed nor listed here fails
# that test, so the next one ships unsealed by DECISION rather than by omission.
OPEN_UNDER_HUMAN_MEMORY = {
    "memories": "the human_memory store itself - the endpoint the seal redirects to",
    "memory/scored": "DWB-585's derived-score READ of the new store; a prefix-wide "
    "guard here would disable the endpoint that makes the mode work",
    "memory": "GET of stock memory.md, kept readable so a switched project's old "
    "content can still be migrated and inspected by a human",
    "scaffold-memory": "creates the memory DIRECTORY and an empty file at spawn; "
    "infrastructure, not a write of content, and sealing it breaks spawn",
}


class StockMemorySealed(Exception):
    """Raised when a stock memory write is attempted under human_memory.

    Carries the 409 detail. 409 rather than 403: the request is well-formed and
    the caller is permitted, but it CONFLICTS with the project's current mode -
    and unlike a permission error, it becomes valid again if the mode changes.
    """

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def project_for_agent(db: Session, agent_id: int) -> Project | None:
    """The agent's project, or None when the agent is missing or unscoped.

    None means "cannot tell", and every caller here treats that as NOT sealed.
    That is deliberate: this guard must never invent a failure for a request
    that would otherwise have produced its own 404. It answers one question -
    is this project in human_memory mode - and stays out of the way otherwise.
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        return None
    return db.get(Project, agent.project_id)


def is_human_memory(project: Project | None) -> bool:
    return project is not None and project.memory_mode == MemoryMode.human_memory


def assert_stock_write_allowed(db: Session, agent_id: int, route: str) -> None:
    """Raise StockMemorySealed if `route` is a stock write on a human_memory project.

    `route` is the suffix as it appears in the path, e.g. "memory/append". It is
    looked up in _WRITE_REPLACEMENT so the refusal can name the endpoint to use
    instead; an unknown route raises KeyError at import-time-adjacent call sites
    rather than silently degrading to a generic message.
    """
    project = project_for_agent(db, agent_id)
    if not is_human_memory(project):
        return
    replacement = _WRITE_REPLACEMENT[route].format(agent_id=agent_id)
    raise StockMemorySealed(
        f"stock memory is sealed on this project: `{project.prefix}` runs "
        f"human_memory mode. Spec section 7 hard rule 1: when human_memory is on "
        f"it is the ONLY memory - stock DWB memory is not written, not read, not "
        f"consulted, and is not a fallback, a cache or a second opinion. "
        f"Write to {replacement} instead. Episodes go to POST /api/journal."
    )


def memory_full_for(
    project: Project | None,
    stock_content: str,
    *,
    db: Session | None = None,
    agent: Agent | None = None,
) -> str:
    """What a spawn / SessionStart read should serve.

    Takes the stock content the caller already has rather than reading the file
    itself, so the seal is a single decision at one place and cannot drift from
    however each caller happens to locate memory.md.

    DWB-610: the seal itself does not change - human_memory still never serves
    stock_content, which stays exactly the enforcement this module exists for.
    What changes is WHAT it serves instead of stock_content: real assembled
    memory (band 8-10 full text, 5-7 compressed) when there is any, the pointer
    only when there is not. `db` and `agent` are optional and keyword-only so
    every existing call site that has no assembled content to offer (there are
    none left after this ticket, but a future caller might genuinely have
    neither) still gets the pointer rather than a TypeError.
    """
    if is_human_memory(project):
        if db is not None and agent is not None:
            from app.services import memory_context

            assembled = memory_context.assemble_session_context(db, agent)
            if assembled:
                return assembled
        return STOCK_MEMORY_SEALED_POINTER
    return stock_content
