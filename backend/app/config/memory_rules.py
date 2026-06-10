# Path: app/config/memory_rules.py
# File: memory_rules.py
# Created: 2026-06-10
# Purpose: Single source of truth for the inline memory-usage rules surfaced in identify + spawn-prepare responses (DWB-352)
# Caller: app/services/agent.py (identify_agent, spawn_prepare_payload)
# Callees: -
# Data In: -
# Data Out: MEMORY_USAGE_RULES: str (<=600 chars, enforced at import time)
# Last Modified: 2026-06-10

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
    "Memory dir: .claude/agents/memory/<prefix>/<name>/\n"
    "Files: identity.md (system; NEVER edit), scratchpad.md, lessons.md, "
    "recent_sessions.md.\n"
    "NEVER Edit/Write any .claude/ path (crashes subagents). "
    "ALL memory writes go through the API:\n"
    "- In-flight: POST /api/agents/{agent_id}/memory/append "
    "{file, content}. file=scratchpad|lessons|recent_sessions.\n"
    "- Wrap-up: POST /api/agents/{agent_id}/session-complete writes "
    "all three at session end.\n"
    "Both endpoints prepend the ISO 8601 UTC heading "
    "(## 2026-06-10T13:45:00+00:00) and are append-only."
)


# Enforce the 600-char cap at import time. The DWB-352 spec mandates this:
# if the constant overflows, refactor or trim rather than letting the
# response silently bloat.
MEMORY_USAGE_RULES_MAX_CHARS = 600
assert len(MEMORY_USAGE_RULES) <= MEMORY_USAGE_RULES_MAX_CHARS, (
    f"MEMORY_USAGE_RULES is {len(MEMORY_USAGE_RULES)} chars, "
    f"exceeds the {MEMORY_USAGE_RULES_MAX_CHARS}-char cap. Trim or refactor."
)
