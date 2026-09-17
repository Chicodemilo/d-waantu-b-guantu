# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-09-17, S82 open at 14/17, everything pushed)

- **Origin at `6f38cf3`.** Eighteen commits today, nothing local, tree clean.
- **S82 (sprint 171) still OPEN**, 14 done, 3 left. Not closed, deliberately: the three remaining are the retrieval lane and Miles has not released them.
- Backend 2152 pass, frontend 388 pass.
- Uvicorn (8000, `--reload`), Vite (5173) and the MySQL container all left running.

## What shipped today

Started as a doc cleanup and turned into an instrumentation repair. In order of consequence:

- **Token capture was five times under** (DWB-580). A session row recorded its first turn and froze; every later stop hit an idempotency guard and returned. Six sessions in one day: 1.9M recorded against 9.8M real. The guard was correct for one-shot subagents and wrong for long-lived teammates, and usage moved onto that path on 2026-09-15. Fixed by a sweep that re-parses grown transcripts, which is correct whether or not repeat events fire at all — a design that sidesteps a question we could not answer. **Forward-only: historical figures stay wrong, and they are wrong in BOTH directions.** Today under-reports; 2026-09-15 probably over-reports (overlapping re-parses). A trend line across those days means nothing.
- **Ticket attribution missed 5 of 6 workers** (DWB-576). Resolution ran once, at session creation, asking which ticket an agent was assigned — 17 to 25 minutes before the tickets were assigned. Now inverted: the ticket claims its agent's unattributed sessions, fill-only, sprint-bounded. Also self-assigns when an agent starts an unassigned ticket, which was how two tickets became permanently uncostable.
- **Attribution provenance** (DWB-581). A claimed session is a best guess; a resolved one is a fact; they used to look identical. Four states with NULL meaning honestly unknown. Guarded by AST tests over all six write sites.
- **Write-on-close gate decoupled from prose** (DWB-564). It proved participation by reading dated headings in `memory.md`, which condensing removes. Three agents landed in that state in one day, all by condensing *correctly*. Now reads `max(last_memory_write_at, mtime)`.
- **Sprint-close mint fixed** (DWB-566), plus the ten tickets stranded on a March placeholder since June, deleted.
- **Doc sweep from removals** (DWB-568/569/570): eleven stale claims, a drift checker that fails when docs name code that no longer resolves, a help-centre audit and the missing Nodes section. `FILE_TREE.md` and `PASSIVE_TRACKING_PLAN.md` deleted.
- **Four clone-fragility bugs** (571/572/573/574/575): a gate judging every project by this platform's coverage, a button running our suite under other projects' names, a page printing raw JSON, a hardcoded prefix, and a hardcoded home directory that shipped a username and reported "in sync" having read nothing.

## FIRST JOB NEXT SESSION

**The retrieval lane, DWB-577 then DWB-578, then DWB-579.** Specced in full, unassigned, Miles has not released them.

The problem they solve: the node index works and reaches nobody. `GET /api/tickets/{id}/related-nodes` returns ten ranked lessons and ten code pointers for a real ticket. But `spawn-prepare` takes only role, name and project, so there is no ticket to rank against and `relevant_lessons` has returned `[]` for an entire sprint. Meanwhile memory is delivered by pasting the whole file into the spawn prompt, which is why the 4500 ceiling exists.

Both are the same defect: **memory is injected whole and pointers are injected never.**

- **577**: split memory into a pinned core (always injected, tight cap, agent chooses what is pinned — Miles's ruling, abuse handled by stick) and a retrievable body.
- **578**: optional `ticket_id` on spawn-prepare; returns the core, the ranked body and the pointers. Cheaper than it reads — the response field already exists and is already pointer-only by design. Carries two requirements with teeth: an empty retrieval must be *loud* (three distinct states, not one empty list), and pointers are labelled advisory and non-exhaustive.
- **579**: raise the body's ceiling only after 577 and 578. Raising first is a treadmill.

**Miles rejected an agent opt-out mechanism** ("this node stuff sucks, let me explore"), and the reasoning matters: a switch replaces the signal we need (ranking put the wrong file first) with one we do not (someone opted out).

## Known gaps, none blocking

- **`session-complete` fails two different ways, and they get conflated.** Two workers hit `422` because `session_id` is required and a subagent does not reliably know its own. A third hit `422` for an unrelated reason — `lessons` expects a list and he sent a string. A fourth filed successfully first try. The append fallback works for all of them, so the workaround hides the distinction. Participation still records either way; the summary and token figures a wrap-up writes to the DB do not. The session-id case needs the id to reach workers at spawn or the field to become optional; the schema case needs one line of documentation.
- **The token estimator is character-based** (`max(len//4, words)`), so it rewards lexical compression that a real tokenizer would punish. Vowel-dropping "saves" 24% by that measure and would almost certainly cost tokens in reality. A gate trusts this number.
- **Memory ceiling pressure is system-wide**, not just here: agents on CI and IND were at 99% today. Several condensed mid-task.

## Process lessons earned today

- **The failure family** (Barry's framing): a mechanism reporting that it *ran* rather than that it *landed*, whose confidence is indistinguishable from knowledge. Five instances in two days. When a check returns nothing, confirm it *can* return something before trusting the negative.
- **Do not decide a design while waiting for the answer that settles it.** I broke this three times on one ticket, costing three full implementations including a live schema change applied and reverted. If you are asking a question to settle a design, you have forfeited the right to decide until it is answered.
- **Short messages cross less.** A long correction takes longer to read than it takes to become obsolete.
- **Duplicated logic is where a correct fix goes to be half-applied.** Two identical increment blocks, two coverage globs, six write sites where the AC implied three. When an AC says "every write", count them and state the number.
- **A test that names the defect must go red; one guarding an adjacent risk legitimately passes both ways.** Never count the second as evidence of the first.

## Team

Pam_DWB, Barry_DWB, Stan, Sylvie and Freddie all worked today and were asked to land memory wrap-ups before shutdown. CC teams do not survive sessions — respawn per playbook: spawn-prepare, pending marker, paste `memory_full`.
