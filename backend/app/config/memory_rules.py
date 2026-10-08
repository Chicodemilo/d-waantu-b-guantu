# Path: app/config/memory_rules.py
# File: memory_rules.py
# Created: 2026-06-10
# Purpose: Single source of truth for the inline memory-usage rules surfaced in identify + spawn-prepare responses (DWB-352); DWB-560 makes them lessons-only; DWB-638 adds the human_memory variant so a sealed project is never handed stock instructions; DWB-661 states the required condensed + keywords fields on the lesson write
# Caller: app/services/memory_mode.py (memory_usage_rules_for), app/services/agent.py (identify_agent, spawn_prepare_payload), app/services/agent_memory.py (identity.md)
# Callees: -
# Data In: -
# Data Out: MEMORY_USAGE_RULES: str, HUMAN_MEMORY_USAGE_RULES: str (each <=700 chars, enforced at import time)
# Last Modified: 2026-10-08 (DWB-661: condensed + keywords stated as required in HUMAN_MEMORY_USAGE_RULES; cap 600 -> 700; the stock constant is unchanged)

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

Hard contract: each constant is <= 700 chars (600 until DWB-661; see the
cap block at the bottom for why it moved and in what order). The module
asserts this at import time so a future edit that overflows fails the test
run instead of silently bloating the response.
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
#
# DWB-661 adds `condensed` and `keywords`, both REQUIRED on the lesson write
# (DWB-657 refuses the write at 400 without them). They are named here and not
# left to the refusal alone because this block is the only memory instruction
# some agents ever read, and a required field an agent does not know about
# costs it a round trip on its first write of the session.
HUMAN_MEMORY_USAGE_RULES: str = (
    "HUMAN_MEMORY MODE: stock memory.md is SEALED. Every stock write route\n"
    "409s and writes nothing; the 409 names the replacement.\n"
    "DURABLE LESSONS ONLY: no ticket ids, dates, counts or status.\n"
    "- Lesson: POST /api/agents/{id}/memories. {body, condensed, keywords}\n"
    "  ALL REQUIRED else 400. condensed = ONE line that IS the lesson, not\n"
    "  the setup. keywords = two or three. Optional cost:'none|low|high',\n"
    "  caught_by:'me|worker|human|ci', surprised:bool; enums not prose (422),\n"
    "  no tier (400).\n"
    "- Episode: POST /api/journal {agent_id, body, tags}\n"
    "- Read: GET /api/agents/{id}/memory/scored\n"
    "/memories satisfies write-on-close. No ceiling."
)


# Enforce the cap at import time. The DWB-352 spec mandates this: if a
# constant overflows, refactor or trim rather than letting the response
# silently bloat. Both variants are capped, not just the stock one: a cap that
# only one of two interchangeable payloads has to meet is not a cap on the
# response, so there is ONE number here and both must meet it.
#
# THE CAP MOVED 600 -> 700 IN DWB-661, AND THE TRIM CAME FIRST. Two required
# fields with semantics attached do not fit in the slack the 600 left. The
# first draft that stated them ran 773 chars; trimming the prose around them
# (the sealed-routes sentence, the lessons-only exclusion list, the closing
# line) brought it to 629 without dropping a route, an enum value or a refusal
# code. There was no further cut that did not delete something an agent acts
# on, so the number moved rather than the content. That is the order to repeat:
# trim to the floor, then move the cap by exactly what the floor needs. A cap
# that rises to meet whatever was written has stopped being a cap.
MEMORY_USAGE_RULES_MAX_CHARS = 700
for _name, _rules in (
    ("MEMORY_USAGE_RULES", MEMORY_USAGE_RULES),
    ("HUMAN_MEMORY_USAGE_RULES", HUMAN_MEMORY_USAGE_RULES),
):
    assert len(_rules) <= MEMORY_USAGE_RULES_MAX_CHARS, (
        f"{_name} is {len(_rules)} chars, "
        f"exceeds the {MEMORY_USAGE_RULES_MAX_CHARS}-char cap. Trim or refactor."
    )
del _name, _rules
