# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-01, human_memory COMPLETE AND RUNNING, NOTHING COMMITTED)

**NEXT SESSION, IN ORDER, FROM MILES:**
1. **Full human_memory scan test / run through.** Not a unit run. Drive the whole thing end to end and look at it.
2. **Then push.**

Nothing else comes before those two. Do not open with housekeeping.

- **`HEAD` unmoved at `357db3a`. ~120 files unstaged or new. Nothing staged, nothing committed.** Miles has not yet asked for a commit; he has now said we push after the scan test next session.
- Backend suite **2762 passed, 0 failed** (5:14), source fingerprint `e034022014b0` matched before and after, 178131 bytes into the hash.
- **The end-to-end exerciser is 5/5 on all five movements**, run by the TL personally, printed context read.

## human_memory is now ACTUALLY BUILT. What that means.

On 2026-09-30 Miles found that the lane we called "done" was a substrate with no system on it: four buckets that held rows, correct decay maths, and **not one mechanism that moved anything**. No agent ever received a memory; `human_memory` served a pointer. The TL had reviewed thirteen tickets against their acceptance criteria and never asked whether the set of them added up to the feature.

Twelve tickets (DWB-603 to DWB-614) fixed it. What runs today:

- **Session start fires `memory_consolidate.consolidate_agent`**, gated on `human_memory`, wrapped so a consolidation bug cannot 500 the hook. Order: scar-to-core, then scar-context-concluded, then WORKING floor, then journal-to-core. A mutation-verified test pins that order.
- **All five of Miles's movements have real consumers.** WORKING at the floor goes to the journal keeping its original `created_at` (DWB-605 added the second date). A scar fired 3 times broadens to CORE. A scar at 6 whose context resolved to a closed ticket or completed epic goes to the journal. A scar whose context can never resolve becomes CORE. A journal entry pulled 3+ times becomes CORE.
- **Agents receive real memory.** Bands 8-10 arrive as full text through `memory_format.render`, 5-7 as one truncated line, 2-4 and 1 as a count only. Both spawn and SessionStart. The seal still holds: `human_memory` never serves the flat file.
- **Four buckets, not five.** `scar_context_bound` was collapsed into `scar` (DWB-611, migration applied). `raw` remains as the pre-judgment ingest state, which Miles accepted as outside the four at rest.

## MILES'S RULING ON WHAT COUNTS AS A READ (2026-10-01)

Verbatim, because paraphrase lost it twice:

> "Deploy doesn't count as a read. Reading is Oh have I made this scar producing error before? Outside of normal startup."

Three code paths had been incrementing the promotion counters merely by DISPLAYING a memory. CORE never decays, so the system as wired would have migrated everything into the bucket that never forgets, which is the opposite of the feature's thesis.

Stan turned the ruling into a testable rule, and it is the one to keep:

> **A read is injection-shaped when it can be satisfied with NO QUESTION in it.**

`scored_memory()` could be called with nothing in it, so it can never be a consultation no matter who calls it. `journal.search_entries` requires a filter by construction, so it always is one. Consequences now in the code:

- `_fire_scars` and `FIRING_TIERS` are **deleted**, not flagged off. Injection, the dashboard and the consolidation job are structurally incapable of firing.
- `memory_consult.consult_scars(db, agent_id=, term=)` is the single `fired_count` write site. It refuses a blank term and fires only MATCHING rows.
- **Top-off calls it in the same pass it searches the journal, with one term computed once** (`_topoff_search_term`), so the two can never drift onto different slices of the prompt.
- Triggering a consultation on a schedule does not change what kind of question it is, which is why DWB-612's journal search needed no change.

## The instrument: backend/scripts/human_memory_exerciser.py

`cd backend && .venv/bin/python scripts/human_memory_exerciser.py`

Functional, not unit, on Miles's explicit instruction. Drives the live API over real HTTP against the live DB on a throwaway project it creates and deletes. Manufactures 92 closed sessions for the clock, seeds every bucket, fires the real SessionStart hook, verifies only through `GET /memory/scored` and `GET /api/journal`, **prints verbatim what an agent receives**, and tears down in `try/finally`.

**This is the thing that was missing and it is why the lane is trustworthy now.** On its outings it caught: a live journal outage (a model edit ahead of its migration, under `--reload`), a compression check that could not distinguish broken from no-op, and a movement with no implementation at all. A pytest version would have caught none of them, because `lat_test` is built by `create_all` from the same models.

Three states, not two: `PASS`, `FAIL`, `SHORT_BODY_AMBIGUOUS` for rows whose body is too short for compression to be observable.

## Open, in priority order

1. **The scan test, then the push.** Miles's instruction for next session.
2. **CHANGELOG.md and README.md still need one fix.** They say working facts "fade to nothing"; they floor at 1 and are then REMOVED by DWB-607. The band-carrying claim is now true. Dolores's condition (do not commit with a red open in the lane) is satisfied.
3. **S83 / sprint 177 close** is prepped: gates passing, zero open failure records. Carrying DWB-578 and DWB-583. Backlog: 598, 599, 600, 601, 602, 615, 616.
4. **DWB-615 and DWB-616** are real and reproduced: `delete_agent` 500s on `tl_message_reads`, and `delete_project` orphans `agent_memories`/`journal_entries`. The exerciser works around both by hand; when they land, those manual deletes become removable and the cleanup docstring says so.

## The test-tooling failures of 2026-09-30 (S83)

Dolores ruled these do not belong in the human_memory CHANGELOG entry: wrong subject, and they would read as a non sequitur to someone evaluating the repo. They get their own entry when a fix lands. Recorded here meanwhile.

- **A fingerprint was stable, reproducible, read by two people, and wrong.** `9094beb8cdbe` was handed to the runner as a baseline. It was the hash of the tree with a mutation battery's deliberately broken file in it, confirmed afterwards by reconstructing the mutation in scratch and reproducing the hash exactly. Had the suite come back green we would have published a number certifying broken code. **Every check we had asks whether the tree is STILL; none asks whether it is RIGHT.** Filed as DWB-601, ordered ahead of DWB-600. This is the strongest argument in the repo for why a fingerprint needs a check independent of itself, because agreement cannot catch it: two people agreeing is what the method produces either way.
- **Eight instances of one defect family across four people in one afternoon**, each of whom knew the rule, two of them committing it inside the act of writing the rule down. Now classified in `docs/worker_playbook.md` into closed loop, wrong target and no check, with a different detection move for each. Two of the three can be mechanised. The third can only be caught by another person.
- **`git checkout` on an uncommitted shared tree destroyed three tickets' router wiring**, window roughly 12:05 to 12:20, self-reported unprompted with the window named, repaired, repair independently verified at 139 passed. The published 2656 is provably outside the window: that run ended 12:05:37 and its post-run fingerprint matched its pre-run read, impossible if three route wirings were missing.
- **A TL PATCH by ticket id hit DWB-590 while intending DWB-591 and destroyed the description.** Unrecoverable from the system: the activity feed records that a row was updated, not its prior value. Restored only because the assigned worker had printed the full ticket text when picking it up. Now: assert `ticket_key` before any write, re-fetch and compare after, append rather than replace.
- **A function with zero call sites was misclassified as harmless from its call graph.** Its body returned None for the direct edge that seals stock memory against an empty store, so it implemented the rule DWB-593 exists to forbid. Deleted with a record of what was there; `MEMORY_MODE_SWITCH_WARNING` survives.
- **Three uncovered suite inputs found one incident at a time**: the live memory corpus, `identity.md` scaffolding, and `docs/`/`.claude/` playbooks. The runner's conclusion, which is the right fix and is in DWB-601: derive the scope from the suite by recording every path a run READS, rather than declaring it. Every scope declared by hand today was wrong in one direction or the other.

**Instrument worth keeping:** a per-file manifest beside the fingerprint. A hash says THAT the tree moved; the manifest says WHAT moved, in one diff, in three lines of shell. It is the only check built that day that answered a question without a hunt attached, and it is what located the destroyed router file.

## What shipped: the human_memory lane

| Ticket | What it is |
|---|---|
| DWB-584 | Substrate. `agent_memories`, `journal_entries`, `projects.memory_mode`, schema version, top-off columns, prompt counter. |
| DWB-585 | The derived score. Decay curve, bands, session gap, `GET /agents/{id}/memory/scored`, candidate lists. |
| DWB-586 | Raw untiered append with `cost`, `caught_by`, `surprised` on the memory row. |
| DWB-587 | The journal. No full dump, server-side unskippable retrieval count, promotes at three. |
| DWB-588 | `memory_mode` toggle with the switch warning verbatim, inline text confirm, no modal. |
| DWB-589 | Enforcement. Four write routes sealed per-route, both read paths sealed, write-on-close gate hole closed, harness hook. |
| DWB-590 | Top-off on its own toggle and interval, independent of `memory_mode`. |

**Spec: `docs/human_memory_spec.md`, and it is UNTRACKED.** 453 lines, canonical, carrying three amendments made this session. Four tickets cite it by section number. A backup is in the session scratchpad. **Track it in the first commit.**

### Design decisions that are easy to erode

- **There is no `score` column and there must never be one.** Score is a pure function of tier and sessions-since-reinforced, computed at read time. A guard rejects `score`, `band`, `sessions_since_reinforced`, `last_reinforced` and `last_reinforced_at`, and it was proved to bite.
- **The clock is SESSIONS, not calendar days.** Reinforcement is `last_reinforced_session_id`, not a timestamp.
- **The arithmetic floors at 1. Zero is an eviction state, not a computed score.** Nothing is deleted by arithmetic alone; anything leaving memory is written to the journal first.
- **`tier` is NOT NULL with `raw` as a named value**, so a scoring query has to name `raw` to exclude it. A nullable column would let a join drop untiered rows silently.
- **`cost`, `caught_by`, `surprised` live on `agent_memories`, not on `journal_entries`.** Decided by asking what READS each field: the context scan gates on `cost`, and `caught_by` aggregated across agents is the map of where a team's own checks do not look.
- **Top-off is independent of `memory_mode` and shares a migration for delivery reasons only.** A comment in the migration says so.

### The one thing top-off gives up, stated plainly

It ships **shape 2**: the injected line is `••TopOff Complete <link>`, short and constant, and **the four questions are NOT injected**. The marker is the trigger, the content lives in `docs/worker_playbook.md` § Top-Off. That makes the check a rule behind a reference, which is weaker than a rule in front of you, and it was Miles's ruling because four questions every tenth prompt is a flood that becomes wallpaper. **The playbook section is therefore load-bearing.** If it is ever trimmed, top-off fires a line nobody has been told how to act on.

The linked page `/projects/:id/topoff` **does not exist**. A DWB view for top-off events is a follow-up ticket. A dead link was chosen over an invented page deliberately.

## Verified end to end, and the one thing that is not

Everything in this lane is proved by its real path rather than inferred:

- The migration replays from base AND from a dump of live's structure stamped at the prior revision.
- The score guards bite, proved by running the broken variants as permanent tests.
- Top-off's channel is demonstrated by two independent transcript captures of the injected attachment.
- The hook denies the real harness memory path, creates no file, and exits 0 on empty, non-JSON, `{}` and null input.

**The single remaining unknown: whether a pure teammate relay fires `UserPromptSubmit` at all.** Cron-queued prompts do, measured twice. If relays do not, top-off is silent during exactly the heads-down stretches where drift is most likely. Recorded as a hypothesis with a cheap test on DWB-590 comment 916. It is unknown because testing it costs the human a line in his session, not because it is hard.

## THE HONEST CAVEAT, unchanged

**The fade is designed and unproven.** No consolidation run has ever shrunk without a human prompting it. Archie_IND's prototype ran twice and grew the second time; the only demotion so far happened because Miles pushed. Two condense runs this session shrank while adding content, but both were prompted and most of the reduction was removing narration the rules already excluded, which is cleanup rather than decay. **Miles and Archie_IND both agreed the bar for a second project is a run that shrinks unprompted. Nothing has met it.**

## Open items

- **DWB-592, in progress (Freddie).** The relay-filter bug, not part of human_memory. `_is_synthetic_user_text` was a `startswith` over sixteen angle-bracket literals and failed OPEN: the dominant relay shape starts with prose and sailed through into session open/close phrase detection, 331 turns against 32. The fix inverts it to a provenance allowlist that fails CLOSED, measured across 2349 turns and two harness versions. **`hook_tracking.py` carries both this and DWB-590, so sequence those commits.**
- **DWB-591, backlog (Dolores).** Changelog and README copy leading with human_memory and top-off. Gated: nothing describes as shipped what has not landed, and the fade must be described as designed rather than demonstrated.
- **IND ships a different top-off.** Archie_IND's prototype fires the full four questions every ten prompts, the shape rejected here. Not a collision; the thing to resolve if IND ever adopts this version.
- **The bug list Miles asked for is NOT written up.** He asked for human_memory bugs only and those are all closed. The DWB-side findings from this session are in `ARCHITECTURE.md § 9` rather than a list.

## Environment hazards found this session

Written into **`ARCHITECTURE.md § 9 Operational Gotchas and Traps`** rather than left as folklore. Five of them, each of which cost an outage or a wrong diagnosis: saving an ORM model is a schema change to the shared database; alembic never calls `create_all`; a `create_all` schema and a migration schema disagree on server defaults; testing a migration against an empty database proves less than it looks; MySQL DDL is not transactional. Read that section before touching a migration.

Also true and not in that section: **the TL cannot edit `.claude/settings.json`** — it is refused as self-modification — so any hook wiring needs the human to run it.

## Process lessons earned this session

- **Three of my own findings were overturned by my own workers, and all three corrections were right.** Each time I had a correlation and handed someone a cause. The tell is being able to name the coincidence but not the mechanism.
- **Eight crossed messages, all the same shape:** verify state, write at length about it, state moves before the message lands. Short messages cross less. This was already in memory and I ignored it for a session.
- **A brief is not the ticket.** I briefed four of five acceptance criteria and dropped the one the ticket called the reason it was filed. The worker built to the ticket and was right to.
- **Three permission refusals produced better work than they blocked:** a denied SQL write exposed a feature that had shipped unreachable, a denied settings edit surfaced a self-modification hazard, and a denied live migration re-run forced a scratch reproduction that found the real cause.
- **Never grep a transcript, parse it.** Grep finds the conversation about a string; only parsing finds the string. This produced both a false positive and a false negative in one night.

## Team

Barry_DWB (4 tickets), Stan (3), Freddie (1 plus 592 in flight), Sylvie (the P0 that unblocked the whole evening), Dolores (gate clearance, parked on 591), Pam_DWB (filed the slate, caught three defects before a worker saw them). All stood down with memory written. CC teams do not survive sessions: respawn per playbook.
