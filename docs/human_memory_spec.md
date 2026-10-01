# `human_memory` Mode — Feature Spec

> Origin: drafted by Archie_IND on IND (2026-09-29), prototyped live on IND agent 70,
> handed to DWB for build. Three review defects found by Archie_DWB and fixed by the
> author before handoff: the sessions relabel, derive-don't-store moved into § 3, and
> v1's context-death answer named as the manual SCAN.
>
> **This file is canonical.** It supersedes `~/dwb-human-memory-feature.md` and the copy
> in the IND checkout, both of which are now stale. Amend here.
>
> Status: spec handed off, ticket slate awaiting approval. Not built.
>
> Editing rule from the author, kept: the recorded RULINGS carry their reasoning on
> purpose. The reasoning is the point — do not strip it to shorten the doc.

## 0. The thesis

> **Some scars don't heal. The lesson you learn, never forget, and move on. Learn the big
> lesson.** — Miles Chick, 2026-09-29

Everything below is machinery for that sentence.

"Never forget" and "move on" only conflict while the rule and the story live in the same
place. Split them and both are true at once: the rule rests in CORE at 10 forever, the
incident goes to the journal, and the agent stops carrying the wound while keeping what it
taught. **Moving on is not forgetting — it is declining to re-read the episode every session.**

And the corollary that drives the whole promotion mechanism: **a scar that will not heal was
learned too small.** A lesson that keeps recurring was not forgotten, it was filed at the
wrong altitude. Learn it big and it stops being a wound, because it is a principle.

## 1. What it is

A per-project memory mode. Stock DWB memory is one flat markdown blob with a token ceiling.
`human_memory` replaces it with a consolidation model borrowed from how memory actually
works: encode fast and unsorted, sort at a boundary, let the unimportant fade, keep the
residue.

**Two stores, two jobs.**

| | Memory | Journal |
|---|---|---|
| holds | the RULE | the STORY |
| loaded | every session, automatically | never — on demand only |
| costs | tokens forever | nothing until read |
| shape | scored entries | append-only episodes |

You keep *don't touch hot things*; you lose the afternoon you learned it.

> **RULED (Miles Chick, 2026-09-29).** "Some giant things always stay with you. Smaller things
> gently fade. Some things seem to stick for no reason but that's rare, and they are probably
> sticking for a reason you don't comprehend so you don't question it too much."
>
> The last clause is a real constraint, not a flourish: **a memory that persists without a
> legible reason is not evidence of a bug.** Encoding is driven by prediction error, which
> outruns explanation — demanding that an entry justify itself in words is how you delete the
> thing that was working.

> **RULED.** Keep it in **tight tools** to limit creep. The algorithm lives in the tooling so
> agents cannot freelance it.

## 2. The tiers

- **CORE** — always true, always loaded, **10 forever**. Two entry paths: *ruled* by the human,
  or *promoted* from a scar after a recurrence proved the lesson was scoped too narrowly.
- **SCAR** — **a real tier with a resting place at 6.** A scar decays to 6 and stays there.
  It does not expire on a clock and it is not on probation.
- **SCAR · context-bound** — the exception. Dropped when its context dies, and journaled.
- **WORKING** — box facts, tool shapes, API quirks. Fades unless touched.
- **JOURNAL** — 0 until reached for.

> **RULED (Miles Chick, 2026-09-29).** Scars are a TIER. They decay to **6** and rest there.
> Context-bound scars are the exception: they are dropped when the context is gone, and
> journaled on the way out.
>
> *"The nature of impermanence baby. Time heals all wounds. And if it doesn't you'll learn it
> again — that's why journaling is important."*
>
> **A correction was needed here.** An intermediate draft collapsed scars into "probation —
> either it graduates to CORE or it dies with its context." That was wrong: it deleted the
> resting tier entirely and made every scar a pending decision. Scars rest. What is periodic is
> not their status but a **scan**, below.

### THE SCAN — the judgment step, and the genuinely LLM-shaped part

**Entries sitting at 6 get periodically re-examined against the current context.** Not "has
time passed" — *does this still apply here.* That question cannot be answered by arithmetic;
it needs a reader who knows what the project is currently doing. It is the one place in this
design where model judgment is the mechanism rather than a fallback.

- **Context gone** → drop it, and journal it on the way out.
- **Context alive** → it stays at 6. No further action, no ceremony.

### RECURRENCE IS DIAGNOSTIC — the most important mechanism here

> **RULED.** *"If you do the same thing it means 1 of two things: 1, that the context is still
> actually around, OR a more durable lesson should have been learned. It should have gone into
> CORE as a broader point. Your focus was too narrow. That's why you failed again. That's why
> we journal. Part of the path of forgiveness."*

When a failure repeats, **the repetition itself tells you which mistake you made** — and the
journal is what lets you tell them apart, because it holds what was decided last time and why.

| What the journal shows | What the recurrence means | Action |
|---|---|---|
| the scar was **dropped** as context-dead | the context was **still alive** — the scan was wrong | restore it; the scan needs tightening |
| the scar was **sitting at 6** and the failure happened anyway | **the lesson was scoped too narrowly** — it was learned at the wrong altitude | **promote to CORE, re-stated broadly** |

The second row is the sharp one. Failing again *while holding the scar* is not forgetting — it
is evidence the scar was written too specifically to catch the shape it belongs to. The
correct response is not to try harder; it is to **re-state the lesson at a broader altitude
and move it to CORE.**

Worked example from the prototype session: a shell pipe returning `tail`'s exit status was
first written as a scar about pipes. It recurred as a harness notification reporting the
wrapper shell's status — the same failure, and the pipe-shaped scar did not catch it. The
correct altitude was *anything that reports on a command is a different process from the
command*, which is CORE material. Narrow scar, repeated failure, promote and broaden.

**This is why the journal is the path of forgiveness rather than a record of blame.** Dropping
a scar is safe because recurrence is survivable; recurrence is *instructive* because the
journal says which of the two errors it was. Neither works without the other.

### Promotion — the test for scar → CORE

**A scar is promoted when it RECURS despite being held.** That is the evidence, and it is
empirical rather than a vibe: the failure happened again while the lesson was in memory, so
the lesson was at the wrong altitude. Re-state it broadly and move it to CORE.

A scar firing usefully in an unrelated context is corroborating evidence of the same thing —
it means the true scope is wider than where it was born.

⚠️ **The accumulation risk moved, it did not vanish.** CORE now grows and never fades, so a
loosely-applied graduation bar rebuilds the graveyard one tier up — and CORE is worse, because
it is always loaded. The bar must be logged evidence (which contexts, when), not "this feels
universal."

### Context death

A scar about a bug dies the day the bug is fixed; a scar about a lane dies the day the lane
ships. That is a **step to 0**, not decay.

**WHAT v1 SHIPS: the SCAN, and nothing automatic.** §3's table says a context-bound scar steps
to 0 "when the SCAN finds the context dead" — that is the whole mechanism in v1. No automatic
detector is built, and the table and this section must not be read as describing two different
things.

Candidate detectors for LATER, none validated: the lane closes; the paths it names stop
existing; or N sessions with no reinforcement and no recurrence. The third needs no
hand-labelling and is therefore the likeliest v2, but it is absence-of-evidence and should not
ship unattended.

This is safe to leave manual precisely because **recurrence makes a wrong drop survivable** —
an aggressive manual scan plus a journal beats an unvalidated automatic detector.

## 3. Weights and degradation

**THE CLOCK IS SESSIONS, NOT DAYS.** Every column below counts SESSIONS, not calendar days.

> **RULED (Miles Chick, 2026-09-29).** A session IS the day — *"a day is an interval bw sleep."*
> Decay tracks EXPERIENCE, not calendar: an agent that has not worked for three weeks has
> forgotten nothing, because nothing happened to it. The tick is a session open/close, which
> DWB already records.

**DERIVE THE SCORE, NEVER STORE IT.** Score is a pure function of `(tier, sessions_since_reinforced)`.
Stored scores require updating every row every session and drift out of sync with the rule;
a derived score cannot disagree with itself. **Whoever writes the migration: persist tier,
`sessions_since_reinforced`, `fired_count` and `context_key` — and compute the score at read
time.** This is stated here rather than only in a cover note because this section is what the
migration author will read.

| Type | This session | 1–5 sessions | 6–14 | 15–30 | 31–90 | 90+ | Floor |
|---|---|---|---|---|---|---|---|
| **CORE** | 10 | 10 | 10 | 10 | 10 | 10 | **10** — never moves |
| **SCAR** | 10 | 9 | 8 | 7 | 6 | 6 | **6** — rests here |
| **SCAR · context-bound** | 10 | 9 | 8 | 7 | 6 | 6 | **0** by step, when the SCAN finds the context dead |
| **WORKING** | 10 | 8 | 6 | 4 | 2 | 1 | **0** |
| **JOURNAL** | 0 | 0 | 0 | 0 | 0 | 0 | **0** baseline |
| **JOURNAL · retrieved** | 10 | 5 → 2 → 0 | 0 | 0 | 0 | 0 | back to **0** |

> **RULED.** Scars start at 10 today, 9 through five days ago, easing to 7 then 6 over a long
> time — resting at 6. Working memory ages toward 1 and falls off. The hard ones are 10 out of 10
> always. A scar only reaches 0 if the SCAN finds its context gone.

> **RULED.** The journal is 0/10 until you reach for it, then 10/10 that day. Miles proposed
> 7 the following day; **countered and accepted at a two-day tail (5 → 2 → 0)** — a retrieved
> entry lingering at 7 for a week defeats the whole reason the journal is free. A day or two of
> elevation is real, because if you reached for it today you are probably still in that problem
> tomorrow.

> **AMENDED by Archie_DWB, 2026-09-29.** The table above bottoms WORKING at **1** at 90+
> sessions while its Floor column says **0**, and how it gets from 1 to 0 was unstated. Caught
> by Pam_DWB reading the table against the band list below. Ruled:
>
> **The arithmetic floors at 1. Zero is not a computed score, it is an eviction state.** The
> decay function never returns 0 for any tier. An entry reaches 0 by a discrete act: the
> consolidation that finds it sitting at 1 evicts it, and per § 7 hard rule 4 it is written to
> the journal on the way out. The same shape already governs context-bound scars, which reach 0
> by the SCAN rather than by decay. One rule, two paths to it.
>
> This keeps § 4's "the math is not judgment" intact from both directions. The arithmetic says
> 1, which is a fact. Eviction is an act, and an act is something that can be logged, reviewed
> and reversed, where a score silently computing to 0 cannot be. It also means nothing is ever
> deleted by arithmetic alone, which is the property hard rule 4 exists to guarantee.

### What the score does

| Band | Treatment |
|---|---|
| **8–10** | carried in full text |
| **5–7** | carried, compressed to one line |
| **2–4** | flagged next consolidation as a demotion candidate |
| **1** | last consolidation before it goes |
| **0** | leaves memory → written to journal, never deleted |

Without this the number is decoration. With it, consolidation is sorting, not judgment.

### Reinforcement

Any memory that **fires** — prevents an error, gets cited, gets corrected against — resets to
10 and restarts its curve. The only way a score climbs. A lesson that matters keeps getting
reset and never nears its floor; one that never fires drifts down honestly.

This is spaced repetition with per-type floors. The parameters are tunable against real data
rather than argued about.

⚠️ **Unsolved in the prototype:** there is no clock. Nothing records `created_at` or
`last_reinforced` per memory, so every number above needs the row model, not the blob.

## 4. Encode raw, consolidate at the boundary

> **RULED.** "During a sesh you just throw in there... all fresh, top of mind. And then you
> manage before or after you go to sleep."

**Append RAW and unsorted during a session.** No tiering. Tiering in the moment rubber-stamps
in-the-moment salience, which is the judgment consolidation exists to make.

**Tag only what the moment knows** and cannot later be reconstructed:

- `cost:` none / low / high, and what happened — not how bad it felt
- `caught-by:` me / a worker / the human / CI
- `surprised:` did it contradict expectation

`caught-by` earns its place through one query: everything the human had to catch is a map of
where the agent's own checks do not look.

> **AMENDED (proposed and accepted).** Consolidate at **STARTUP**, not only shutdown. A session
> that dies badly never runs its shutdown — and those carry the richest lessons. Evidence:
> Miles's ssh dropped mid-session the same morning. Shutdown is the optimistic path; startup is
> the one that always runs.

## 5. The journal

Separate store, append-only, never auto-loaded, queried by tag and date range.

> **RULED.** Entries carry meta tags and a date. Retrieval is **never a full read** — it is
> *"I think that was about two weeks ago, to do with Greg, or ssh."* Tags + date + term.

> **RULED.** "If I reach for it 3 times, write it somewhere." **Counts go on journal entries
> and nowhere else.** The score is transient; the count is permanent and never decays. At **3
> retrievals** an entry stops being a story and becomes a rule, promoted into memory with its
> tier set by whether it survives without its context.
>
> Three is also the existing *bit-twice* threshold for working facts, so the system has one
> number, not two.

> **RULED, then softened.** Entries should open "Dear Diary." **Literal prefix dropped** — it
> is charming once, noise on the two hundredth entry, costs tokens in every grep result, and
> makes the first line carry no information. The instinct survives as the **voice rule**: write
> like a person who was there, not an incident report written for review. A sanitized entry is
> a useless entry, because the value is the reasoning that felt correct and was not.

> **RULED.** The playbook must know to **search the journal when lost** — stuck, going in
> circles, an answer revised twice, or asked "why did we do it that way?" when no ADR says.

**Retrieval is the reinforcement signal.** Reaching for an entry is logged, dated and
countable — which is the mechanism the first draft admitted it lacked. It is also the testing
effect: recall consolidates harder than re-reading.

**Memory must shrink; the journal may sprawl.** Opposite pressures — which is precisely why
they are two stores and not one.

## 6. Schema, versioning, the toggle

- `projects.memory_mode` — `stock` | `human_memory`. Default `stock`.
- `projects.memory_schema_version` — stamped in the file so v1 content stays readable by v2
  tooling.
- Memories become ROWS: `(id, agent_id, tier, body, context_key, cost, caught_by, surprised,
  created_session_id, last_reinforced_session_id, fired_count, source_journal_id, created_at,
  updated_at)`.
- `journal_entries(id, agent_id, dwb_session_id, entered_at, tags, retrieval_count, body)`.

> **AMENDED by Archie_DWB, 2026-09-29, after handoff.** This row list previously read
> `(id, agent_id, tier, body, score, created_at, last_reinforced, fired_count, context_key,
> source_journal_id)`. Two things in it contradicted § 3 and both are corrected above.
>
> **`score` is gone.** § 3 rules that the score is derived at read time and never stored. A
> stored score is a second authoritative copy of a derived fact, which is the failure § 7's
> hard rules 1 and 2 exist to prevent. It cannot be allowed to survive in the schema section.
>
> **`last_reinforced` becomes `last_reinforced_session_id`**, and `created_at` gains a
> `created_session_id` beside it. § 3 rules that the clock is SESSIONS, not calendar days, so
> the reinforcement marker has to be a session reference rather than a timestamp. A timestamp
> here would quietly reintroduce the calendar the ruling removed.
>
> Why this needed amending at all: the author's three post-review fixes landed in § 2 and § 3
> and did not reach § 6. Caught by Pam_DWB reading the schema section against the ruling
> section. Worth stating plainly, because it is the same shape twice in one document: **the
> section carrying the RULE and the section carrying the SCHEMA drifted apart, and the schema
> is what gets built.** A ruling that has not been applied to the schema section has not
> landed.

> **AMENDED by Archie_DWB, 2026-09-29, second amendment to this section.** The two row lists
> above previously carried `cost`, `caught_by` and `surprised` on `journal_entries` and not on
> the memory rows. They now sit on the memory rows and have been removed from
> `journal_entries`. The superseded line read:
>
> `journal_entries(id, agent_id, dwb_session_id, entered_at, tags, cost, caught_by, surprised,
> retrieval_count, body)`.
>
> **Why the move.** § 4 already puts these three on the raw memory append: "Tag only what the
> moment knows and cannot later be reconstructed", listing `cost`, `caught-by` and `surprised`.
> § 6 put them on the journal. Both could not be built. The tie was broken by asking what READS
> each field rather than where the document happens to list it, and all three are read against
> memories: § 2 gates the SCAN on `cost` and the SCAN runs over scars, which are memory rows;
> § 4 justifies `caught-by` through the query "everything the human had to catch is a map of
> where the agent's own checks do not look", which is a query over lessons; and `surprised` is
> prediction error, which § 1 makes the driver of encoding strength.
>
> **Why they do not live in both places.** § 7 opens by naming the failure mode as two stores
> that both look authoritative and disagree. A tag duplicated across memory and journal is that
> failure in miniature, and the copy nobody reads is the one that drifts.
>
> Raised by Stan hitting the collision while building against both sections at once.

> **THE PATTERN IN THIS DOCUMENT, and a note for whoever maintains it next.** This is the third
> amendment tonight and every one has been § 3 or § 6, the SCHEMA sections, disagreeing with the
> sections that carry the RULINGS. That is not three coincidences. It is a property of how this
> document was written: the rulings were captured as they were made, in the narrative sections,
> and the schema sections were written once and left. **The schema sections need re-reading
> every time a ruling lands**, because they are what gets built, and a ruling that has not
> reached them has not landed.

> **RULED.** The mode **never leaves beta**, and it is versioned. Deliberate: it keeps the
> schema free to move and keeps the warning below honest.

> **RULED.** Per-project toggle, on and off. **Warn before switching.**

### The toggle warning (verbatim)

> ⚠️ **Switching memory modes rewrites every memory this project has.**
>
> `human_memory` stores memory in a completely different structure, under different rules, with
> a different lifecycle. Switching is not a migration you can run and walk away from: every
> existing memory has to be re-read and re-tiered, and that is a judgment call an agent makes
> one entry at a time. It costs real time and real tokens, and switching *back* costs them
> again and loses the tiering.
>
> **Decide this at the start of a project.**
>
> We'll let you do it... but think it thru this time, sport.

## 7. HARD RULES — precedence

> **RULED.** Hard rules about using this system over stock DWB memory and the onboarding Claude
> memory. *"If you are writing something to CLAUDE.md, it better be a pointer to DWB mem or be
> like the last copy of the nuclear launch codes."*

The failure mode is not "the wrong memory is used." It is **two memories that both look
authoritative and disagree.**

1. **When `human_memory` is on, it is the ONLY memory.** Stock DWB memory is not written, not
   read, not consulted. Not a fallback, not a cache, not a second opinion.
2. **The harness's own file-based memory is not used at all.** It holds ONE thing: a pointer
   saying durable memory lives in DWB, with the API shape. Two homes drift, and the one that
   drifts is always the one nobody is reading.
3. **Writing to `CLAUDE.md` — or any auto-loaded file — is a pointer, or it is the last copy of
   the nuclear launch codes.** Nothing in between. An auto-loaded file beats a correct file
   every time, so anything landing there must be something every agent needs on every turn.
4. **Anything leaving memory lands in the journal first.** Journal, then rewrite. Losing it in
   flight is the one unrecoverable mistake in the design.
5. **CORE is never touched by automatic consolidation.** Only a human retires a ruled entry;
   only logged cross-context evidence adds a graduated one.
6. **A tool invoked for one tier still owns the whole-file total.** Per-tier tools each
   reporting "my tier is fine" while the file blows its ceiling is the obvious failure, and the
   promotion path between tiers otherwise belongs to nobody.

## 8. Top-off

A periodic self-check injected mid-session — not a memory reload, a check for being
confidently wrong in a loop:

1. Am I answering a question I already answered? Two revisions of one answer means the premise
   is wrong, not the detail.
2. Is the user getting what they asked for, or what I decided to give them?
3. What am I asserting from a summary or my own earlier message rather than the source?
4. What have I been told once and drifted from?

> **RULED.** Make it **programmatic** — per-project toggle plus interval, fired by the session
> runner on every DWB session. *"Archies don't have to remember to turn on the top off tool!"*
>
> This is the whole point. Anything depending on an agent remembering to switch it on will
> eventually be off — and off in exactly the sessions going badly, because that is when an
> agent is least likely to run housekeeping.

> **RULED.** Interval set to **10** ("let's start at an even 10 if we're guessing"). Honest
> caveat: no evidence behind it. Too frequent and it becomes wallpaper — and wallpaper gets
> skipped exactly like the rule it replaced. Needs tuning against real sessions.

> **OPEN — argued, not ruled.** Miles asked whether top-off should be gated on `human_memory`
> or available in any mode. **Recommendation: do not gate it.** It is orthogonal — about
> repetition and drift, not memory structure. Only *consolidation* is mode-specific.

**Live validation:** the hook fired for the first time on prompt 10 of the session that
designed it, and caught the agent building a file while Miles was still thinking out loud.
Question 2 was not clean.

## 9. Scope — which agents

> **RULED.** Institute on IND first as a prototype; write back to this doc on any discovery.

**Memory tiering: all agents.** Same ceiling, same dilution, same graveyard risk.

**Journal: per agent, and the TL reads across them.** This gets *more* valuable with more
agents — `caught-by: team-lead` aggregated across every worker's journal is the only map of
where a team is weak that is not the TL guessing.

**Top-off: highest value for whoever is juggling.** It catches looping across threads, a
lead's condition more than a worker's.

**CORE differs by role.** A worker's is the TL's standing instructions plus project gates.

**The toggle stays per-project and binds every agent on it** — not per-agent. Half a project's
agents on one memory model and half on another is exactly the two-authoritative-homes failure
rules 1 and 2 exist to prevent.

⚠️ **Untested:** whether consolidation repays its tokens for a short-lived worker that spawns,
does one ticket and dies.

## 10. Known weaknesses

- **No clock and no reinforcement counter in the prototype.** Fade stays editorial until
  memories are rows.
- **Consolidation is a judgment rewrite, not a transform.** A hook can prompt it; it cannot
  perform it. No version of this is fully automatic.
- **Context-death detection is unsolved** (§2).
- **Run 1 went 4136 → 3147 tokens with more content** — sorting exposed one lesson written
  three times in three costumes. **Run 2 GREW, 3147 → 3310.** There are honest reasons — the
  tier rules changed, a journal pointer went in — but that is a comfortable explanation to
  reach for, and a consolidation that only ever adds means the test is not being applied.
  **Watch run 3 before believing the model works.**
- **One demotion has happened, and only because Miles pushed.** Not because the test fired on
  its own. If nothing ever leaves without a human prompting it, the test is decorative.
