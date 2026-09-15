# Path: app/config/memory_rules.py
# File: memory_rules.py
# Created: 2026-06-10
# Purpose: Single source of truth for the inline memory-usage rules surfaced in identify + spawn-prepare responses (DWB-352); DWB-560 makes them lessons-only
# Caller: app/services/agent.py (identify_agent, spawn_prepare_payload)
# Callees: -
# Data In: -
# Data Out: MEMORY_USAGE_RULES: str (<=600 chars, enforced at import time)
# Last Modified: 2026-09-15 (DWB-560: lessons-only rule with explicit exclusions; drops the stale auto-trim wording)

"""Inline memory-usage rules for agent spawn responses (DWB-352).

Workers often skim past the playbook on spawn. The DWB API ships a
condensed copy of the memory rules in every identify + spawn-prepare
response so the worker sees the rules inline regardless of whether they
opened the playbook.

Hard contract: ``MEMORY_USAGE_RULES`` is <= 600 chars. The module
asserts this at import time so a future edit that overflows fails the
test run instead of silently bloating the response.
"""

MEMORY_USAGE_RULES: str = (
    "memory.md = DURABLE LESSONS ONLY (identity.md is system; NEVER edit).\n"
    "Write what future-you would otherwise relearn the hard way.\n"
    "Do NOT write ticket ids, dates, counts, what you shipped, or status "
    "narration: the DWB database is the session record; duplicating it burns "
    "your ceiling.\n"
    "Append-only; the server stamps an ISO 8601 heading.\n"
    "- Append: POST /api/agents/{id}/memory/append {file:'memory', content}\n"
    "- Size: GET /api/agents/{id}/memory -> est_tokens, ceiling, headroom\n"
    "- Wrap-up: session-complete writes ONLY your lessons.\n"
    "Over-ceiling writes are REFUSED (400): condense, nothing drops."
)


# Enforce the 600-char cap at import time. The DWB-352 spec mandates this:
# if the constant overflows, refactor or trim rather than letting the
# response silently bloat.
MEMORY_USAGE_RULES_MAX_CHARS = 600
assert len(MEMORY_USAGE_RULES) <= MEMORY_USAGE_RULES_MAX_CHARS, (
    f"MEMORY_USAGE_RULES is {len(MEMORY_USAGE_RULES)} chars, "
    f"exceeds the {MEMORY_USAGE_RULES_MAX_CHARS}-char cap. Trim or refactor."
)
