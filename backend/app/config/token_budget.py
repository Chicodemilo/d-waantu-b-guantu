# Path: app/config/token_budget.py
# File: token_budget.py
# Created: 2026-06-17
# Purpose: Single source of truth for doc/memory token ceilings + token estimation, shared by the token-budget endpoints, the consolidation gate, and the memory-compaction gate.
# Caller: app/routers/projects.py, app/services/agent.py (compaction), app/services/agent_consolidation.py
# Callees: -
# Data In: file names + text
# Data Out: ceilings (int), classifications (str), token estimates (int)
# Last Modified: 2026-10-01 (DWB-617)

"""Canonical token-budget config.

Previously these lived as private symbols in `app/routers/projects.py`,
which meant the memory-compaction gate could not reuse them without a
circular import. They now live here so every consumer measures the same
way against the same ceilings.

Token estimate: `max(len(text) // 4, len(text.split()))`. The old
`words * 1.3` heuristic under-counted real BPE tokens by ~20-25% for the
markdown + code + paths these files contain (audit 2026-06-17), so a gate
built on it would let files overrun their context budget while reading as
compliant. char/4 is the standard rough BPE floor; the word-count term is
kept as a floor-of-the-floor so whitespace-sparse content is not under-read.
"""

# Per-category token ceilings.
#
# DWB-617 (2026-10-01): raised across the board. The previous table was not
# tight, it was fiction - most categories were already exceeded, including
# files DWB generates itself. Measured against the live tree that day, against
# the OLD ceilings:
#
#   CLAUDE.md          2043 / 2000   OVER   project_rules_worker  3042 / 4000  ok
#   HANDOFF.md         4245 / 1500   OVER   worker_playbook      18319 / 4000  OVER
#   ARCHITECTURE.md   10649 / 8500   OVER   team_lead_playbook   14202 / 4000  OVER
#   README.md          3764 / 3500   OVER   pm_playbook           6750 / 4000  OVER
#   INITIAL.md         1752 / 2000   ok     identity.md (all 8) 615-664 / 600  OVER
#                                           memory.md worst       4420 / 4500  98%
#
# Four of eight DWB agents sat at 91-98% of the memory ceiling, one write away
# from an HTTP 400, and every identity.md was over its own ceiling while being
# scaffold-generated, so DWB wrote a file it then refused. The playbooks ran
# 3.5x to 4.9x over, advisory only, which means the number taught nobody
# anything. Miles's instruction that day: raise the base ceilings across the
# board, we have the context room, and make a newly opened project inherit the
# new limits rather than the old ones.
#
# Known limitation, recorded rather than hidden: DWB-579 proposed raising the
# memory cap and was CANCELLED with the condition "raise the body cap only
# after retrieval replaces whole-file injection", because the cap exists to
# bound what is pasted whole into a spawn prompt. That retrieval is the
# `human_memory` memory_mode. It is built and proven, but every project is
# still memory_mode='stock', so on stock the raised cap IS pasted whole. Miles
# was shown that and instructed the raise anyway.
TOKEN_CEILINGS = {
    "agent_def": 3000,
    "playbook": 20000,
    "claude_md": 4000,
    "project_rules": 8000,
    "handoff": 8000,
    "architecture": 20000,
    "readme": 8000,
    "initial": 4000,
    "memory_identity": 1500,
    # memory_main is a HARD WRITE-TIME REFUSAL, not a trim. DWB-518 removed the
    # passive drop-oldest behaviour: an append / session-complete / compact /
    # condense whose projected size exceeds this ceiling is REFUSED with HTTP
    # 400 and nothing is dropped (services/agent.py raises
    # SessionCompleteError("over_ceiling", ...) / MemoryAppendError, and the
    # detail string tells the agent to condense then retry). It is still NOT
    # counted by the consolidation gate (see GATE_EXEMPT + _gate_counts in
    # agent_consolidation.py).
    "memory_main": 12000,
}

# Memory files scanned per active agent (filename -> category). DWB-401: 2-file
# model (identity.md + memory.md).
MEMORY_FILES = {
    "identity.md": "memory_identity",
    "memory.md": "memory_main",
}

# Fallback when a file classifies to a category not present in TOKEN_CEILINGS.
# Single constant so every call site agrees (the old code used 800/1000
# inconsistently across scan blocks).
DEFAULT_CEILING = 1000

# Categories that are DWB-shipped governance docs: deployed from DWB,
# regenerated on deploy, and un-editable by any agent (.claude/ writes crash;
# only DWB's own TL authors them). Keeping them lean is DWB's editorial job, an
# advisory warning on the budget panel, NOT a close-blocking gate elsewhere
# (DWB-397). They still appear in compute_token_budget output; only the gate
# enforcement skips them. Agents are gated only on docs they author + can edit:
# their memory files + root continuity docs (HANDOFF/ARCHITECTURE/README/INITIAL)
# + project_rules.
#
# DWB-399: project_rules removed from the exempt set. Unlike playbooks (shipped
# DWB doctrine, identical across every project, overwritten on deploy),
# project_rules are project-specific and TL-editable — never overwritten by
# Deploy Playbooks. So they ARE budgeted/judged and gated, but only against the
# team-lead (the only agent who can edit .claude/ files); see _OWNER_MAP in
# agent_consolidation.py. Gating workers/pm on them would re-make the DWB-397 bug.
GATE_EXEMPT_CATEGORIES = {"playbook", "agent_def"}


def classify_file(name: str) -> str:
    lower = name.lower()
    if lower == "claude.md":
        return "claude_md"
    if lower == "handoff.md":
        return "handoff"
    if lower == "architecture.md":
        return "architecture"
    if lower == "readme.md":
        return "readme"
    if lower == "initial.md":
        return "initial"
    if "project_rules" in lower:
        return "project_rules"
    if lower.endswith("_playbook.md"):
        return "playbook"
    # Files in agents/ directory
    return "agent_def"


def is_gate_enforced(name: str) -> bool:
    """True when an over-ceiling `name` should BLOCK a close/ack gate.

    DWB-397/399: shipped DWB doctrine (playbooks, agent defs) is advisory only —
    it classifies into GATE_EXEMPT_CATEGORIES and returns False. Everything else
    (root continuity docs, project_rules, memory files that classify by
    fallback) returns True. project_rules are TL-editable project docs, so they
    are gated against the team-lead only (see _OWNER_MAP). NOTE: per-agent
    memory files classify as "agent_def"
    by name alone (they match none of the prefixes in classify_file), so callers
    that operate on budget entries MUST guard memory files by `agent_name`
    before applying this exemption — see agent_consolidation.py.
    """
    return classify_file(name) not in GATE_EXEMPT_CATEGORIES


def estimate_tokens(text: str) -> int:
    return max(len(text) // 4, len(text.split()))


def ceiling_for_category(category: str) -> int:
    return TOKEN_CEILINGS.get(category, DEFAULT_CEILING)


def ceiling_for_file(name: str) -> int:
    """Ceiling for a memory file name (scratchpad.md, lessons.md, ...) or any
    classified doc name."""
    if name in MEMORY_FILES:
        return ceiling_for_category(MEMORY_FILES[name])
    return ceiling_for_category(classify_file(name))
