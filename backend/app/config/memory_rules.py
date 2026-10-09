# Path: app/config/memory_rules.py
# File: memory_rules.py
# Created: 2026-06-10
# Purpose: Single source of truth for the inline memory-usage rules surfaced in identify + spawn-prepare responses (DWB-352); DWB-560 makes them lessons-only; DWB-638 adds the human_memory variant so a sealed project is never handed stock instructions; DWB-661 states the required condensed + keywords fields; DWB-667 adds `situation` and the reachability rule; DWB-669 adds the subject rule. This block is a WRITE instruction: it deliberately does NOT state that core and scar are both consulted, or that a CORE row can be demoted, because those are retrieval and re-tiering facts and the block has three characters of headroom
# Caller: app/services/memory_mode.py (memory_usage_rules_for), app/services/agent.py (identify_agent, spawn_prepare_payload), app/services/agent_memory.py (identity.md)
# Callees: -
# Data In: -
# Data Out: MEMORY_USAGE_RULES: str, HUMAN_MEMORY_USAGE_RULES: str (each <=1600 chars, enforced at import time)
# Last Modified: 2026-10-09 (DWB-667: `situation` stated as required, and the reachable/unreachable keyword contrast carried inline; cap 700 -> 1050; the stock constant is unchanged)

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

Hard contract: each constant is <= 1600 chars (600 until DWB-661, then 1050 in
DWB-667, then 1600 for DWB-669's subject rule; every move trimmed first; see the
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
# DWB-661 adds `condensed` and `keywords`; DWB-667 adds `situation`; all four
# REQUIRED on the lesson write, and DWB-669's subject rule refuses separately
# (DWB-657 refuses the write at 400 without them). They are named here and not
# left to the refusal alone because this block is the only memory instruction
# some agents ever read, and a required field an agent does not know about
# costs it a round trip on its first write of the session.
HUMAN_MEMORY_USAGE_RULES: str = (
    "HUMAN_MEMORY MODE: stock memory.md is SEALED. Every stock write route\n"
    "409s and writes nothing; the body names the replacement.\n"
    "DURABLE LESSONS ONLY: no ticket ids, dates, counts, status.\n"
    "- Lesson: POST /api/agents/{id}/memories.\n"
    "  {body, condensed, keywords, situation} ALL REQUIRED else 400.\n"
    "  condensed = ONE line that IS the lesson, not the setup.\n"
    "  keywords = the words in the air when you are IN that moment, NOT a\n"
    "  label for what the lesson is about. Reachable 'git checkout',\n"
    "  'shared tree'; unreachable 'self-exempt', 'decompose-the-count'.\n"
    "  No stemming, every token must be present, two distinct needed\n"
    "  across ANY keywords - so SEVERAL SHORT keywords beat one precise\n"
    "  phrase, and carry both forms typed (doc/docs): a wrong-form\n"
    "  keyword is as dead as a label and LOOKS right.\n"
    "  But NEVER index a phrase not about your subject: two ordinary\n"
    "  words clear the floor BY THEMSELVES and fire on any prose\n"
    "  ('before i', 'show me'). Bare 'gate'/'test' cannot fire alone\n"
    "  but pair up by accident. Not adding junk is not narrowing.\n"
    "  situation = one line naming that moment. Keywords match it with\n"
    "  retrieval's OWN comparison, so one your sentence lacks is refused.\n"
    "  WRITE THE SITUATION FIRST, read keywords out of it.\n"
    "  Check offline, writes nothing:\n"
    "  keyword_reachability.require_reachable_keywords(keywords,situation)\n"
    "  Optional cost:'none|low|high', caught_by:'me|worker|human|ci',\n"
    "  surprised:bool; enums not prose (422), no tier (400).\n"
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
#
# DWB-667 MOVED IT 700 -> 1050, SAME ORDER, AND THIS IS THE BIG ONE SO THE
# ARGUMENT HAD BETTER BE GOOD. What was added is `situation` and, crucially, a
# WORKED CONTRAST between a reachable keyword and a filing label. The contrast
# is the content: "keywords are the words that will be in the air" is a sentence
# every author already believes it is following, and 288 live scars were written
# by authors who believed exactly that. Only the pair - 'git checkout' beside
# 'self-exempt' - changes what the next one writes. A rule stated without its
# counter-example is the version that produced those rows.
#
# THE TRIM CAME FIRST AGAIN, and it was measured. The first draft stating all of
# it ran 1112; cutting the redundant phrasing around the mechanics (not the
# mechanics) brought it to 1041, and no further cut removed anything an agent
# acts on. The cap is 1050 rather than 1041 so an unrelated word does not fail
# the build, and rather than 1200 so that the next addition has to make this
# argument again.
#
# IT MOVED AGAIN, 1050 -> 1350, IN THE SAME TICKET, AND THAT NEEDS SAYING OUT
# LOUD RATHER THAN SLIPPING THROUGH AS A SECOND BUMP. The first move carried the
# RULE. Four agents then re-keyworded 207 rows against that rule and sent back two
# things the rule did not contain, both found by running rows rather than by
# reading it:
#
#   INFLECTION, not labels, is the hard half. Getting from 'absence-defect' to
#   situational words is easy. Knowing whether the typed form is 'doc' or 'docs',
#   'trim' or 'trimming' is not, nothing is stemmed, and a situational keyword in
#   the wrong form is exactly as dead as a filing label while LOOKING correct -
#   which is worse, because re-reading it tells you nothing. Carrying both forms
#   costs one array entry and is the whole fix.
#
#   WRITE THE SITUATION FIRST and read the keywords out of it. Two agents arrived
#   at that independently from opposite directions, and it is what the gate
#   structurally enforces anyway.
#
# Plus the offline check, which turns learning this contract from a sequence of
# 400s into one local call; one agent checked all 44 of its rows that way and sent
# zero failing requests.
#
# A cap that rises to meet whatever was written has stopped being a cap, so: the
# addition is 302 chars against a 300-char move, the trim was done first again
# (the duplicated "every token must be present" clause was absorbed rather than
# appended), and the test pinning the literal must be edited in the same commit.
#
# THIRD MOVE, 1350 -> 1600, AND A THIRD MOVE IN ONE TICKET NEEDS MORE THAN THE
# USUAL ARGUMENT. Here it is.
#
# WHAT FORCED IT. The second move added Barry's rule - several short keywords beat
# one precise phrase - which is correct and is the single most useful mechanical
# line in this block. Measuring the pass that followed it showed what it produces
# when shipped WITHOUT its failure mode: keywords like 'before i' and 'show me',
# which are two ordinary English words, so they clear the two-token floor BY
# THEMSELVES and fire on any first-person prose. On twenty negative controls drawn
# from this project's own vocabulary, 'before i' fired on "the epic needs a
# description before I create it". Bare 'gate', 'test' and 'check' spread across
# the corpus the same way; one cannot fire alone, which is exactly what makes them
# feel free, and two in one situation fires the row.
#
# SO THE QUALIFIER IS NOT AN ADDITION TO THE ADVICE, IT IS PART OF IT. Shipping
# "widen" in the block that some agents read INSTEAD of the playbook, while the
# measured way widening goes wrong lives only in the playbook, is this file's own
# counter-example rule broken by this file. That is the whole reason the contrast
# pair is in here rather than only in docs/.
#
# WHAT I TRIED FIRST, because trim-before-bump has to be more than a sentence. The
# qualifier is 249 chars as shipped and the slack was 2. My first draft of it ran
# 297 and the import-time assert refused the file at 1645 against a cap I had just
# set to 1600 - I had costed the move from a draft I then rewrote. The assert is
# the only reason that number and this comment agree, which is the argument for
# having it. Compressing the reachable/unreachable
# contrast recovers about 25; the situation sentence about 3; the sealed-routes line
# about 2. Dropping `- Read: GET /api/agents/{id}/memory/scored` would recover 43
# and is the only sizeable cut left - it is NOT taken, because a route an agent
# cannot find is the defect this block exists to prevent, and trading a route for
# prose is the wrong direction. There is no cut of ~160 chars that does not delete
# something an agent acts on, so the number moved rather than the content, for the
# third time, by measurement rather than by drafting.
#
# ONE THING FOR WHOEVER READS THIS NEXT. This block is now 1597 chars against the
# stock variant's 593. It has stopped being a quick card and is becoming a short
# playbook. That is a shape question - whether the inline block should carry worked
# examples at all, or state rules and point at docs/ - and it is deliberately NOT
# answered here by a fourth trim or a fourth bump. It wants a decision, not another
# edit to this constant.
#
# WHY THIS BLOCK AND NOT ONLY THE PLAYBOOK: this is the only memory instruction
# some agents ever read. It reaches more of them than any markdown file does,
# because identify and spawn-prepare paste it into all of them, and a behaviour
# rule with a second home in a code generator goes stale silently. The playbooks
# under docs/ carry the same contrast at length; if the two ever disagree, the
# API is the tiebreak.
MEMORY_USAGE_RULES_MAX_CHARS = 1600
for _name, _rules in (
    ("MEMORY_USAGE_RULES", MEMORY_USAGE_RULES),
    ("HUMAN_MEMORY_USAGE_RULES", HUMAN_MEMORY_USAGE_RULES),
):
    assert len(_rules) <= MEMORY_USAGE_RULES_MAX_CHARS, (
        f"{_name} is {len(_rules)} chars, "
        f"exceeds the {MEMORY_USAGE_RULES_MAX_CHARS}-char cap. Trim or refactor."
    )
del _name, _rules
