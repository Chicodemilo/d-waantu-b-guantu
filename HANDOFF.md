# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## READ FIRST

**`docs/project_page_cleanup.md`** — tomorrow's work. Miles parked the
`/projects/:id` cleanup; the audit is already done against live data. Do not
re-audit it. Tier 1 is three strict duplicates of pages that already exist, and
the order is set in the doc.

**The biggest problem on that page is not layout.** 80 of 86 open alerts are
reputation broadcasts raised to `critical`. That is DWB-598, in backlog, and
fixing it does more for the page than any redesign.

## Current state (2026-10-06, pushed and green)

HEAD `fbfdf52` on master, 2948 passed, 0 failed. Five commits today, each a
separate revertable fix. Working tree clean.

IND (project 40) migrated stock -> human_memory: 308 entries judged by seven
agents, 293 adopted (209 scar, 84 working), 15 skipped and journaled. The nine
stock `memory.md` files are byte-identical to the pre-toggle baseline — cutover
sealed them rather than consuming them, and with the clock bug below they are
currently the only readable copy. Do not close that door.

## Four defects shipped as guards today

All four were the same shape: **a path that is honoured in part and answered
200**. None announced itself.

1. **top-off ran during a transition** and could promote a scar to CORE on
   evidence drawn from a half-migrated store. Suppressed while `adopting` or
   `reverting`.
2. **`reason` was accepted and discarded** on the tiering path, kept only on
   skips. 293 reasons lost on IND's migration before the column existed.
3. **an adoption with no open session** mints rows with a NULL clock origin,
   which cannot be scored and are therefore excluded from retrieval. Second
   occurrence; the first was closed with a comment instead of a guard. Now
   refused at BEGIN.
4. **a markdown heading was read as a scope that can never close**, so
   `scan_context` answered `cannot_die` and auto-promoted into the
   never-decaying tier. 381 of 455 live scars were eligible. Now answers a new
   `unresolvable` outcome and takes no action.

## Open, needing Miles

- **The 39 + 86 already-promoted rows.** Before the bug fired, IND's team lead
  had ZERO core rows — the entire CORE tier there is an artifact, including 13
  standing rulings and the Jira credential authorization. Nothing in it carries
  human-granted provenance because no route grants it. Current lean: revert to
  scar and promote deliberately once a human path exists. Raw SQL either way.
- **IND's 293 NULL clock origins.** Backfill pending a ruling. Argued (by the
  other Archie_IND) for a synthetic session pinned to the adoption window rather
  than stamping now, because stamping now asserts reinforcement that never
  happened and the lie grows while the decision waits. Lockstep is not an
  artifact to engineer away — those rows genuinely did enter in one hour.
  **Not urgent:** `/memory/scored` serves rows regardless of scoring, so the
  other window's spawn script already routes around it. Only a caller trusting
  `memory_full` is affected.
- **No human path to CORE at all.** `promote_to_core` has no HTTP route. After
  defect 4 this is now the *only* road, so it went from a gap to the blocker.
  Tracked for human_memory v2 along with the dedup hole and bundled rows.
- **`memory_usage_rules`** from `spawn-prepare` still teaches `memory/append`
  and `condense`, which 409 on a human_memory project. Server-generated, so this
  morning's playbook fix did not cover it. Smallest open item.

## Two Archie_INDs

A second interactive session runs IndependenceDay on another machine
(`independenceday-99`), opened DWB session 2653. Both are agent_id 70 writing to
the same store and neither can see the other, which is why a defect report
arrived here attributed to a spawned teammate who correctly refused credit. That
session has its own spawn script and is briefed on all four fixes. It
deliberately does not raise things with Miles, to avoid double-asking.

## The lesson worth carrying

Three of today's four defects I walked into myself, and the clock-origin one I
caused by closing a session on instruction. The tell in every case was a 200.
The suites were green throughout both outages because every test asserted rows
were WRITTEN and none asserted a memory could be READ BACK by the thing that
serves it. A row count proves storage; only an end-to-end read proves delivery.

That bit one more time tonight: the memory note pointing at the cleanup doc was
written seconds after the regex layer closed the session, so it landed with a
NULL origin — the exact defect, on the last write of the day. Stamped with its
true session (2652) by hand. Hence this pointer existing in two places.
