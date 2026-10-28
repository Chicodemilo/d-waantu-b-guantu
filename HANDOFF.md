# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-10-28)

HEAD `b469ad0` on master, seven commits today, pushed, tree clean.
Alembic head `dwb682a1b2c3`. API restarted and verified live.

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

Three substrate changes, all filed, none authorised, nobody working them:

- **Scar consolidation** (DWB-684 context): lowering the floor or adding a scar
  candidate list changes what every agent sees at spawn, because those bands
  decide full text vs compressed vs dropped.
- **Indexing the live corpus** (DWB-692, DWB-701): the node graph is grounded
  only on `.dwb/memory/**/memory.md`, frozen at 2026-10-01 and sealed. The live
  `agent_memories` store is unindexed, so `relevant_lessons` returns pointers to
  files agents are forbidden to open. It has never delivered a lesson in any mode
  — with the seal off, stock returns a section heading.
- **Persisting commit rows** (DWB-695): DWB has never received a commit from
  anywhere. `.git/hooks` here is eleven stock samples; IND's `core.hooksPath`
  points at an empty directory, which also disables the defaults. `install-git-hooks.sh`
  ships and nothing runs it, and `.git/hooks` is never in git, so every fresh
  clone is unarmed by construction.

## Backlog from this session (DWB-690 to 703, unassigned)

690 `memory/scored` omits `situation` AND `created_at` · 691 the coverage gate
misses DWB-suffixed test files and may be failing falsely · 692 node-graph
grounding · 693 `completed_at` survives a revert out of done · 694 compaction
gate instruction stale on stock too · 695 commit persistence · 696
failure-records cannot filter on `reviewed`, the field its own gate reads ·
697 `reviewed` is set by any PM edit (design question, intended, do not "fix") ·
698 promote list mixes id spaces · 699 the seven failure types are enumerated in
seven places and defined in none · 700 `GET /api/agents` silently ignores an
unsupported `project_id` · 701 the sweep instrument · 702 `working`-tier rows are
never searched (design tension) · 703 `revert_score_event` exists, tested, with
no route. D2J-23 on project 6 for three dwb2jira CLI defects.

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
