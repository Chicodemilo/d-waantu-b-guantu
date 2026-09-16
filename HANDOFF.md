# Handoff: D'Waantu B'Guantu

> Session-to-session continuity. Read at session start, update at end.

## Current state (2026-09-15 evening. S81 CLOSED, pushed, team shut down)

- **S81 (sprint 160) CLOSED, 27 done.** "Nodes Visual Layer (Cloud, Detail Overlay, Limiter Search)". Origin master at `b555409`, 15 commits pushed. All gates verified green at 20:35 before close. Backend 2050 pass (result 196, taken against committed HEAD), frontend 377 pass (result 193).
- **Per-agent split:** Freddie 11, Barry 9, Stan 7. Worth knowing that the quietest lane was the largest; anyone reading the session thread would infer the opposite, because the noisy lane was the one collecting amendments.
- **Nodes visual layer is live** at `/projects/:id/nodes`: weighted cloud with a top-0.5% headliner tier, detail overlay with neighbour hops, substring limiter search with an optional connections toggle, per-project scan exclusions with a directory browser, and a rescan control with an inline confirm.
- **Also shipped:** stick redemption (half rounded up, once per stick), peer carrots/sticks notifying via agent comms, agent memory now lessons-only, three token-attribution bugs fixed, timestamp parsing corrected across 14 components.

## FIRST JOB NEXT SESSION (decided 2026-09-15, do not relitigate)

1. **Fix the mint: DWB-566** (todo, sprint 160, unassigned — give it to a backend worker). Miles chose option 2 of three: mint the test ticket onto **the closing sprint as backlog**, delete the next-sprint search entirely rather than repair it, leave the ticket unassigned. Small change; most of the work is tests, including the never-covered normal case of closing a sprint when no other sprint exists. Full root cause and AC are in the ticket.
2. **Then delete the ten stranded tickets.** DWB-445, 453, 467, 480, 495, 498, 504, 507, 515, 521 — all on sprint 23 under inactive agent Sage, eight still `todo`. Miles's decision: delete them once DWB-566 lands, **not before**, because they are the evidence the mint never worked. They are stale prompts for a redundant second test pass; the code they name IS tested (132 backend test files, 2050 backend / 377 frontend passing). DWB-515 and DWB-521 also close as duplicates of DWB-566.
3. **Carry-forwards, eleven**, all backlog/unassigned on sprint 160 except 566 which is todo: DWB-547, 548, 550, 555, 558, 561, 562, 563, 564, 565, 566.

## The mint bug, root-caused (DWB-515 / DWB-521)

The sprint-close auto-mint has **never worked**, at every close from S69 to S81. Root cause verified in `services/sprint.py`, not inferred:

- **Sprint half:** the lookup selects `status in (planned, active)` ordered by `sprint_number ASC` and takes the first. That is a correct implementation of a **queue model this project abandoned** — we create one sprint at a time and never queue them, so the only `planned` row is a March placeholder (id 23, number 14) and ascending order picks it every time. Repair is not "fix the lookup", it is "replace an assumption".
- **Assignee half:** `_find_agent_by_role` is an unordered `.limit(1)` with **no `is_active` filter and no ORDER BY**. Latent second defect: with two active testers the assignment would be nondeterministic by query plan.
- **Best framing:** why is there a search at all, when the sprint being closed already holds both answers? (question: Stan; "a search that cannot fail beats a search that fails loudly": Pam)

## Process rules earned tonight (all cost real cycles)

- **Amendments, three clauses.** A description PATCH is not delivery to an in-flight worker → send a direct message. The **ack** is the load-bearing half; no worker flips to `in_review` without checking their inbox. And **do not issue an amendment until the design is settled** — clauses 1-2 cannot catch a message landing during a long tool call. Four wasted build cycles all trace to relaying half-decisions.
- **Review from the code, never the worker's comment.** Their comment is accurate against the spec *they* could see. This caught two wrong-design builds.
- **A ticket carries its own scope.** Cite the source too, and say whether carried text is verbatim. But this is provenance *hygiene, not correctness*: verbatim copying propagates a wrong source faithfully. Anything load-bearing gets checked against the code.
- **Worked examples in memory are load-bearing** — verify them or label them as reported. A wrong example launders a false premise into a rule that looks tested.
- **Never `git add -A <dir>`.** Stage the explicit file list for the ticket under review. A broad add swept a rejected design into an unrelated commit (`6c71168`), making unapproved code the repo's committed behaviour; `b555409` names it as superseded.
- **Silence is not death.** A worker writes nothing to the DB between `in_progress` and `in_review`. I respawned a live worker and the duplicate collided on six files.
- **The failure shape of the night, five instances:** a mechanism *right about the fact, wrong about the blame* — an outage presenting as a missing ack, a gate change as a delinquent non-writer, a stale roster row as an absent participant, a stale test result as a passing gate, a green suite as a recorded one. When a gate names someone, ask whether it can distinguish "did not" from "could not" from "was never here".
- **Automated steps that fail quietly while the surface looks healthy** is a class worth sweeping, not three point fixes. The tell: a success signal reporting that a step *ran* rather than that it *landed*.
- **Working condition, not a courtesy (Pam):** being corrected was treated as useful rather than as friction, so nobody had to defend a position to keep their standing, and four wrong theories were discarded quickly. That is why the mint bug was found.

## Gotchas (carry forward)

- Memory ceiling is a **treadmill** if only raised: it exists because memory is injected whole at spawn. Real fixes are lessons-only content (shipped) and retrieval-based delivery. Three of six agents were refused a write within one hour tonight.
- `run_tests.sh --post` **silently loses results** when `--context` contains an apostrophe (DWB-565): tests pass, nothing is recorded, script exits 1.
- Sprint close consumes a ticket_number; reserve numbers AFTER closing.
- Do not close a sprint while a worker is writing backend files: uvicorn `--reload` on a half-written module 500s the memory endpoint and the gate then names innocent participants.
- The write-on-close gate filters `is_active` before testing writes, so a dark agent cannot block a close.
- Uvicorn (8000, `--reload`) + Vite (5173) left RUNNING, MySQL container up.

## Team

Nobody live. Pam_DWB, Freddie, Barry_DWB and Stan were shut down after landing session-complete wraps (all four verified lessons-only, which tested DWB-560 on its own session). CC teams do not survive sessions — respawn per playbook: spawn-prepare, pending marker, paste `memory_full`.
