# Path: app/config/token_budget.py
# File: token_budget.py
# Created: 2026-06-17
# Purpose: Single source of truth for doc/memory token ceilings + token estimation, shared by the token-budget endpoints, the consolidation gate, and the memory-compaction gate.
# Caller: app/routers/projects.py, app/services/agent.py (compaction), app/services/agent_consolidation.py
# Callees: -
# Data In: file names + text
# Data Out: ceilings (int), classifications (str), token estimates (int)
# Last Modified: 2026-06-17

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
TOKEN_CEILINGS = {
    "agent_def": 1500,
    "playbook": 4000,
    "claude_md": 2000,
    "project_rules": 3000,
    "handoff": 1500,
    "architecture": 7500,
    "readme": 3500,
    "initial": 2000,
    "memory_identity": 600,
    "memory_scratchpad": 2000,
    "memory_lessons": 1500,
    "memory_recent": 1000,
}

# Memory files scanned per active agent (filename -> category).
MEMORY_FILES = {
    "identity.md": "memory_identity",
    "scratchpad.md": "memory_scratchpad",
    "lessons.md": "memory_lessons",
    "recent_sessions.md": "memory_recent",
}

# Fallback when a file classifies to a category not present in TOKEN_CEILINGS.
# Single constant so every call site agrees (the old code used 800/1000
# inconsistently across scan blocks).
DEFAULT_CEILING = 1000


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
