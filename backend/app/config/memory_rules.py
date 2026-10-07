# Path: app/config/memory_rules.py
# File: memory_rules.py
# Created: 2026-06-10
# Purpose: Single source of truth for the inline memory-usage rules surfaced in identify + spawn-prepare responses (DWB-352); DWB-560 makes them lessons-only; DWB-638 adds the human_memory variant so a sealed project is never handed stock instructions
# Caller: app/services/memory_mode.py (memory_usage_rules_for), app/services/agent.py (identify_agent, spawn_prepare_payload), app/services/agent_memory.py (identity.md)
# Callees: -
# Data In: -
# Data Out: MEMORY_USAGE_RULES: str, HUMAN_MEMORY_USAGE_RULES: str (each <=600 chars, enforced at import time)
# Last Modified: 2026-10-07 (DWB-638: HUMAN_MEMORY_USAGE_RULES added; the stock constant is unchanged)

"""Inline memory-usage rules for agent spawn responses (DWB-352).

Workers often skim past the playbook on spawn. The DWB API ships a
condensed copy of the memory rules in every identify + spawn-prepare
response so the worker sees the rules inline regardless of whether they
opened the playbook.

TWO CONSTANTS, ONE PER MEMORY MODE (DWB-638). Until this ticket there was one,
and it taught `memory/append`, `session-complete` and `memory/condense` to
every agent on every project. DWB-589 seals exactly those routes under
`human_memory`, so on a sealed project DWB itself was the thing instructing
agents to call endpoints it would then refuse with 409 - and this block reaches
more agents than any markdown file does, because identify and spawn-prepare
paste it into all of them.

The selector is NOT here. `app/services/memory_mode.memory_usage_rules_for`
picks between these two, alongside `stock_excerpt_for` and `memory_full_for`,
so the mode is one decision in one module rather than a rule each call site
remembers. This module stays dependency-free config: strings and their cap.

WHY THE HUMAN_MEMORY TEXT NAMES NO SEALED ROUTE. It would fit, and it was
drafted that way first. It says "every stock memory write route" instead for
two reasons: an agent arriving with a stale playbook in context needs the
negative statement to cover whatever route that playbook named, including one
added after this text was written; and the 409 body itself carries the
per-route replacement (`memory_mode._WRITE_REPLACEMENT`), so the specific
mapping is served at the moment it is needed rather than memorised in advance.
The playbooks under `docs/` name all four explicitly, where length is free.

Hard contract: each constant is <= 600 chars. The module asserts this at
import time so a future edit that overflows fails the test run instead of
silently bloating the response.
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

# Served instead of MEMORY_USAGE_RULES when the project runs `human_memory`
# (DWB-584/589). Everything the stock block teaches is sealed here, so this is
# a replacement rather than an addition: an agent must receive one or the
# other, never both, because two sets of memory instructions that both look
# authoritative is the exact failure DWB-589 exists to prevent.
HUMAN_MEMORY_USAGE_RULES: str = (
    "HUMAN_MEMORY MODE: stock memory.md is SEALED on this project.\n"
    "Every stock memory write route 409s and writes nothing, whatever an older\n"
    "playbook told you to call. The 409 names the replacement; read it.\n"
    "DURABLE LESSONS ONLY; not ticket ids, dates, counts or what you shipped.\n"
    "- Lesson: POST /api/agents/{id}/memories {body, cost:'none|low|high',\n"
    "  caught_by:'me|worker|human|ci', surprised:bool}. Enums not prose (422);\n"
    "  never send tier (400).\n"
    "- Episode: POST /api/journal {agent_id, body, tags}\n"
    "- Read: GET /api/agents/{id}/memory/scored\n"
    "A /memories row satisfies write-on-close. No ceiling here."
)


# Enforce the 600-char cap at import time. The DWB-352 spec mandates this:
# if a constant overflows, refactor or trim rather than letting the
# response silently bloat. Both variants are capped, not just the stock one:
# a cap that only one of two interchangeable payloads has to meet is not a cap
# on the response.
MEMORY_USAGE_RULES_MAX_CHARS = 600
for _name, _rules in (
    ("MEMORY_USAGE_RULES", MEMORY_USAGE_RULES),
    ("HUMAN_MEMORY_USAGE_RULES", HUMAN_MEMORY_USAGE_RULES),
):
    assert len(_rules) <= MEMORY_USAGE_RULES_MAX_CHARS, (
        f"{_name} is {len(_rules)} chars, "
        f"exceeds the {MEMORY_USAGE_RULES_MAX_CHARS}-char cap. Trim or refactor."
    )
del _name, _rules
