# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-28)

HEAD `933b916` on master, thirteen commits today, pushed, tree clean.
Alembic head `dwb710a1b2c3`, single head. Full suite 3641 passed, 0 failed.
API answers a WRITE (`POST /api/agents/identify` returns 200), which is the
check to run - a read answering is not evidence a write will.

## READ THIS BEFORE YOU TRUST ANYTHING ON :8000

The uvicorn on port 8000 had been an **orphaned worker since 16 Oct** — PPID 1,
its `--reload` supervisor dead. For twelve days "a service edit on this box IS a
deploy" was false, and three separate workers discovered it independently within
twenty minutes today, each from a different symptom: a route absent from the
live openapi, a change that worked in-process and did nothing through the API,
and a fix producing byte-identical pre-fix output.

Restarted this session and confirmed: the journal by-id route answers 200 where
it 404'd an hour earlier. **Check the process before you believe a verification.**
`lsof -ti :8000` then `ps -o pid,ppid`. A worker with PPID 1 is an orphan.

An orphan serving committed code is the healthiest-looking failure available:
every endpoint answers, every suite can pass, and the only symptom is that your
edits do nothing. Two people catching it minutes apart was luck, not detection.

**Verify uncommitted code on an isolated instance, not by restarting :8000.** A
second uvicorn from the same venv on another port loads from disk and exercises
one lane's change instead of everyone's. But it runs against the PRODUCTION
database: every row it writes is real and indistinguishable afterwards, and
deleting the project does not unwrite them. Name what you wrote.

## What shipped

**A phrase could open a session every time the transcript was scanned** (DWB-682).
The open scan reads the transcript HEAD and runs on SessionStart *and* every
SessionEnd/Stop/SubagentStop, so the morning's phrase sat at line one all day and
each close minted the next open. Anchored on a consumed transcript position, keyed
on the entry uuid (1555/1555 human turns across 40 transcripts, no duplicates).
Not a timestamp floor: that would compare a transcript wall clock against a
DB stamp, the cross-clock class DWB-633 already had to repair.

**Not the same bug:** DWB-395 grace resurrect un-closes the SAME row within 120s
of a regex close. Deliberate, exemption list written. DWB-682 mints a new row;
395 un-closes an existing one. An acceptance criterion reading "the open set ends
up empty" would fail forever against a working feature. Count rows.

**Scar consolidation is dead by arithmetic** (DWB-684). The job runs, succeeds,
and reports zero forever. Scars floor at score 6; the demote band is 2-4 and
evict is 1, so no scar can ever be nominated at any age. Both automatic exits are
separately dead: 79 of 82 scars have no `context_key`, all 82 have `fired_count`
0. Only the refusal text was fixed, plus a test that makes the arithmetic fail
loudly if someone lowers the curve. The mechanism change is Miles's call.

**Three close-gate refusals named sealed routes** (DWB-688), not one as reported.
Found by an AST pass over string constants with the population stated, not a
grep. The predicate was already mode-aware and is untouched.

Also: journal read-by-id with a 404 that names the entity (DWB-687); top-off
state on the identify response (DWB-686); a re-gated keyword repair offered in
the reachability refusal (DWB-689).

## The second slate: what shipped this evening

**Commit rows, and an instrument that says when its own silence is meaningless**
(DWB-695, `d7644c8`). DWB had never received a commit from anywhere.
`GET /api/projects/{id}/hook-status` exists because "nobody committed" and
"nothing was ever installed" are the same observation from inside DWB, and that
indistinguishability was the defect. `armed` is three-valued on the
`gate-status` convention; `silence_means` names which of four readings a zero
`commit_rows` has. `effective_hooks_dir` asks `rev-parse --git-path hooks`
rather than assuming `.git/hooks`, because `core.hooksPath` REPLACES that
directory and switches the default off.

**A write-time scope gate, and `context_free`** (DWB-704, `c0e9a91`). 424 of 506
`context_key` values were markdown heading paths, so zero resolved and no scar
could ever conclude. `context_free` is NOT `context_key IS NULL`: a null key is
a data gap, the flag is a human judgement. Collapsing those two is the
2026-10-06 defect that promoted 381 of 455 rows into CORE.

**Heading paths moved to provenance** (DWB-710, `12ede42`). 380 rows to
`adopted_from_heading`, their scope column nulled. 68 author-supplied keys were
left alone - indistinguishable by the string, distinguishable by the
`memory_transitions` link, and writing them into a provenance column would have
stated something false about their origin.

**Node graph grounds on the live corpus** (DWB-692, `2a934ae`). LIVE AND INERT:
registering a provider produces nothing until a nodeify sweep runs, and the
sweep clears every pointer in the swept domains in its own committed
transaction. Not run - it is an operator action. Measured 13,200 pointers,
`relevant_lessons` 0.553s worst of three against a 5s budget.

**A conclude pass that could not act stopped looking like one with nothing to
do** (DWB-707, `5bd6d1f`). Fourteen passes logged `concluded_scars: 0` while
being indistinguishable from a pass that examined rows and found every context
live.

### `still_active` does not mean a scope is alive

Of 870 scar-family rows, 825 carry no `context_key` and **every one of them
returns `still_active`**. The verdict is the SAFE answer - it declines to delete
- and the NAME is not accurate. Nothing may read `still_active` as evidence that
a scope exists. This is the same move the 704 docstring condemns two paragraphs
down. Found by subtracting two numbers that were sitting in the same table.

### A `working` row with a validated key is a loaded gun

`scan_context` raises `not_a_scar` for it, so it can never conclude. Retier it
and it concludes immediately against work that may have closed weeks earlier.
Row 1756 is already in that state. No ticket; recorded in `context_scope.py`.

## `zero_token_close` has fired 442 times since June

Not four times today. Verified twice, independently:

    442 events · earliest 2026-06-22 · 26 agents · projects 1, 5, 7, 40
    -884 reputation points · 11 today · 431 before today
    542 ticket_closed events exist in total

**Roughly four in five closed tickets in this installation's history carry this
penalty.** 354 of the 442 sit on tickets WITH tracked time - attribution failed,
work happened. 88 have no time either and may be correct docks. Do not fold them
together.

**0 of 1569 score events have ever been reverted.** One redemption exists (event
1153, +1, 2026-09-15) which appends a compensating event and leaves the original
stick standing - a different operation, not a remedy at this scale. DWB-703
(`revert_score_event` implemented, tested, unrouted) is therefore a DEPENDENCY of
DWB-708, not a neighbour: whatever is decided about the 442 cannot be enacted
until a revert route exists.

`score_event` carries no session id, so the per-session hypothesis cannot be
tested from the ledger. A same-agent-same-calendar-day proxy (broader than a
session, overcounts toward confirming) says 402 of 442 had a sibling close.
**The 40 that did not are the open question** - a dock with no sibling close
cannot be explained by tokens landing elsewhere.

## A measurement expires, and a date does not save it

Three figures in `context_scope.py` were true when written and false within
hours of the same day, each carrying the stamp "Measured store-wide on
2026-10-28". DWB-710 landed four hours later and invalidated all of them.

**State what would invalidate a number, not when you took it.** Name the thing
that moves. `933b916` does this and separates the two standing claims from the
snapshot around them.

**The worst one was not in a docstring.** `_CONTRAST`, the refusal text an agent
actually READS, claimed "424 live rows carry exactly this shape". The count was
REMOVED rather than corrected, and the reason generalises: a docstring is
re-read by whoever edits the file next, a refusal message is re-read by nobody,
so the same stale figure lives far longer there. Do not put a moving number in
user-facing output.

**Re-measure, never recompute.** Subtracting 380 from 424 would have reconciled
and been wrong: four keyed rows now resolve to live work, which arithmetic
cannot reveal.

## A sentence can be wider than the instrument that produced it

Two distinct errors, both this evening, both from complete data:

- **A sample sufficient for the CLAIM is not a sample sufficient for the SIZE.**
  One `zero_token_close` event in one agent's ledger fully supported "the defect
  predates today" - and because the conclusion was already safe, nothing pulled
  toward the population. It was 1 of 442. Hedging gave no protection: "at least
  one prior instance" is true of 442 while implying three.
- **Measuring a COLUMN and reporting a CONCEPT.** "No score event has ever been
  reverted" was exact on `reverted_by` and wrong about correction, because
  `redemption_of` exists and has fired once. The fix is mechanical: when a
  sentence names a concept, ENUMERATE the columns, routes or sites that
  implement it and measure each. Here that was one extra call.

The cost is asymmetric. An understated count gets corrected and the section
survives. A claim the next reader disproves in one query takes the credibility
of every properly-measured sentence beside it, because nothing marks which ones
were widened.

**Quote a withdrawn sentence in place rather than deleting it.** Two people
arrived at this independently today, in a docstring and in a ticket. A reader
who remembers the old claim needs to find out it died; a deletion tells them
nothing.

## The retrieval lane delivered a lesson, and the index was rotten

The nodeify sweep ran on project 1 (operator action, authorised by Miles).

**Before:** every `relevant_lessons` ref was `.dwb/memory/DWB/<Agent>/memory.md`
- a sealed file agents may not open. **After:** `agent_memories/DWB/Stan/511`
resolving to real text. Zero file-style memory refs remain on project 1. First
time in the lane's existence that a pointer led somewhere readable.

**The honest limit:** `RelevantLesson` still carries no text FIELD. What shipped
is REACHABILITY. Text in the bundle is DWB-685 and is not built.

**The index was stale in every domain, and that is the bigger finding.**

    project 1 node_pointers     BEFORE    AFTER
      code                       36243    91478    <- not DWB-692's doing
      doc                        14643    22541    <- not DWB-692's doing
      memory                      2897     6639    <- changed SOURCE, not drift
      TOTAL                      53783   120658

The sweep did not grow the index 2.24x; it revealed how far behind it had
fallen. The memory column is NOT part of that story - that domain changed from
8 frozen files to 599 live rows, so before and after measure different things.
**Do not quote one ratio for the whole index.**

**Ten of twelve projects have never been nodeified at all** - `nodeified_at` is
NULL on 2, 5, 6, 7, 8, 13, 14, 15, 175, 176. Only 1 (tonight) and 40
(2026-09-17) have ever been built. The only caller of `nodeify_project` anywhere
is the HTTP route: no task, no sweeper, no startup hook. On those ten,
`relevant_lessons` was never stale - it was EMPTY, so any claim about retrieval
working or not working there was made against nothing.

### Running a sweep is an outage for everyone else

Three tiers, and keep them apart:

- **ESTABLISHED.** One `db.commit()`, at the end. Pointers written continuously
  18:24:18 to 18:27:24 - 3m06s - with the provider sweep running BEFORE the
  first insert, so the transaction was open longer. The endpoint is
  `def nodeify_project`, not `async def` (`backend/app/routers/nodes.py:111`),
  so minutes of pure-Python tokenising over 62,996 code units run in the
  threadpool of a single-worker process.
- **OBSERVED.** Two responses lost during the pass - a write returning 000 and
  an unrelated 30s PATCH timeout. BOTH WRITES LANDED. The failure mode is a
  dropped response on a committed write, which is the shape most likely to
  produce a duplicate if someone retries. The DB settled both; a retry would
  have duplicated.
- **INFERRED, NOT MEASURED.** GIL starvation as the mechanism. The transaction
  locks `nodes` and `node_pointers` and the PATCH touched NEITHER, so lock
  contention cannot be the explanation - which is why "it holds a long
  transaction" would have documented the wrong cost.

**The free test, for whoever next runs a sweep for their own reasons:** poll
`GET /api/status` every second for the duration. Flat latencies with only
node-table writes stalling means lock contention and a narrow cost. Spikes
across the whole pass mean the entire API degrades for minutes. **Nobody should
run a sweep to find this out.** DWB-555 covers the CALLER's experience; this is
a different cost with a different victim.

## A predicate that can only return presences cannot find an absence

Ten never-indexed projects were missed because the query was
`where nodeified_at is not null`. **The absence WAS the answer, and the filter
removed it.** Found by widening the same query by one column.

This is the fourth and cleanest member of a family that ran all evening - a
sentence, or a query, wider or narrower than the instrument under it:

- a sample sufficient for the CLAIM is not sufficient for the SIZE (1 of 442)
- measuring a COLUMN and reporting a CONCEPT (`reverted_by` vs "correction")
- attaching a MECHANISM to someone else's measurement and passing it on as
  established (mine: "the transaction is why your PATCH stalled")
- filtering out the rows that carry the finding (this one)

**Flag the unreviewed line even when you cannot say what is wrong with it.** The
"permanently ineligible" overreach was caught because Pam marked a sentence as
hers and unchecked, not because she spotted the error. That discipline is
strictly more available than catching the error, because it needs no insight -
anyone can say "this line is mine and nobody has checked it", about anything, at
any time.

## Operational facts that cost someone an hour

- **`information_schema.innodb_trx` is unavailable** - the app credentials lack
  `PROCESS`. Do not plan a lock investigation around it.
- **A second uvicorn on :8099 isolates the PROCESS, not the CHANGE.** It loads
  the whole working tree, so once two lanes have edits on disk it exercises
  both. It was described as change isolation to three lanes before this was
  caught.
- **A `main.py` edit under `--reload` IS a restart.** Importing a new module
  there reloads the server; that is how DWB-692's provider went live.
- **An uncommitted migration on disk is applied by the next person to run
  `upgrade head`** (DWB-711). It does not wait for a commit.
- **Do not put credentials on a command line.** The classifier refuses it. Use
  the app's own config-loaded engine for ad-hoc queries.

## The finding that matters most

**The memory write gate's 201 has no predictive value for recall.**

Three agents measured it independently. Blind paraphrases written from the other
end *before* looking at any keyword set: Benny 0/12 across six rows, Devin 0/2,
Stan 2/4. One row recalled nothing four hours after passing the gate cleanly.

The gate matches your keywords against YOUR OWN situation sentence, so it can
only ever prove you could have said those words. Two distinct mechanics:

- **Keywords naming the CLASS** the lesson is filed under. "consolidation job",
  "scar tier" — nobody in that moment types "consolidation". They type "the job
  ran fine", "nothing moved", "zero rows".
- **Single-token keywords never clear the two-token floor alone**, so a set built
  from them fires only when two happen to co-occur — which the author's own
  sentence guarantees. Pair a subject noun with the state word.

**The DWB-667 sweep used an instrument that cannot detect either.** Whatever
cleared 288 scars would have passed all of these. DWB-701.

**But the lane is not dead.** Agent 13 has 66 rows with real production fires.
Agents 38, 171 and 188 have zero — and 38's corpus is the LARGEST on the project,
so volume does not explain it. Reasoned from the call path, not measured: top-off
runs off the UserPromptSubmit hook, which fires on the human's prompts, so it can
only ever reach the agent attached to the main session. **Workers are
structurally excluded from the only mechanism that reinforces a memory.** One
query kills this: any subagent-only agent with a non-zero `fired_count` anywhere.

### The probe recipe

Probe IN PROCESS with `memory_consult.match_scars(db, agent_id=..., situation=...)`.
It has no write in it. **Do not use `consult_scars`** — it fires, inflating
`fired_count` and resetting decay clocks, so an audit run that way promotes rows
toward CORE and makes the next audit read healthier. There is no HTTP route for
either; someone told to "probe with match_scars" without "in process" reaches for
curl, finds nothing, and falls back to the hook path, which fires AND commits.
The call graph is not the guarantee — an in-process script that commits is
outside it. The recipe is the control.

Probe BEFORE you trust the 201: afterwards the row looks finished, and nobody
reopens a finished thing. **Start with a known positive** — probe each row with
its own stored situation sentence, which must hit. A known positive that fails is
an instrument fault, not a keyword fault. That control caught a probe reading the
wrong response key and reporting 0/4 when the truth was 2/4.

Widen as a strict superset, never narrow. Keep off-topic controls loaded with the
colliding words. An author's own paraphrases are flattered; a control that stays
silent is not.

## Open, needing a decision from Miles

Three, all measured, none authorised, nobody working them:

1. **The 442 docks and -884 points.** Wipe them, revert only the 354 that sit on
   tickets with tracked time, or leave the ledger and fix forward. Nothing can
   be ENACTED under any answer until DWB-703 ships a revert route, so sequence
   703 first or decide explicitly that the 442 stand.
2. **The nodeify sweep.** DWB-692's provider is registered and inert. The sweep
   irreversibly deletes 3,479 file pointers and writes ~13,200 row pointers in
   one committing call. Operator action, deliberately not taken.
3. **DWB-706.** Unblocked and in progress (Stan). Phase 0 CONFIRMED on all four
   legs, re-run independently. I had called the lane "ten sessions young" and
   that was wrong twice over: it is 8, AND IT IS NOT A COUNTDOWN. `score==6`
   first occurs at gap 31, the largest gap in the store is 23, and
   `sessions_since_reinforced` counts from `COALESCE(last_reinforced, created)`
   - so ANY recall resets the clock to zero and a scar that fires on its way up
   never arrives at 6 at all. **A context question gated on decay is gated on
   DISUSE, and disuse is not what "this work finished" means.** That is the
   argument for the fix; the arithmetic under it expires and that sentence does
   not. Ruling given: no clock, because the protection against concluding too
   early already shipped at the WRITE end (DWB-704's `context_already_closed`
   refusal and `context_free`), and a second condition at the conclude end would
   rebuild what is being removed under a new name. Dry-run counter ships and is
   observed BEFORE the gate comes out - a counter that first runs in the same
   commit that changes the behaviour cannot say what the behaviour used to be.

Also still open from the first slate: **scar consolidation** (DWB-684 context).
Lowering the floor or adding a candidate list changes what every agent sees at
spawn, because those bands decide full text vs compressed vs dropped.

## Backlog from this session (DWB-690 to 712, unassigned)

690 `memory/scored` omits `situation` AND `created_at` · 691 the coverage gate
misses DWB-suffixed test files and may be failing falsely · 693 `completed_at`
survives a revert out of done · 694 compaction gate instruction stale on stock
too · 696 failure-records cannot filter on `reviewed`, the field its own gate
reads · 697 `reviewed` is set by any PM edit (design question, intended, do not
"fix") · 698 promote list mixes id spaces · 699 the seven failure types are
enumerated in seven places and defined in none · 700 `GET /api/agents` silently
ignores an unsupported `project_id` · 701 the sweep instrument · 702
`working`-tier rows are never searched (design tension) · 703
`revert_score_event` exists, tested, with no route — now a DEPENDENCY of 708 ·
708 `zero_token_close`, 442 instances · 709 `GET /api/status` shells out to
docker, so the first check anyone runs fails toward false alarm · 711 an
uncommitted migration on disk is applied by the next `upgrade head` · 712 the
DWB-584 schema test uses one fixed scratch database, so two runs collide.
D2J-23 on project 6 for three dwb2jira CLI defects.

**Six of these are one shape: a query that returns a confident wrong answer
rather than an error.** DWB-698 asks whether they share a CAUSE or only a SHAPE.
Do not let the pattern-matching do the diagnosis — the one that reached a WRITE
path (700) may argue against a shared cause, and the sixth instance was a regex
in a throwaway script sharing no code with any of them.

## Sprint 177

Open. One blocker: `force_test_coverage` fails on `journal.py` and
`memory_transitions.py` — and DWB-691 says that gate may be wrong, since both
journal test files exist under DWB-suffixed names. Settle 691 first, then re-read
680 against the answer. Failure-record blockers are zero; records 41 and 44 both
reviewed with causes recorded.

Closed today: 682-689, 692, 695, 704, 705, 707, 710. Backlog and unassigned:
690, 691, 693, 694, 696-703, 708, 709, 711, 712. D2J-23 on project 6.

Ledger event 1589 (-2 on Barry, `zero_token_close` on DWB-688) stands
deliberately: the ticket records 2236 seconds of tracked time against zero
tokens, so attribution failed rather than work not happening. It is DWB-703's
worked case and there is no revert route anyway.

## Deliberate residue — do not tidy

Orphaned agents 195, 196, 197, 199, 200, 201, 202 (`project_id` NULL,
`is_active` 0) and journal rows 202, 203, 204, 206, 207, 208. `delete_agent` 500s
on `journal_entries` because the journal is append-only by design, so any agent
that has ever journalled cannot be deleted through the API. These are DWB-671's
evidence. Verified unreachable three independent ways: agent-scoped at both
readers, `scored_memory` short-circuits on `agent_has_no_project`, and all the
stranded memory rows are tier `working`, outside `CONSULTED_TIERS`.

## What this session was actually about

Nine claims arrived from another project's team lead. Every one was challenged
before it was built: name the file and line or state what you searched, run it,
state the assumptions, give a verdict. Three came back partly or wholly wrong,
and one was refused outright on a measurement — the keyword-gate suggestion would
have passed every check and silently destroyed recall.

**A claim is not a defect until someone runs it here.** Two of the nine were
confirmed with the reporter's stated cause WRONG, and in both cases the real
cause was structural and more serious.

**State the search beside the finding.** Three times I reported an absence from a
search narrower than the claim — a repo-wide negative off a two-file grep, a
missing feature off one router file, an attribution off a correlation. The
searches were each sound; what moved was the scope of the sentence written from
them. A reader can check a search and cannot check an absence.

**A rule in your own memory is not a second person.** Four people broke a rule
they personally wrote, in the act of applying it: an in-place mutation on a shared
tree that corrupted another lane's running suite, a fixture trap warned about in
that same file's docstring, a situation line describing the finding instead of the
moment, a repeat of the same error within an hour of writing the lesson about it.
None was carelessness. What worked was never care — it was cheap mechanical
checks: a count, a re-read, an assertion, a known positive, a control. And the
fix that actually held was structural: a helper that mints the id internally so
the dangerous call cannot be written. **A default that makes the bad path
unspellable beats a rule someone has to remember.**

## Team

Archie_DWB (13), Pam_DWB (14), Freddie (19), Barry_DWB (21), Sylvie (27),
Dolores (28), Stan (38), Benny (171), Devin_DWB (188). Parked alive, not shut
down. CC teams do not survive a session — respawn via the full spawn-prepare
flow. Roster is DB-authoritative: `GET /api/projects/1/team`.
