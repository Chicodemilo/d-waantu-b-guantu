# IND adoption to human_memory, 2026-10-06

Capture of what seven agents found while adopting 308 entries. Written because
**the decide path discards `reason`**, so for the 293 tiered rows the reasoning
exists nowhere but the chat transcripts this file summarises. The 15 skips kept
theirs, appended to their journal entries.

Run: enumerated 14:15:22, completed 15:20:19. 293 written, 15 skipped.
Store: 209 scar, 84 working. All nine stock files byte-identical to pre-toggle
baseline; cutover sealed them rather than consuming them.

| Agent | scar | working | skipped |
|---|---|---|---|
| Pam_IND | 57 | 20 | 1 |
| Archie_IND | 53 | 15 | 6 |
| Devin_IND | 39 | 9 | 1 |
| Sylvie_IND | 32 | 12 | 1 |
| Bolt_IND | 19 | 8 | 0 |
| Dolores_IND | 9 | 1 | 1 |
| Pixel_IND | 1 | 18 | 5 |

## Defect 1: `reason` is accepted and discarded

`memory_transitions` has no `reason` column. `decide_and_maybe_cut_over` passes
`reason` to `skip()`, which appends it to the journal entry. On the `decide()`
branch the parameter is dropped — the function signature does not accept it.
The API returns 200 either way. Fix shape: add the column, pass it through.

## Defect 2: SCAR to CORE is unreachable in practice

Not the "gate is bypassed" story that was escalated. The opposite.

Verified chain: adoption refuses `tier=core` (`memory_decide.py:274`); the only
CORE write site is `promote_to_core` (`memory_promote.py:124`), reachable solely
from `maybe_promote_scar` and `promote_journal_candidates`, both called only from
consolidation. **No HTTP route reaches it, so a human cannot rule anything CORE.**

The mechanical trigger is `fired_count >= 3`. `fired_count` has one write site,
`memory_consult.consult_scars`, called from one place, `_topoff_scar_check`.

Two independent reasons it cannot fire:

1. `topoff_enabled` is False on IND and on DWB.
2. **The search term is the user's whole prompt**, stripped, 12–300 chars
   (`_topoff_search_term`), matched as `body LIKE '%term%'`. A memory body
   containing 12+ consecutive verbatim characters of a prompt is rare; 300 is
   essentially impossible. The code comment concedes it: "a longer literal
   substring only makes an exact match LESS likely, not more."

Evidence: `fired_count` is 0 across all 456 live memories on DWB, 285 of them
scars, on the longest-running human_memory project.

**Correction to the escalation.** Archie measured single words against his own
53 scars ("ticket" fired 16) and concluded mass false promotion. Independent
re-measure over all 209 IND scars is higher still by that method — "check" 49,
"the" 192. But single words are not the term. He flagged this caveat himself.
The block-fire *shape* is structural and real; the live behaviour is zero
promotions, not mass ones. Both halves should survive into v2: ranking would fix
the shape, and something other than whole-prompt substring matching is needed
before the mechanism does anything at all.

Consequence for the human: the 15 standing rulings below are in a fading tier
with no path out, by human ruling or by machine.

## Defect 3: bundled rows carry passengers

One row, one tier. A row holding several lessons tiers at its dominant lesson
and the rest ride at that level. Found independently by Dolores (#689, six
lessons), Archie (two welded rows), Sylvie (488, 505, 518), Devin (576, 578).
Dolores's addition: substring match probability scales with body length, so a
bundle is simultaneously the most promotable row and the least deserving.

Adoption could have caught this and did not; the agents could not, from inside
a one-entry view.

## Defect 4: `session-complete` manufactures duplicates

A wrap-up envelope restates lessons already appended in-flight, so those entries
arrive twice. Devin found the mechanism (his 581 restated nine already-adopted
entries); Dolores found one lesson written five ways across four rows; Pixel
found two entries carrying one fact; Sylvie found 528 duplicating 509. Four
agents, four sets. Unresolved: whether `skip` is the intended dedup channel.
Sylvie argued it is not, since skip means "not a lesson" and overloading it
blunts the instrument. Nothing in the system dedupes at any point.

## Needs a human ruling

- **Entry 482** (Archie): a standing ruling saying *re-read the playbook every
  session, not from memory*, which then restates the whole format spec from
  memory. Contradicts entry 430 (read live, never restate the columns). Now a
  frozen copy in the scar tier that will drift silently. Keep the body, or
  reduce to the pointer?
- **The 20 standing rulings** (Archie). Not 15 — he counted the rows under the
  literal `## CORE - standing Miles rulings` header and missed five appended
  later as loose entries. All 20 verified by SELECT (agent 70, all `scar`, all
  with live memory rows), listed below as `transition id [memory id]`. The
  file's own model settles CORE by provenance, not pain, so the scar tier can
  no longer distinguish "Miles ruled this" from "I learned this the hard way."

  Under the header: 419 [864] no PR Friday · 420 [867] PR gate, scoped
  permission per change · 421 [871] pre-gate autonomy · 422 [874] he decides
  rulings, not process outcomes · 423 [878] plain reading first · 424 [883]
  volume, length is the bigger sin · 425 [885] he learns by probing · 426 [890]
  render the whole artifact when iterating · 427 [892] a ruling argued against
  still gets built faithfully · 428 [897] verify before he posts · 429 [900]
  ticket pipeline, Pam drafts / TL reviews / he approves · 430 [904] ticket
  table, read the spec live, never restate columns · 431 [907] silos are a
  guideline not a fence · 432 [915] standing Jira credential authorization
  (2026-09-24) · 433 [917] no deadline framing to Greg, DWB keys banned

  Appended later, same category, no header: 477 [1078] show the ticket table
  first · 478 [1080] DWB is bot-facing, Jira is what he sees · 480 [1084]
  DWB never reaches him · 481 [1088] no ticket shown until the 10-column
  format · 482 [1090] his format is specified and I keep drifting off it
- **Pam's two authority boundaries**: "epic routing never reaches the sponsor —
  run it, tiebreak, DECIDE, file", and "zero, weak-only, or multiple strong =
  STOP, never guess, never create an Epic". Both are grants of autonomy, not
  earned scars. Same CORE-shaped problem.

## Known-wrong facts now in the store

- **Archie 473**: `docs/silo-map.yaml` names Miles as Forms silo owner. The
  owner is Willy Stout. Welded to a durable definition, so it rode in at scar.
- **Sylvie 488**: asserts a ~4500-token memory ceiling. It is 12000, and on a
  human_memory project those routes are sealed outright. Tiered working.

Both flagged rather than silently corrected. Withdraw path:
`POST /api/agents/{id}/memories/{memory_id}/withdraw`.

## Rows the corrected rubric would have moved

The brief described working tier by its *form* ("box facts, tool shapes, build
details") instead of its *test*: does the knowledge fade harmlessly. Pixel caught
this from inside the loop. The correction reached Pam, Devin and Sylvie after
their queues were already empty.

**Devin** — 6 of 9 working calls fail the corrected test: 534 (pipe masks exit
code), 535 (harness reports wrapper shell), 541 (CI SQLite BINARY blindness),
576 (`mysql:8` is 8.4), 578 (Pint rewrites `{@see}` into an import), 579
(`perl -pi -e` interpolates sigils). Still working under either test: 544, 545,
565.

**Sylvie** — would flip to scar: 524, 526, 525, 507, 521. Scar-grade passenger
inside a working row: 488, 505, 518. Correctly working: 519, 522, 504, 527.
Revised split ≈ 37/7/1. She withdrew her own "possibly over-scarred" caveat:
the error runs toward under-scarring, in her working tier.

**Pam** — 10 of her 20 working calls fail the corrected test, and she named the
property they share: the failure each one prevents is **silent**, so forgetting
it produces a wrong result that looks right rather than an error. 623
(`jira_issue_key` filter silently ignored, returning an unrelated row — its own
maxim is "an empty result announces itself; a wrong result does not") · 617
(`assigned_agent_id` vs `assignee_agent_id`, silently no-ops) · 625 (`create`
defaults the Jira sprint to a POR board even with `--project PID`) · 626
(`create` silently edits descriptions on submit) · 620 (a sprint can be shared
across boards and named for another project) · 603 (`comp run ci` is
Pint/Deptrac/Pest only; nothing lints shell or terraform) · 635 (the built SPA
is not committed; never write a bundle-commit step) · 638 (`ContentScanner`
tri-state: `unscanned` is never `clean`) · 592 (relay truncates long drafts) ·
639 (zsh does not word-split unquoted vars). Correctly working: 616, 622, 633,
659.

Note 603 against 636: she put "never promise a gate catches something without
checking the layer list" at scar, and the fact that rule depends on at working.

Her bundles: 582, 584 and 632 are scars carrying several lessons, tiered on the
dominant one. **618 and 627 are the reverse** — a loud API fact carrying a quiet
judgment rule as passenger, where the passenger is the half that should survive:
"never park a held ticket in a sprint merely named backlog, a completed sprint
asserts the work finished" (618) and "Archive claims a decision; never archive
something merely held" (627). Both now fade with the fact they rode in on.

**Devin's 581** holds one clause that exists nowhere else, surviving only in the
journal because skips keep their reason: *when someone offers a charitable
explanation that is wrong, correct it, because the true cause was worse.*

## What the agents got right, worth keeping

- **Sylvie** flagged her own 32/12 split as the shape of a story she would
  construct to justify over-tiering, citing an entry she had just judged
  (`THE OBSERVER CAN BE THE THING THAT FAILS`) rather than defending the number.
  She also caught a dedup argument leaking into a tiering decision (503 vs 524).
- **Bolt** reported entries vanishing from his queue and deliberately did not
  investigate, because investigating meant listing the queue. The queue was
  intact; his tally was wrong by four. The constraint survived its first alarm.
  His own diagnosis afterwards: he reconstructed the corroborating number from
  the same bad count, so it was not independent evidence.
- **Pixel** produced the only direct evidence that the one-entry design works:
  "batching would have let me pattern-match the surrounding noise and skip both."
  His was the noisiest set, 23 of 24 box facts or bookkeeping.
- **Devin** re-tested his own completed work against a rubric correction that
  arrived too late to use, and named himself a datapoint for the flawed line
  rather than an exception to it.

Twice today an agent's confident recovery story rested on a mechanism nobody had
checked — Bolt's vanishing entries, Archie's preserved reasons. Both reported
accurately what they observed. The silent-success paths are the weak link.
