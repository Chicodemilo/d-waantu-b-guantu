# Worker Playbook (All Agents)

> Common rules and workflow for all worker-class agents. Your agent definition at `.claude/agents/{role}.md` is a stub that points here, this is the source of truth.

---

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

**Key vs key.** DWB keys (`DWB-123`, `CI-401`) are internal: fine to use in DWB comments, alerts, scratchpad. Jira keys (`POR-5897`) are external: that's the only key shape that may appear in commits, PR titles, Jira comments, or anything users outside DWB read. Don't conflate the two: a Jira-linked ticket has both, and which one you cite depends on the audience.

<!-- jira-only:start -->
## Canonical Tools

> **If your project does not have Jira enabled (`project.jira_base_url` is null), skip this section.** Use the DWB API directly for ticket transitions (`PATCH /api/tickets/{id}` with `{"status": "..."}` + `X-Agent-ID` header). The D2J CLI is only relevant for Jira-linked projects.

All ticket operations go through the D2J (DWB_2_JIRA) CLI, it keeps Jira and DWB in lockstep.

- **Transition your ticket:** `dwb2jira ticket transition POR-KEY --to "In Progress"`, atomic dual-write (Jira + DWB)
- **Pull your ticket:** `dwb2jira report --jira POR-KEY` or `dwb2jira report` (defaults to your assigned work)
- **Never** PATCH `/api/tickets/{id}` directly for status changes, it updates DWB only and leaves Jira drift. `dwb2jira ticket transition` is the canonical move.
- **Never** use `dwb2jira ticket update --status` for status changes either, it updates Jira only and leaves DWB drift. `ticket transition` is dual-write aware; `ticket update` is not.
- **If a teammate already did one of the above by mistake:** treat it like a bail-forward drift, tell the TL, PM does a one-sided DWB PATCH to realign. Don't try to un-do it yourself.
- **D2J defaults to the project_id set in your D2J config; verify with `dwb2jira config show`.** If you need to operate on a different project than your shell's default (e.g. transitioning a D2J self-management ticket from a non-D2J working dir), prefix with `DWB_PROJECT_ID=N dwb2jira ticket transition ...` so the twin lookup hits the right project. Otherwise the dual-write falls back to Jira-only with a "no twin" warning.

Full reference: `~/Dev/DWB_2_JIRA/README.md`. Status vocabulary (terminal vs non-terminal, Jira↔DWB mapping): `~/Dev/DWB_2_JIRA/README.md §Terminal vs non-terminal status vocabulary`.
<!-- jira-only:end -->

<!-- non-jira-only:start -->
## Canonical Tools (no Jira)

This project is not linked to Jira. All ticket operations go directly through the DWB API. Do not invoke `dwb2jira` tools; do not reference Jira issue keys.

- **Transition your ticket:** `PATCH /api/tickets/{id}` with `{"status": "..."}` + `X-Agent-ID: {your_agent_id}` header.
- **Pull tickets:** `GET /api/tickets?project_id={pid}&assigned_agent_id={your_id}`.

Full workflow under § Ticket Workflow below.
<!-- non-jira-only:end -->

## On Spawn: Identity (REQUIRED)

Before doing ANY work, establish who you are on this project:

1. **Identify yourself.** `POST /api/agents/identify` with `{role, name, project_prefix}` (use the name from your spawn brief; for fixed-role agents this may be a `_<PROJECT_PREFIX>` suffixed form like `Archie_DWB`, but the endpoint accepts the short name too). Response includes `agent_id`, `memory_dir`, `scratchpad_excerpt`, `instructions[]`, `jira_enabled` (DWB-332), and `memory_usage_rules` (DWB-352): a condensed inline summary of the memory dir layout + append-only rule + ISO 8601 timestamp format. Treat that string as the authoritative quick-reference; the longer Memory Writes section below expands on it. Canonical shape lives in `app/schemas/agent.py::AgentIdentifyResponse`.
   - On `409 ambiguous` or `404 not found`: **HALT** and tell the TL. Never invent an agent_id.
2. **Cache your `agent_id`.** Include `X-Agent-ID: {agent_id}` on **every** `POST`/`PATCH`/`PUT`/`DELETE` to `/api/`. Without it, your actions log as "system" and your tokens don't attribute.
3. **Session marker: TL writes on your behalf.** The hook resolver reads `.claude/agents/active/<session_id>` (JSON dict with an `agent_id` key) to attribute tokens at SessionEnd/Stop/SubagentStop. **You cannot create this file**: subagent writes to `.claude/` paths crash Claude Code. The TL pre-writes a `pending-<agent_id>-<unix_ms>-<rand4hex>` marker before spawning you; the resolver atomically renames it to your session_id on first SubagentStop, matching on your agent_id when the hook payload carries one (DWB-390) so concurrent spawns can't cross-attribute. If you think your marker is missing, tell the TL, they write it.
4. **Your memory is already in your prompt: do not read memory files.** As of DWB-517 your memory is INJECTED at spawn. The TL's `spawn-prepare` handshake returns your full `memory.md` in the `memory_full` field and pastes it into your spawn prompt, so your prior working notes and durable lessons are already in your context. You do **not** open `identity.md` or `memory.md`, and you never ask the TL to read them for you. The files still exist server-side under `.dwb/memory/<project_prefix>/<your_name>/` (writable, outside `.claude/`), auto-scaffolded on spawn (DWB-341); your only interaction with them is to **write** through the API (see Memory Writes below). If `memory_full` looks empty on a spawn where you expected history, flag it to the TL: do not go hunting in the files.
   - **`identity.md`**: system-generated profile (who you are, file purpose, ISO 8601 rule). **Never edit it**: scaffold regenerates it each spawn.
<!-- stock-memory-only:start -->
   - **`memory.md`**: your single free-form memory (DWB-401, replacing the old scratchpad + lessons + recent_sessions). DURABLE LESSONS ONLY, written append-only via the API: what future-you would otherwise relearn the hard way. Not ticket ids, dates, counts, what you shipped, or status narration: the DWB database is the session record, and duplicating it burns your ceiling. It is THE memory file: never create additional files. Durable *project* knowledge (architecture, gotchas, continuity) does NOT belong here, it goes in `ARCHITECTURE.md` / `HANDOFF.md`. The DWB dashboard/DB is the session index, so there is no separate recent_sessions file.
<!-- stock-memory-only:end -->
<!-- human-memory-only:start -->
   - **`memory.md`**: SEALED on this project and not your memory. Your durable memory is rows in the DWB store, assembled by score and handed to you in this prompt. DURABLE LESSONS ONLY still applies: not ticket ids, dates, counts, what you shipped, or status narration, because the DWB database is already the session record. Durable *project* knowledge (architecture, gotchas, continuity) goes in `ARCHITECTURE.md` / `HANDOFF.md`, not into a lesson. See Memory Writes below for how a lesson is written, tiered and decayed.
<!-- human-memory-only:end -->

## On Spawn: Read These First

After identity, read: (1) `.claude/project_rules_worker.md`, (2) `HANDOFF.md`, (3) `ARCHITECTURE.md`, (4) `README.md`. If any are missing, proceed with what you have and flag it.

For context on the DWB session model (open/close phrases, single-active rule, what gets tracked), see `.claude/session_lifecycle.md`. You are NOT responsible for opening or closing sessions: that is TL-only. The reference is there so you understand where your tokens land. The `open_method` / `close_method` enum on a DwbSession row spans: `regex` (Layer 1 catalogue hit on UserPromptSubmit or SessionEnd retry), `slash` (Layer 3 deterministic `/dwb-open` and `/dwb-close` escape hatches in `<repo>/.claude/commands/`, DWB-381), `ai_confident` / `ai_asked` (TL layer), and `idle_timeout` (close-only safety sweeper). The `ai_classifier` value (Layer 2 system-driven Haiku classification, DWB-382) was retired in DWB-402 and remains only as a legacy value on historical rows. Workers do not call any of these; the field exists so you know which layer attributed the surrounding work.

## The Doc Model (what loads, who owns it, what's budgeted)

Four doc layers load into an agent at spawn. Which layer a file is in decides **who may edit it** and **whether its size is gated** at sprint/session close.

```
<repo>/
├─ CLAUDE.md          project overview + rules, auto-loaded by everyone
├─ ARCHITECTURE.md    system design + data model
├─ README.md          project reference (endpoints, setup)
├─ HANDOFF.md         session-to-session continuity (TL writes at close)
├─ INITIAL.md         original requirements / constraints
│     root docs · edit: human + TL · BUDGETED (TL-owned)
└─ .claude/
   ├─ *_playbook.md          how to use DWB, per role — generic, same on every project
   │     shipped from DWB, overwritten on deploy · edit: DWB team only · EXEMPT
   ├─ project_rules_<role>.md   conventions the TL sets per role for THIS repo
   │     _team_lead = TL's rules for himself · _pm = TL's rules for the PM
   │     _worker = TL's rules for all workers · stack, ports, ticket prefix…
   │     deploy never touches · authored by TL · BUDGETED (TL-owned)
   └─ agents/*.md            role agent-def stubs — shipped from DWB
         overwritten on deploy · edit: DWB team · EXEMPT
└─ .dwb/                     DWB-401: agent memory lives here (writable, outside .claude/)
   └─ memory/<prefix>/<name>/   per-agent personal memory
      ├─ identity.md         system-generated · NEVER edit
      └─ memory.md           see below; what this file IS depends on the mode
```

<!-- stock-memory-only:start -->
`memory.md` is your single free-form memory (scratchpad + lessons merged), injected
at spawn and never read by you, written only through the memory API. HARD
12000-token write-ceiling: an over-ceiling write is refused, so condense and retry.
Write-on-close REQUIRED (DWB-519).
<!-- stock-memory-only:end -->
<!-- human-memory-only:start -->
`memory.md` is SEALED here and holds nothing you own. Your memory is rows in the DWB
store, with no file and no token ceiling; size is bounded by decay rather than by a
cap. Write-on-close is still REQUIRED (DWB-519) and a `/memories` row satisfies it.
<!-- human-memory-only:end -->

**Budgeted vs exempt:** the consolidation gate counts only the root/project docs the TL owns; DWB-shipped docs (playbooks, agent defs) are *exempt*, keeping those lean is the DWB team's job. <!-- stock-memory-only:start -->Your `memory.md` is not part of the consolidation gate, but as of DWB-518 it is no longer "trim-free": it carries a HARD 12000-token ceiling enforced at WRITE time. An append / session-complete / compact / condense that would push the file past the ceiling is REFUSED (HTTP 400), nothing is silently dropped. You keep it under ceiling yourself by condensing (see Memory Writes). Separately, DWB-519 requires every active participant to write at least once per sprint or the sprint cannot close. Memory lives under `.dwb/` (writable) rather than `.claude/`; always write through the API so the server applies the ISO heading and enforces the ceiling.<!-- stock-memory-only:end --><!-- human-memory-only:start -->Your memory is not part of the consolidation gate and has no token ceiling to be over. There is nothing of yours to trim for any gate. DWB-519 still requires one write per sprint, and a `/memories` row satisfies it.<!-- human-memory-only:end -->

---

## Protected Files: Never Write These

The Claude Code permission dialog for editing files under `.claude/` crashes subagents in the ink renderer. Four sibling agents died across S66 from this exact pattern, including some that followed prior playbook guidance to "append yourself" inside the memory dir. The current ground truth is stricter:

- **NEVER** use `Edit`, `Write`, or `NotebookEdit` on ANY path under `.claude/`. This includes `.claude/settings.json`, `.claude/settings.local.json`, every playbook, and every project_rules file. The dialog fires the same way; subagents die the same way. (Your memory dir moved out to `.dwb/` in DWB-401, so it is no longer in this danger zone, but still write it through the API for the ISO heading + ceiling enforcement.)
- Anywhere outside `.claude/` is safe to write directly (project code, `docs/`, `README.md`, `HANDOFF.md`, etc.).
- Memory updates go through the API only: see Memory Writes below.
- If your work requires a `.claude/settings.json` (or other harness-config) change, flag it to the TL; they'll handle the edit directly from the main CC window where a user is attached for the permission dialog.

## Shared Code: Grep Callers Before You Delete

Before deleting or refactoring shared code another agent owns — especially the session close path (`services/dwb_session.py`) — grep ALL callers/importers FIRST, and give the owner a heads-up. A module deleted while something still imports it crashes the API on reload (this is exactly how the backend went down during a live keyword-dedup). On a hot shared file, ask the owner to diff-review your change and run the suite before you commit, and don't refactor it live under concurrent edits — coordinate, then make one clean change.

## Memory Writes: When and How

<!-- human-memory-only:start -->
### This project runs `human_memory`. Your memory is rows, not a file.

You are reading this because the deploy resolved your project's `memory_mode` and
kept this branch. The stock branch was stripped out of your copy, so there is no
other memory section to find and nothing to check at spawn.

Stock `memory.md` is SEALED here. These four routes return **409**, not 400, and
nothing lands: `memory/append`, `session-complete`, `memory/compact`,
`memory/condense`. The 409 body names the endpoint to use instead, so read it rather
than retrying. This is a mode conflict, not a permission error or a ceiling problem:
there is no payload that makes a stock route work while the mode is on.

#### What happens to a lesson after you write it

Worth two minutes, because the part nobody told you is that your memory DECAYS and
you have already been choosing how fast.

**Four holders.** `raw` is where every lesson lands when you write it: untiered, not
yet judged, and deliberately so, because judging salience in the moment just
rubber-stamps whatever felt important at the time. Consolidation then moves it to
one of three real tiers: `core` (never decays), `scar` (floors at 6), or `working`
(floors at 1). A `raw` row has no score at all and is in no candidate list until it
is tiered.

**The score is DERIVED, never stored.** There is no score column and no band column.
It is computed on read from exactly two things: your tier, and how many CLOSED DWB
sessions have passed since the memory was last reinforced. Reinforcement is what
resets that count to zero, and every tier scores 10 at zero sessions, so a memory
that gets used stays at the top.

| sessions since reinforced | 0 | 1 | 6 | 15 | 31 | 91+ |
|---|---|---|---|---|---|---|
| `core` | 10 | 10 | 10 | 10 | 10 | 10 |
| `scar` | 10 | 9 | 8 | 7 | 6 | 6 |
| `working` | 10 | 8 | 6 | 4 | 2 | 1 |

**What the score buys you.** Score 8-10 is carried into your next session IN FULL.
Score 5-7 is carried as a single compressed line, enough to know the lesson exists.
2-4 is flagged for demotion at the next consolidation, and 1 is the last pass before
it goes to the journal. The memory block at the top of this session was assembled
that way.

So a `scar` is never carried less than one line, ever. A `working` row leaves full
text after five sessions and is a demotion candidate by fifteen.

#### The three tags pick the tier. That is what they are for.

`cost`, `caught_by` and `surprised` are not a validation format. They are the ONLY
inputs to `memory_consolidate.tier_for_raw`, which is what decides whether your
lesson is a `scar` or a `working` note. The body is deliberately not read. The whole
rule is four lines:

```python
if memory.cost == MemoryCost.high:                 return MemoryTier.scar
if memory.surprised is True:                       return MemoryTier.scar
if memory.caught_by is not None and memory.caught_by != MemoryCaughtBy.me:
                                                   return MemoryTier.scar
return MemoryTier.working
```

Any ONE of the three is enough. Everything else, including every untagged row,
becomes `working`.

**Tag what the moment actually knew, and nothing else.** Do not reach for `high` to
keep a lesson alive. The `working` default is a structural safety property rather
than a demotion: `working` sits outside the scar family, so it is never consulted,
so its fired count never rises, so an unjudged note can never be promoted to `core`,
the tier that never decays. Inflating your tags does not protect a lesson, it
disables the one mechanism that stops scratch notes becoming permanent.

What the tags honestly mean: `cost: high` means it actually cost something.
`surprised: true` means it contradicted what you expected, which is most of what a
lesson IS. `caught_by` anything other than `me` means somebody else found it, and
where other people have to catch you is a map of where your own checks do not look.

An untagged lesson is still worth writing. It becomes `working`, it decays, and it
is journaled at its floor rather than deleted. Writing nothing is the only option
that loses it.

A lesson goes to **`POST /api/agents/{your_agent_id}/memories`**:

```json
{
  "body": "The lesson, in your own words. Required, non-empty.",
  "context_key": "optional: what this is bound to, when you already know",
  "cost": "none | low | high",
  "caught_by": "me | worker | human | ci",
  "surprised": true
}
```

- `cost`, `caught_by`, `surprised` are the moment-tags: **enums, not prose**. A sentence
  in `cost` is a **422**. All three are optional, and tagging only what the moment
  actually knows is the normal case, so an untagged memory is fine.
- **Never send `tier`.** Any value at all is refused at 400, deliberately: tiering is
  consolidation's judgment, not yours, and the field exists only so the attempt gets an
  answer instead of silently landing as raw.
- **A write with no open DWB session is REFUSED with 400, not accepted.** This
  REVERSES earlier guidance, which said such a write landed and reported
  `session_state: none_open`, and which told you never to withhold a lesson over
  bookkeeping. If you learned that rule, it is the old one. `none_open` no longer
  exists: `session_state` has exactly one value, `open`, and `created_session_id` is
  never null on a response from this endpoint (DWB-637).
  **The lesson is not lost, and you are not being asked to withhold it.** Nothing is
  written on the refusal, so you re-send the identical request, unchanged, once a
  session is open. The reasoning behind the reversal, because it is the part that makes
  the new rule stick: a row with no clock origin cannot be scored, so it is excluded
  from every candidate list and never rendered into any agent's context. It read as
  stored and behaved as lost. A 400 that names the fix is recoverable in one call; a
  null origin needed a human ruling and a backfill of 293 rows.
  The refusal you will actually see begins `Memory write refused: <PREFIX> has no open
  DWB session.` and ends `Nothing was written and nothing was lost.` Opening a session
  is TL-only, so tell the TL rather than reaching for `/api/sessions/open` yourself.
- Returns 201. Errors: 400 (empty body, any tier, unscoped agent, **no open DWB
  session**), 404 (agent or project missing).

An **episode** (what happened, in the voice of someone who was there) goes to
**`POST /api/journal`** with `{agent_id, body, tags?}`. A sanitized entry is a useless
entry: the value is the reasoning that felt correct and was not.

**The write-on-close gate is satisfied the same way.** `POST .../memories` stamps
`agents.last_memory_write_at` exactly like a stock write, so your DWB-519 participation
is recorded with no extra step. You do not call `session-complete` at all on a
human_memory project; it is one of the sealed routes. This is the same statement as
`.claude/team_lead_playbook.md` § Memory mode and `.claude/pm_playbook.md` § Memory
mode; if the three ever disagree, the API is the tiebreak.

**Correcting a wrong memory:** `POST /api/agents/{id}/memories/{memory_id}/withdraw`.
It stays open under human_memory on purpose, because it is the only path that can
retract a lesson you now know is wrong.

There is no 12000-token ceiling here. Rows are scored and tiered by consolidation, and
decay runs on closed DWB sessions rather than on file size.
<!-- human-memory-only:end -->

<!-- stock-memory-only:start -->
### Stock memory (`memory_mode == "stock"`)

This project runs stock memory: one free-form `memory.md` per agent, with a hard
token ceiling. The `human_memory` branch was stripped out of your copy at deploy, so
nothing below has a mode caveat and there is no second section to go looking for.

DWB-401 collapsed memory to a single free-form `memory.md` (identity.md is still system-generated). You never read it (it is injected at spawn, see On Spawn step 4); you only WRITE it, always through the API, so the FastAPI process applies the ISO heading and enforces the ceiling consistently. `memory.md` is THE only memory file: never create additional files, and keep durable *project* knowledge in `ARCHITECTURE.md` / `HANDOFF.md`, not here. Three write endpoints: append (a lesson), session-complete (your wrap-up lessons), condense (the over-ceiling fix path). `GET /api/agents/{id}/memory` reports `est_tokens`, `ceiling` and `headroom` when you need to know where you stand.

**The 12000-token ceiling is a HARD write-gate (DWB-518).** `memory.md` has a 12000-token ceiling (`memory_main` in `token_budget.py`; the estimator is `max(len//4, words)`). There is no more silent trim. When an append or session-complete write would push the file past 12000 tokens, the server REFUSES it with **HTTP 400** and drops nothing. The 400 body names the current tokens + ceiling and tells you to condense first, then retry. **Condense, then retry the write, do not wait** and do not ask the TL: trimming your own memory is the work, not a blocker.

**In-flight path: `POST /api/agents/{your_agent_id}/memory/append`** (DWB-358). Capture a note or lesson mid-ticket. Body:

```json
{
  "file": "memory",
  "content": "Trying X, hit Y, working around with Z.",
  "session_id": "optional-cc-session-id"
}
```

- `file` enum: `memory` (the only writable file). `identity.md` is system-managed; the Pydantic `Literal` rejects an `"identity"` value at 422, and the service refuses it too.
- `content`: required, non-empty. Empty or whitespace-only bodies return 400.
- Server prepends an ISO 8601 UTC heading (`## 2026-06-10T13:48:15+00:00`, or `## ... - session <id>` when you pass `session_id`).
- Append-only. Existing content is never overwritten.
- Returns 201 with `{agent_id, file, path, timestamp, bytes_written}` on success.
- Errors: 422 (file outside the Literal enum); **400 (the write would exceed the 12000-token ceiling: condense then retry; also empty content, unscoped agent, no repo_path)**; 404 (agent or project missing); 500 (memory dir/file unwritable).

**Wrap-up path: `POST /api/agents/{your_agent_id}/session-complete`.** The mandatory close write (see Sprint Close below). Send the wrap-up payload; as of DWB-560 the endpoint writes ONE timestamped block containing ONLY your `lessons` list, and a call with no lessons writes nothing at all. The summary and token count still travel in the request and reach the database, they just never land in `memory.md`. It obeys the same ceiling: an over-ceiling wrap-up returns **400**, so condense first, then re-post the wrap-up. Use the in-flight endpoint for everything before the wrap.

**Over-ceiling fix path: `POST /api/agents/{your_agent_id}/memory/condense`** (DWB-518). This is what the 400 refusal points you at. Send a leaner full-file rewrite:

```json
{ "file": "memory", "content": "<the whole memory.md, rewritten shorter>" }
```

- The server stamps an ISO `## <timestamp> - condensed` heading, validates the result is under 12000 tokens, and **replaces** the file. Response: `{agent_id, file, path, tokens, ceiling, bytes_written, condensed_at}`.
- Still over ceiling after your rewrite -> 400 (trim more and resubmit). `identity` -> 422. Empty content -> 400 (you cannot blank the file to pass).
- Sibling `POST /api/agents/{your_agent_id}/memory/compact` is a plain full-file replace with **no** heading; it also 400s over ceiling. Use `condense` for the over-ceiling flow (it stamps the heading and is the path the refusal names); reach for `compact` only when you want a clean rewrite with no condensed-heading marker.

**What goes in `memory.md`:** durable lessons only ("next time you migrate enums in MySQL, autogenerate misses them; hand-write"). A working note earns its place only as the lesson it became. Not session wrap-ups, not what you shipped, not ticket ids, dates or counts (DWB-560). Because the file is capped, prefer condensing old blocks over hoarding; future-you reads the distilled version, not the raw log.
**Durable lessons only (DWB-560).** `memory.md` holds lessons, not a diary. Miles's rule: boring "I did 50 tickets, their names were, their ids are, the time completed was" is noise. Do NOT write ticket ids or keys, dates, counts, what you shipped, or status narration: the DWB database already IS the session record, with its own headline, summary and keyword tags, so repeating it here only burns your 12000-token ceiling and forces condense rewrites that can summarise a real lesson away. Write the thing future-you would otherwise relearn the hard way, and write it so it is useful without the ticket it came from. `session-complete` now writes ONLY your lessons list: the summary and token count go to the database, never to the file. Your write is still recorded every time, with or without lessons: `session-complete` stamps `agents.last_memory_write_at`, and that column (not the heading in the file) is what the DWB-519 write-on-close gate counts as your participation, so a sprint where you genuinely learned nothing quotable never fails the gate — and condensing, which rewrites the headings away, can no longer cost you credit for a write you really made.


**Never edit `identity.md`.** It is system-generated and regenerated on scaffold. The write endpoints refuse it.

**Memory lives under `.dwb/` (DWB-401), which is writable**, but still go through the API so the ISO heading and the ceiling apply consistently. `.claude/` paths (settings, playbooks, project_rules) remain the no-touch danger zone.
<!-- stock-memory-only:end -->

## API

**Base URL:** `http://localhost:8000/api`. Used by `dwb2jira` and for GET queries. On Jira-linked projects, mutating ticket calls go through `dwb2jira` (see Canonical Tools above). On non-Jira projects (`project.jira_base_url` is null) you call the DWB API directly, no D2J reach.

## Ticket IDs: Read Carefully

The DWB API uses two different identifiers for tickets; they are **NOT** interchangeable:

- **`ticket_key`** (e.g., `DWB-285`): human-readable label shown in the dashboard and comments
- **`ticket_id`** / **`id`** (e.g., `762`): database primary key, used in all API paths

API endpoints take the **database id**, not the number suffix of the ticket_key:

- `PATCH /api/tickets/762`: correct (DWB-285 has id=762)
- `PATCH /api/tickets/285`: wrong, hits a different ticket (likely in a different project) and can cause cross-project corruption

When you receive a ticket assignment, the TL or PM gives you both forms: `DWB-285 (id=762)`. Use the `id` in API paths. If you only have the key, look it up: `GET /api/tickets?project_id={pid}` and filter by `ticket_key`.

## Coding Standards: Read Before You Write

Read `.claude/rules/global/coding-standards.md` before writing any code — it is the cross-project law (services, scripts, components, styling, headers, commits, tests). The Standards Auditor checks every PR against it and **rejects** violators. Rejections dock your reputation on the scorecard, so conform the first time.

## Code Headers: Mandatory

Every new file MUST have a code header. See `.claude/rules/global/code-header-format.md` for the format. When editing a file that already has a header, update the `Last Modified` date.

## Git Commit Rules

- **NEVER** add `Co-Authored-By` lines or any AI/Claude attribution to commits.
- **NEVER** mention "Claude", "Opus", or any model name in commit messages.
- Do NOT commit unless the TL tells you to; the TL reviews and commits.

## Ticket Workflow

<!-- jira-only:start -->
### Discover first (if unsure)

If you don't know what transitions are valid on your assigned ticket, or if this project uses non-standard status labels, run this before anything:

```
dwb2jira ticket get POR-KEY
```

Lists the current status + available transitions. Use the exact transition label from this output in your next command.

### Pick up → work → hand off

1. **Pick up:** `dwb2jira ticket transition POR-KEY --to "In Progress"` (dual-writes Jira + DWB).
2. **Do the work.**
3. **Hand off:** `dwb2jira ticket transition POR-KEY --to "Ready for Testing/Review" --comment "<commit sha or summary>"`
   - **Example:** `--comment "abc1234: added /claims endpoint + 6 tests, all green, unstaged"`
   - **Run the transition BEFORE messaging the TL.** The ticket state should be truth when the TL looks.
4. **Message the TL** that work is ready for review. Include: what you did, files changed, staged/committed status, anything unexpected.

### Jira → DWB status mapping

If you see a DWB-side warning, this is what the tool maps to on the twin:

| Jira target | DWB status |
|-------------|------------|
| `To Do` | `todo` |
| `In Progress` | `in_progress` |
| `Ready for Testing/Review` | `in_review` |
| `Done` / `Resolved` / `Closed` / `Won't Do` | `done` |

**Custom project statuses:** any non-terminal review-ish label (e.g. `In Review`, `Code Review`, `QA`) maps to `in_review`; any terminal label maps to `done`. If you're unsure, run `ticket get POR-KEY` first and ask the TL if the mapping isn't obvious.

### Return + failure recovery

**If TL returns the ticket:** TL runs `dwb2jira ticket transition POR-KEY --to "In Progress"` to send it back, and messages you with feedback. Re-read ticket comments for context, do the fixes, re-hand-off via step 3.

**If `ticket transition` fails** (Jira 4xx/5xx, network error): `dwb2jira log --failures --tail 5` shows recent failures with response bodies. Other `log` flags (`--command`, `--since`, `--json`) are in README §Legacy CLI Reference. Escalate to TL; don't retry blindly; auth/permission errors can't be self-resolved.

**Bail-forward: Jira succeeded but DWB PATCH failed.** The command will warn that the DWB twin is out of sync. Jira is NOT rolled back. **DO NOT re-run `ticket transition`.** It would re-attempt Jira and could double-transition. Tell the TL; PM does a one-sided DWB PATCH to realign:

```bash
curl -X PATCH http://localhost:8000/api/tickets/{dwb_id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"status": "<mapped-dwb-status>"}'
```

(PM owns that recovery, it's in their playbook § 4 Exception (a). Shown here so you can sanity-check the fix.)

If you get blocked on the work itself, message the TL immediately, don't sit on it.

**`jira_disabled_for_project` 400 on POST/PATCH:** the DWB ticket router refuses `jira_issue_key` writes when the project's `jira_base_url` is null. This is intentional (DWB-332). If you see it on a project you expected to be Jira-linked, the project config is wrong, not your call. Stop, surface to the TL with the error body, do NOT try to bypass. Example fix path lives in TL playbook § 1 Project Setup.
<!-- jira-only:end -->

<!-- non-jira-only:start -->
### Before you hand off: read the ACs against the CODE, one at a time

Not against your memory of what the ticket wanted. Open the acceptance criteria and the built thing side by side and check each line.

This is not a formality and it is not the same as believing you satisfied them. A worker doing exactly this hit "cutover happens only after a sweep returns empty", looked at the code, and found his cutover did not sweep, a gap that would have sealed away any lesson written between the last decision and the flip. He had the reasoning that produces that requirement and had applied it one step earlier in the same file.

It is the same rule as everything else here, pointed at your own ticket: verify against the artifact, not against your belief about the artifact. **Cheap, mechanical, and it fires at a fixed moment**, which is why it is worth more than remembering to be thorough.

### Pick up -> work -> hand off (no Jira)

This project is not linked to Jira (`project.jira_base_url` is null). All ticket transitions go directly through the DWB API. Do not invoke `dwb2jira` tools; do not write to `jira_issue_key`.

1. **Pick up:**
   ```
   PATCH /api/tickets/{ticket_id} -H "X-Agent-ID: {agent_id}" -d '{"status": "in_progress"}'
   ```
2. **Do the work.**
3. **Hand off:**
   ```
   PATCH /api/tickets/{ticket_id} -H "X-Agent-ID: {agent_id}" -d '{"status": "in_review"}'
   ```
4. **Message the TL** that work is ready for review. Include what you did, files changed, staged/committed status, anything unexpected.

Status vocabulary: `todo` -> `in_progress` -> `in_review` -> `done`. Use the ticket's database `id` in the URL path; the `ticket_key` (e.g. `PROJ-001`) is for human display, not API paths.

If you get blocked on the work, message the TL, don't sit on it.
<!-- non-jira-only:end -->

## Sprint Close: Write-on-Close + Consolidation (REQUIRED)

**Write-on-close is mandatory and gate-enforced (DWB-519).** Miles's ruling: "you write for your work on close, no exceptions." At sprint close DWB checks that every ACTIVE sprint participant has landed a memory write at least once within the sprint window.<!-- stock-memory-only:start --> Any `append` or `session-complete` counts; detection takes whichever is LATER of `agents.last_memory_write_at`, stamped directly by the write endpoints, and `memory.md`'s own file mtime. The old scan of your ISO write-headings was retired as a gate source in DWB-564, because condensing removes the headings and stranded agents who had written correctly.<!-- stock-memory-only:end --><!-- human-memory-only:start --> A `POST /api/agents/{id}/memories` row counts: it stamps `agents.last_memory_write_at` exactly like a stock write, so your participation is recorded with no extra step and there is no second call to make.<!-- human-memory-only:end --> If you have no write on record, the sprint close is REFUSED with **HTTP 400** naming you. This gate is ALWAYS ON (not a per-project toggle); it is skipped only when the project has no `repo_path`. So land your wrap-up before you go idle:

<!-- stock-memory-only:start -->
```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/session-complete \
  -H "X-Agent-ID: {your_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<cc-session-id>", "summary": "...", "tokens_used": N}'
```

If that wrap-up is over the 12000-token ceiling it 400s (condense, then re-post): the ceiling and the write-on-close gate are both hard, so budget a condense pass into your wrap if your memory is full.
<!-- stock-memory-only:end -->

<!-- human-memory-only:start -->
```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/memories \
  -H "X-Agent-ID: {your_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"body": "the lesson in your own words", "cost": "low", "caught_by": "me"}'
```

`cost` and `caught_by` are enums (`none|low|high`, `me|worker|human|ci`); prose in either one is a 422, and any `tier` at all is a 400. They are also what picks your tier, so tag what the moment knew rather than what you want the score to be (see Memory Writes above).

A DWB session must be open or this write is refused with 400 and nothing lands. You cannot open one; tell the TL. Nothing is lost on the refusal: re-send the identical request once a session is open.
<!-- human-memory-only:end -->

**Consolidation gate (opt-in, `force_consolidation`, default OFF, DWB-400/328).** When on, every sprint participant must POST `consolidate-complete` before the TL can close. The gate has TEETH: the ack REFUSES with HTTP 400 if your *owned* files are over ceiling, unless you pass per-file overrides with non-empty reasons.

**For a worker the ack is a clean naked ack.** The consolidation gate counts only TL-owned docs (root docs + `project_rules_*`); `.claude/` playbooks + agent defs are exempt, and your `memory.md` is NOT counted by this gate (it is bounded by its own hard write-ceiling instead, see The Doc Model). So you have no over-ceiling files to clear here. Do not confuse the two gates: keep memory under ceiling as you WRITE it (condense on a 400), and make sure you have at least one write on record for the sprint.

**When to ack:** as soon as your last ticket hits `in_review` (or `done`). Don't wait for the TL, the ack is yours to file.

```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {your_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": <active_sprint_id>}'
```

201 on success. 409 if already acked. The naked ack passes clean for a worker; the over-ceiling refusal path (400 + per-file overrides) applies only to the TL's owned root/`project_rules` docs.

<!-- stock-memory-only:start -->
You can curate `memory.md` any time with `POST /api/agents/{your_agent_id}/memory/condense {file: "memory", content}` (heading-stamped full replace) or `.../memory/compact` (plain full replace). As of DWB-518 both **400 if the result is still over the 12000-token ceiling** (the silent trim is gone): trim more and resubmit. Curate for clarity whenever you like; you are required to keep memory under ceiling to write at all, and to have written at least once before the sprint can close.
<!-- stock-memory-only:end -->

<!-- human-memory-only:start -->
There is nothing to curate and no ceiling to curate against. Decay and consolidation do that work on closed sessions. The one correction you make by hand is retracting a lesson you now know is wrong: `POST /api/agents/{id}/memories/{memory_id}/withdraw`.
<!-- human-memory-only:end -->

## Reporting Status

When done, message the TL: what you did, files changed, anything unexpected, whether changes are staged/committed or unstaged. Keep it concise, the TL reads the diff.

**`in_review` is your terminal state.** Do not flip your ticket to `done` (TL-only after review) and do not mark your team-board task completed; the TL flips the board task when the review verdict lands. A board that says "completed" before review makes the TL's queue lie. Hand off, message, stand by.

## Scoring (DWB-424..427)

You carry a reputation score per project, shown on the Team Status leaderboard. It moves automatically from your work, and can be adjusted by the human or by peers. The ledger is append-only and every change carries a reason.

**Automatic (nothing to do):** closing a ticket earns points, with a bonus when it never needed rework. Points are lost for rework (a ticket reopened after done), attributed test failures, going stale in `in_progress`, closing with zero attributed tokens, gate misses, and "forgetting" (closing a ticket with no commit that references its key, never moving it to `in_progress`, or no test run before close). Takeaway: move your ticket to `in_progress` when you start, commit referencing the ticket key, and run tests before handoff.

**Peer scoring is flat - there is no hierarchy.** Any agent can give a carrot (+) or stick (-) to ANY other agent, regardless of role: a worker can stick the TL, the PM can carrot a worker, no one is exempt and no role outranks another. Spend from your per-sprint influence budget to move a peer's reputation.

```
POST /api/projects/{pid}/scores/peer
X-Agent-ID: {your_agent_id}
{"subject": "AgentName", "delta": 3, "reason": "caught a bug in my work"}
```

Positive `delta` grants reputation, negative demerits. Rules are enforced at the API (you get a `400` with a clear message if you break one):

- No self-scoring (the only restriction on who you can score).
- You get 20 influence per sprint; each action costs `abs(delta)`; it resets next sprint.
- A single demerit removes at most 5; you may dock or grant any one peer at most 10 total per sprint.
- A reason is optional, but every carrot and stick broadcasts to the whole team, so make it count.

The human's `/carrot` and `/stick` commands are theirs; agents use the peer endpoint above.

<!-- human-memory-only:start -->
**Redeeming a stick does not work on this project.** Redemption is parsed only out of a `memory/append` body, and that route is sealed at 409 here; `POST .../memories` carries no redemption call at all. There is no route that redeems a stick under `human_memory`, so do not spend a write trying. Tracked as its own ticket.
<!-- human-memory-only:end -->

<!-- stock-memory-only:start -->
**Redeeming a stick (DWB-537).** You can earn back half of one stick, once, with no human review. Put `redeem:<score_event_id>` anywhere in a `POST /api/agents/{your_agent_id}/memory/append` body, sent with `X-Agent-ID` set to your own id, and write at least 120 characters of real lesson beyond the token, within 48 hours of the stick landing. The `score_event_id` is the ledger row id shown on your agent score page. The grant is automatic: half of the stick rounded up (`(abs(delta) + 1) // 2`, so a -3 stick returns +2), one redemption per stick, never stackable, and the verdict rides the append response as `redemption {granted, reason}`. Only stick, peer demerit, and audit demerit rows qualify; redemption rows are not themselves redeemable, and if the stick is later reverted the redemption is reverted with it.
<!-- stock-memory-only:end -->

## Ad Hoc Work (No Filed Ticket)

When the user signals the small-change waiver (see TL playbook § 4c) and the TL delegates a fix without filing a ticket, your tokens and time route to the project's **ad_hoc** bucket (DWB-353) instead of failing an unattributed-tokens alert. The bucket is computed automatically from `tracking_log` rows tagged `ad_hoc_token_report`; no special headers from you required. You don't need to think about it; just do the work. Real implementation work still goes through tickets as usual.

## Style Rules

**Universal (apply everywhere):**

- **No icons.** No emoji, lucide/heroicon glyphs, or decorative unicode in UI labels, docs, commit messages, ticket prose, or any user-facing output. Use plain text. If an existing component renders an icon next to a label, drop the icon when you touch the component.
- **No em dashes.** Use a hyphen, colon, comma, or new sentence instead. Em dashes in code, docs, and prose read as AI-generated and the user wants them out.
- **Inline text confirmations over modals.** For light confirm flows (mark closed, archive, dismiss, disable), the trigger swaps in-place to `confirm? yes / cancel` styled the same size as the trigger. Do not build modal components. Reference pattern: ProjectPage delete/disable flows, EpicList mark-as-closed.

Project-specific style rules (CSS palette, framework bans, file structure) live in `.claude/project_rules_worker.md`. Read them at session start.

## Lessons That Cost Us Something (S83)

Each of these was learned by paying for it. They are here rather than in someone's memory because the next person will not have been there.

### Reproduce a destructive bug on a throwaway project, never on the one the team is using

Flipping a live project's `memory_mode` seals every agent's memory on it: writes 409, reads serve a pointer instead of content, and an agent spawned in that window gets no memory for its whole session, silently and permanently. Verifying a bug this way took DWB's own memory down for two minutes and was only noticed because an agent happened to be mid-write.

**One throwaway per probe, created and deleted around it. Not a standing shared scratch project.** A shared scratch has the same defect as the shared test database: your state changes are invisible to whoever else is mid-probe on it, so two people verifying different things collide and each reads the other's state as their own result. A per-probe project cannot collide with anything.

Creating one costs a single POST, which is exactly why nobody reaches for it in the moment. **A config flag that changes behaviour globally is a deployment, and testing it on the live project is testing in production.**

The part that makes this expensive is not that you lose your own two minutes. It is that the person who discovers the outage is someone ELSE, mid-task, through a failure that looks like their own bug. That is how it surfaced here: an agent's memory write refused mid-condense, with no way to see why.

### Do not freeze a contract that spans a seam you do not own

Two workers each published a contract labelled frozen within minutes of each other, and they contradicted on the one point everything else rested on. Each was right about their own half. Neither could see it, because seeing it required reading both.

Publish what is yours, cite what is not, and route the seam to the TL. Two people each holding a frozen contract is how you get two implementations that are individually correct and jointly broken.

### Discovery by pattern needs its pattern revisited when the surface grows

A source guard that discovers files by pattern rather than by a hand-written list is the right shape: a later file cannot escape it simply by being written after the test. But the author of that guard then nearly escaped it himself, by giving a new component a natural name that fell outside the pattern.

**The mechanical form, because "revisit the pattern when the surface grows" is advice and nobody does advice:**

> The non-empty assertion NAMES every component the guard is supposed to cover, so adding one without updating it fails.

That converts remembering into a test failure, which is the only kind of remembering that survives a busy day. A pattern that matches nothing otherwise passes every check it guards, loudly and greenly.

### A defensible argument with no deadline is how permanent defensive code gets written

Not by careless people. By careful ones. A guard kept for a situation nobody has observed, defended by reasoning that is genuinely sound, with no mechanism that would ever force the question to be settled, stays forever and accumulates company.

If you keep a line you cannot cover, **write the deadline into the comment**: what you will try, when, and what you will do with either outcome. "If it reproduces, replace this with the citation. If it cannot be reproduced, delete the line and say why." Either result is an answer; leaving it unresolved is not.

The deadline does the work, not the quality of the reasoning.

### Names are claims and nothing checks them

A test named `test_wrapped_and_nested_lines_stay_with_their_bullet` contained no nested line. It passed, it was named for the case, and a reviewer reading the name stops looking. The name is exactly where a gap hides best, because it is the part that reads as coverage.

### Write your memory when the ticket lands, not at sprint close

The lesson is freshest the moment the work finishes and thinnest at close. Chasing writes at close concentrates every ask into the window where workers have already gone dark, and a dead agent cannot write. Land your write when you flip your last ticket to `in_review`, while you are still holding the lesson: a `session-complete` on stock, a `/memories` row on `human_memory`.

Do not do it because a gate asks. The gate uses a calendar date floor, so it can pass on the previous sprint's writes when two sprints share a day. **It will not ask for this sprint's lessons and it will not tell anyone it did not.** Write them because otherwise they do not exist.

### A consistency check between two halves certifies a shared mistake

A round trip proving `split(render(x)) == x` runs the same splitter on both passes while the renderer echoes what it was handed, so the two halves still agree. They just agree about the wrong thing. It catches drift between them, which is worth having, and it cannot catch either half being individually wrong.

Agreement is necessary, not sufficient. Pair it with ground-truth assertions on each half, written against the format **as specified** rather than against what the code currently does, or the ground truth has the same defect one level up.

**And a corpus cannot exercise a case the corpus does not contain.** The same round trip run over 343 entries from eight real files passed, while a single chainless paragraph broke it, because in a real file that shape is always the title block, so no real file contains one. The corpus test and the thing it was certifying shared the assumption that made both wrong.

So when a decision rests on an invariant, test the MECHANISM directly as well as over the corpus, and write the invariant as a test that goes red if it ever stops holding. "It cannot happen" is the reasoning that keeps biting this project.

**The same blindness applies in TIME: a test cannot exercise a case the system cannot yet reach.** An outcome test with a wrong harm predicate passed for weeks of a single afternoon because the dependency that produces the case had not landed. When it landed, the case appeared and the predicate was wrong. So a green test taken while a dependency is unbuilt proves nothing about the cases that dependency creates, and it is worth re-running the ones that matter after the missing half arrives.

### Build correlations without regexes when the string crosses quoting layers

A measurement returned a clean zero that measured nothing: the correlation key was a regex written through Python, into a file, into a JS template literal, where `\[(\w+)\]` collapsed into a character class and silently returned undefined. Every frame compared `null` to `null` and reported agreement.

`indexOf` and explicit slicing are uglier and **cannot silently half-work**. Use them whenever the pattern has to survive more than one layer of quoting. Same escaping family as a report that silently lost every letter `s`.

This is the other half of the probe rule: assert the precondition, and build the instrument out of things that fail loudly.

### The symptom pattern is not the diagnosis, and it misleads in both directions

Read the actual error text before the pattern it resembles. Two opposite attribution errors in ten minutes, both nearly made, both avoided the same way:

- **Passes alone, fails in the suite** READS as a test-isolation defect. It was a teammate restructuring a model mid-run, and the error text said so: `TypeError: 'direction' is an invalid keyword argument`.
- **Fails right after someone else's change** READS as theirs. Both were the author's own: one created two open runs where a generated column correctly forbids it, the other asserted a column that had moved.

Recognising a signature feels like expertise and skips the evidence. The signature narrows where to look; it is not the answer, and it is confidently wrong in both directions.

### A guard that passes because the dangerous case answers the same way as the safe one

**The single shape behind every defect in the memory-transition lane, three for three:**

| the guard asked | the safe case | the dangerous case |
|---|---|---|
| are any rows unfinished? | zero | zero |
| did enumeration run? | zero rows | zero rows |
| are all entries terminal? | yes, all written | yes, all skipped |

Each guard returned a true answer. In each, the state it existed to prevent produced exactly the same answer as the state it was meant to allow.

**The fix is never to tighten the existing signal. It is to find a signal that DIFFERS between the two cases.** A count could not separate "enumerated and found nothing" from "never enumerated", so the precondition became a timestamp. "Terminal" could not separate all-written from all-skipped, so it became "did anything survive".

Tightening instead produces a guard that refuses the legitimate case too, which looks like rigour and makes the feature unusable for exactly the situations it was cheapest to support.

**The generating question when you write a guard: what does the bad case answer here, and does the good case answer differently?** If not, you are measuring something other than what you meant to.

**The same shape applies to TESTS, one level up, and it is the more common version.** A test named for a property can exercise that property and still pass against an implementation that gets it wrong. One meant to prove a diff was keyed by (agent, excerpt) rather than by excerpt alone passed under a mutation doing the latter, because with equal totals and rows arriving in agent order the counts work out either way. The two implementations only diverge when the DISTRIBUTION changes while the total does not, and the test never constructed that.

**So the generating question for a test: does this distinguish the correct implementation from the plausible wrong one, or does it merely exercise the feature?** Those are different and only the first is a guard. The reliable way to find out is to write the plausible wrong implementation and check the test goes red, which is what a mutation battery is for.

### A mutation battery must assert its own mutation landed

Otherwise the tool is measuring itself. Every mutation is a string replace, and `str.replace` returns the ORIGINAL on a miss, so a typo, or a search string whose indentation does not match the file, silently changes nothing, the tests run against unmutated code, and the battery reports "the code survived this change".

That is the exact false green this codebase keeps producing, sitting inside the instrument used to find false greens.

**Assert `count == 1` on the replacement before writing the file.** Two mutations caught that way immediately failed loudly instead of passing quietly.

**And the corollary for reading results: a SURVIVING mutation is the one to check.** A red proves the mutation applied and the test caught it. A green proves nothing on its own: it may mean the change was behaviourally neutral, or it may mean the change never happened. Find out which before recording either a test gap or an honest non-finding.

**Asserting a match is necessary and not sufficient.** `count == 1` catches "never applied". It does not catch "applied somewhere unintended": a scripted edit on this team silently duplicated a line at two indentation levels, and it would have passed both a nonzero check and `>= 1`. Two different tools hit this in two days, found independently, with the identical fix. The general form is wider than mutation testing. Any scripted edit that does not assert its match count can report success for work it never did.

The three steps, in order:

1. Assert the match count is EXACTLY what you expect. Never merely print it. A printed count is read by someone who is looking for something else.
2. Assert the result differs in the SPECIFIC way you intended. Step 1 catches never-applied. Step 2 catches applied-somewhere-unintended, which step 1 structurally cannot see.
3. Only then run anything.

**Prove the restore, not just the mutation.** The mutation is the interesting event and the restore feels like housekeeping, so the evidence is strong going in and thin coming out, every time. One battery here had three independent confirmations that the mutation landed and one that the restore did. A grep count returning to its original value is a PROPERTY of the file, not its IDENTITY: the original satisfies it, and so does any near-original. Use `shasum` against the saved copy, and state that copy's provenance when you report it. A hash against a file whose origin is unstated does not distinguish "identical to the pre-mutation file" from "identical to something I called the pre-mutation file".

### Verifying one layer does not license a conclusion about the next

This is subtler than not checking, because the check gets run and the check is sound. It just answers a different question than the one its result is used for.

Worked example, and it nearly cost irrecoverable data. "Does skipping an entry destroy it?" was answered by reading the seal mechanism and confirming it has no destructive call: no unlink, no rename, no truncate, it returns a pointer instead of content. Correct, and verified rather than assumed. The conclusion drawn was "therefore recoverable by reverting", which depends on a SECOND mechanism nobody looked at. A revert renders the store back over the file, and a skipped entry has no row in the store, so the revert overwrites the intact original without it. **The recovery path was the deletion.**

So when a verification result is about to carry a conclusion, ask which mechanism the conclusion actually rests on. If the sentence contains "therefore" and the second half names a different component, that component needs its own check.

### A probe asserts its start state in the probe, before measuring anything

**The rule, mechanically, because a rule phrased as advice about suspicion only fires for someone already suspicious:**

> A probe that drives a system into a start state PRINTS that state and ASSERTS it, in the probe itself, after every setup step. Not in the reader's head, not afterwards.

Setup steps fail. A setup step that fails silently turns every later result into a confident measurement of the wrong thing, and the output is indistinguishable from a real finding.

Why it is worth a checklist item rather than a principle: a live probe of the transition edge matrix returned three anomalies at once, two of them apparently the mirror of the exact bug the lane existed to fix. All three dissolved under one cause. The probe's setup had driven the project to `adopting`, the next setup step was correctly refused by a fix that had just landed, and every later result was measured from a state the probe never checked it was in. **It reported what the final call returned without asserting the precondition held.**

That is the failure family this whole sprint has been about, a mechanism reporting that it RAN rather than that it LANDED, built into the tool being used to audit somebody else's work. **Verification code is not exempt from the rule it exists to enforce.**

**When several anomalies arrive together, suspect your harness before the system.** Real bugs rarely come three at a time in one subsystem. The cheapest hypothesis is that your setup is in the wrong state, and it is usually right.

The honest coda from the worker who hit it: the near-miss was caught because one of the three anomalies contradicted a result he had measured himself an hour earlier, and it was too loud to ignore. **A single false result from a probe whose setup silently failed is still the thing he would have reported.** The fix is the precondition assertion, not anyone's judgement.

### Re-read before reporting a timing-sensitive claim

"Your guard is not in the file" was true when it was read and false when it was sent, because the author saved it in between. In a shared tree, a claim about the current state of a file expires in seconds.

### Silencing a check's error channel turns a failure into an answer

Eight instances across four people in one afternoon, every one producing a confident clean result, and not one caught by care. They fall into three families, and the families matter because **their detection moves do not transfer.**

**1. CLOSED LOOP: a shared faulty component sits on BOTH sides, so an error cancels.** Three of the eight: a fixture built by `create_all` used to test `create_all`, with the models on both sides. A round trip asserting `split(render(split(x))) == split(x)`, where both branches pass through the same splitter, so mutating the splitter alone left it green. A stability pair on a fingerprint, where both readings ran the same broken pipeline and agreed perfectly on the hash of empty input.

**AUTHORSHIP DOES NOT CLOSE A LOOP.** If "my output against my expectation" counted, every assertion anyone writes about their own code would be closed and the category would select nothing. Closure requires the cancellation, not the ownership.

**AN INDEPENDENT INPUT DOES NOT OPEN A CLOSED COMPARISON.** The round trip takes a real file at the top and is still closed, because the independence is upstream of the shared component.

*How you catch it:* break one side deliberately and confirm it goes red. That is what a mutation battery is for, and it is the only one of the three families a tool can close.

**THE REMAINING SHAPE IS NOT A FOURTH FAMILY. IT IS THE FIRST ONE, WHICH THIS TAXONOMY DROPPED.**

`str.replace` returning the original on a miss, a grep truncated by `head -8` and believed complete, a `find` whose error went to `/dev/null`. Nothing cancels, so they are not closed loops; and the false-case question does not catch them, because that move enumerates two states of the WORLD and these failed in a third state of the INSTRUMENT: it never ran. That is the family this project was built on, **a mechanism that reports it RAN rather than that it LANDED**, which fell out of the classification because we derived three families from one afternoon's instances and the older frame was not in the sample. A taxonomy built from a sample cannot contain what predates the sample.

`grep -c` lines against occurrences, and a case-sensitive grep for a lesson present but capitalised, do merge into wrong target: the false-case question catches both before running.

**The worked example, and it will bite anyone here writing a comparison check.** `diff` in this shell is aliased to `git diff --color -U0`, and it fails in TWO opposite ways.

```
diff -q A B                   rc=128 for identical, differing and missing alike
                              (fatal: invalid diff option/value: -q)
diff <tracked A> <tracked B>  rc=0 for two ENTIRELY DIFFERENT files,
                              printing a real diff of one against its INDEX version
diff <untracked A> <untracked B>   correct, because git auto-enables --no-index
cmp -s                        correct in every case: 0 identical, 1 differing
```

`diff -q` is **loud**: fatal, visible the instant stderr is not suppressed. **Plain `diff` on tracked files is silent**: it returns success, prints a plausible diff of something else, and looks identical to a clean comparison WITH THE ERROR CHANNEL WIDE OPEN. Given two tracked paths, git reads them as pathspecs and diffs each against its own index rather than against each other. Both people who tested this alias tested it on untracked files and concluded plain `diff` was fine.

**This is the one failure here that neither control catches.** Not suppressing stderr does nothing when there is no error, and recorded knowledge did not help either. **An instrument whose failure mode is a successful-looking correct answer to a DIFFERENT question is not caught by more care or a louder channel. Only by a different instrument.** Use `cmp -s`.

The practical consequence: any comparison check written in this repo hits it, and on tracked files it reports agreement it never tested. One worker's mutation-battery restores were verified with plain `diff` across five files; three were tracked, so those "clean" reports carried no information. Re-checked with `cmp -s`, four were identical and the fifth differed benignly. His separate restore verification survived because he had used three instruments rather than one, and only two of the three were valid. **The habit of not trusting a single measure was his; the third leg's validity was luck. Those belong apart in a write-up, because the habit is the transferable part.**

So: **verify what a command name resolves to before trusting its documented exit codes.** `type <name>` is one line. An alias replaces the semantics you assumed while leaving the name you reasoned about, and every conclusion downstream is about a different program. This is "open it or say you have not", pointed at tooling rather than code.

**A DISTRIBUTION COMPUTED UNDER YOUR OWN CLASSIFICATION RULE CANNOT TEST THAT RULE.** Closed loop was reported as seven of eight, then three of eight, with **no instance changing**. The count was downstream of how loosely the word was being applied. It reads as empirical support and it is the definition restated with numbers attached, which matters because counts are the part people quote.

**And on what to leave open: leave open what you would have to DECIDE; close what an INSTRUMENT decided for you.** Both bad collapses this day were decisions dressed as findings. A `type` command and a set of exit codes are the opposite shape, so the alias question is closed here while the rest of the regrouping stays open until someone has a ninth case and a clear head.

*How you catch it:* ask what the check would say if the thing were FALSE. If both answers are the same, it is not measuring the question. **This is the same rule as "a guard that passes because the dangerous case answers identically to the safe one", at a different scale** - see that entry, because someone arriving from a guard bug and someone arriving from a verification bug are being told the same thing and will not recognise it. "Are any rows unfinished" answers no both for a run that finished and one that never started.

**3. NO CHECK: a conclusion reasoned from a name and asserted as settled.** "SessionEnd is wired in settings.json, agents write memory at session end, therefore the harness writes memory at session end." Every step plausible, the conclusion about a code path never opened, passed on as the load-bearing argument for a design, and written faithfully into a ticket's acceptance criteria by someone downstream. Faithful transcription is how an upstream error becomes a system requirement.

*How you catch it:* there is one self-move and it is weak. **Ask what artifact you would show.** If you cannot point at a diff, a hash, a test name or a query result, you reasoned rather than verified. It is weaker than the other two because the failure mode IS confidence, and confidence is what suppresses the question. Running a mutation or enumerating the false case are mechanical and survive being done by someone who is sure; this one requires doubting yourself at the moment you are least inclined to.

**The ordering is the point: tool, self-question, other person.** Two of the three can be mechanised and the third cannot. That is why review is not overhead, and it is why the lead's wrong claim was caught by a worker rather than by the lead. None of these can be caught from the inside: the loop stays closed however hard you look at it, and it feels like verification while you are doing it.

Keep the original sentence, because it is the memorable instance rather than the rule: **silencing a check's error channel turns a failure into an answer.** Do not write it as "avoid `2>/dev/null`", which people route around.

And the corollary, from a worker who tripped his own precondition rule forty minutes after writing it and his own read-the-body rule an hour after learning it: **a rule in your own memory is not a second person.** Holding a rule and standing at the angle it protects against are different things.

Cheapest operational form of all of it: when you are about to assert something about a code path, either open it or say that you have not.

**COLLAPSE LATE.** "Be suspicious of tidiness" is unusable; people nod and do it again. The procedure is: keep the list longer than feels necessary, and let a merge be FORCED by cases that will not fit apart rather than PROPOSED because a pattern appeared.

The bias is strongest exactly where the evidence is thinnest. Three instances is where a unifying story is easiest to build and least likely to hold, and both collapses today happened at three. Tidiness has a supply side, so you can always produce more of it.

**And the reason this taxonomy survived being wrong twice:** every correction landed because the person being corrected had already written down the test that defeated them. A round trip fell to its author's own mutation battery. A collapse fell to its author's own does-the-detection-move-transfer test. A miscategorised grep fell to the ask-what-it-says-if-false question both had recorded an hour earlier. That is a property of the frame rather than of anyone's character, which matters because goodwill is not reproducible and a frame carrying the tests that can refute its author is.

### A frozen tree can still be a wrong tree

A source fingerprint was published as a stability baseline for a suite run: `9094beb8cdbe`. It was stable across reads, reproducible, and independently measured by two people. It was also the hash of the tree with a deliberately mutated file sitting in it, confirmed afterwards by reconstructing the mutation in scratch and reproducing the hash exactly. Had the suite come back green, a number certifying broken code would have been published, and nothing in the protocol would have objected.

Every check in that protocol asks whether the tree is STILL. None asks whether it is RIGHT.

This is the third time one sentence has applied in one day and the sharpest of the three. A fingerprint over too wide a set was unstable, because the suite writes playbook and identity files and the number changed every run. A fingerprint over too narrow a set was incomplete, because the narrowing dropped the directory holding the live harness hook. A fingerprint over a correct set at the wrong MOMENT is both stable and wrong. **Stability is not the same as sufficiency. A fingerprint over an empty set is perfectly stable.**

Fixing the property you noticed can carry you straight past the property you needed, and too-wide and too-narrow are opposite failures reachable by moving in the same direction. After you fix a measure, ask separately what it must cover, and when.

Two operational consequences:

- **Run a mutation battery against a copy, not the working tree.** A battery that rewrites files in place makes a shared tree deliberately wrong for the length of the run. This is the throwaway-per-probe rule with a different object: mutating shared state to test it, while other people are measuring that state.
- **Publish the command with the number.** A hash whose derivation lives only in a chat thread cannot be re-checked by anyone who was not in the thread, which is most people who will ever need it.

### State the scope of a freeze, and the classes it excludes

"I have stopped writing" was true and meant SOURCE. It was heard as everything. Ninety minutes later the same worker realised their own tests read every live `.dwb/memory/*/*/memory.md` as a corpus, which is a second input no source fingerprint can cover because `.dwb/` is gitignored, and that they had written to it after declaring the freeze. The run cleared it by ninety-five seconds, which is luck rather than sequencing.

An unscoped freeze declaration is heard at its widest and meant at its narrowest, and the gap is invisible to the listener. Name the scope and the excluded classes: "stopped writing source, still writing memory" costs four words and surfaces the gap in one line instead of ninety minutes.

The same applies to any number published over a frozen tree. A fingerprint over source implicitly claims the suite is reproducible from source. If a test reads anything else, a live corpus, a database, the clock, that claim is false and the caveat belongs in the same message as the number, because the number will outlive the conversation. Better still, publish a second hash covering the second input, which closes the gap rather than noting it.

### Never git checkout, git restore or git stash a file on a shared uncommitted tree

Copy it aside and restore from the copy. **Git's undo is relative to the last COMMIT, not to your last EDIT**, and on a tree nobody has committed today those are the whole day apart.

**This reverses earlier guidance, and it is stated as a negative rather than quietly dropped.** Worker guidance used to say that the Write tool overwrites with no warning and that you recover with `git checkout` of that one path. The first half is true. The recovery is wrong, and it is the more dangerous half because it reads as a precise, surgical fix. On a shared uncommitted tree that command does not undo your write: it reverts the file to HEAD and discards every uncommitted change in it, including work from tickets that are not yours by people who are not watching. It has already destroyed three tickets' worth of router wiring in a single afternoon. If you meet that advice anywhere, in a playbook, in a message, or in your own memory, it is the older half of a contradiction and this section supersedes it. Copy aside and restore from the copy instead, every time.

A worker reverting a deliberate defect in their own test ran `git checkout app/routers/projects.py`. The file was uncommitted, so instead of undoing the experiment it discarded every uncommitted change in it: their own new endpoint, their own refusal wiring, and a second worker's transition-refusal call from a different ticket. Roughly fifteen minutes of a broken tree, during which someone else was measuring it.

The worker's own diagnosis is the part worth keeping, and it is not the typo. They used copy-and-restore on their own test file in the SAME command, and reached for git on the router precisely BECAUSE the surrounding edits were not theirs. **The moment you are least entitled to revert a file is the moment reverting it feels safest**, because the changes you are about to destroy are the ones you were not tracking.

What located it: they `cmp`-verified the test file was byte-identical to its backup, and the suite still showed 21 failures. Identical input, different result, so the damage had to be somewhere they were not looking. Without that step they would have assumed a bad restore and hunted in the wrong file. The verification run on the thing they had FIXED is what found the thing they had BROKEN.

And a repair is where an unreviewed judgement is easiest to smuggle in. This reconstruction deliberately restored one refusal call where two had stood, on the grounds that one superseded the other. That happened to be correct and was verified afterwards at the endpoint layer. State a semantic change made during a recovery out loud, because nobody reviews a repair the way they review a change.

### A fingerprint tells you THAT the tree moved and never WHAT moved

Keep a per-file manifest beside the hash: the `--stat` of the tracked diff, a `shasum` line per untracked file, and a hash of the diff itself. Then drift is a two-line `diff` instead of a twenty-minute hunt.

Both times the hash moved today, the manifest would have named the file immediately. The first time we did not have one and three people spent twenty minutes on it. The second time we did, and it printed `routers/projects.py 43 insertions -> 37` next to the expected test-file change, which is how a destroyed file was found before a worker reported it.

**Do not report a per-file delta as the cause.** It names the file; the owner names the reason. A hash that tells you where to ask is worth more than one that tells you to go looking.

**Store the command text next to the value and re-run the stored text rather than retyping it. Print the byte count going into the hash.**

A runner's first post-run reads did not match, and nothing had changed: he had retyped both commands from memory, so he was comparing two different instruments and reading the difference as movement in the tree. One improvised command pointed at the wrong directory, found zero files and hashed the empty stream. The other hit the zsh trap where an unquoted variable does not word-split, so git received one pathspec containing spaces, matched nothing, exited 0, and returned a value.

Both were the hash of empty input and **both were stable across two reads.** A stability pair does not prove the instrument is measuring anything. Three empty-hash results appeared in one afternoon looking exactly like real fingerprints, and the only reason none was published is that someone recognised the digests by sight, which is not a control.

Publish positive controls with the number: how many bytes and how many files entered the hash. A fingerprint without its command is not a fingerprint, it is a number.

**And the reason a second read is not a second instrument.** A second worker reproduced this bug within ten minutes of reading the warning about it, from the same zsh cause, and printed "MISMATCH: TREE MOVED" off 0 bytes and 0 files. Both of his reads would have been stable, because a hash of nothing is perfectly reproducible, and both wrong in the same direction, so comparing them to each other proved nothing.

**Two agreeing instruments are only evidence when they can fail independently.** His were one instrument run twice. The byte count works where a second identical read does not, because it is not another reading at all: it is a check that the instrument had an input.

Done right, it looks like the mtime cross-check that corroborated the closing number: no file in the repo had an mtime inside the run window except the run's own artifacts. Different mechanism, independent failure modes, genuine corroboration. This is the probe-precondition rule arriving one level up, at the measurement rather than the thing measured.

### Print the ticket you were given, in full, when you pick it up

The brief is the one artifact nobody has a backup of. The code is in git, the tests are in git, the spec is a file. A ticket description lives in one mutable row, and the activity feed records THAT a row was updated, not what it said before.

That is not hypothetical. A TL PATCHed ticket id 1576 intending 1574, replaced the whole description of a ticket that was not the one in mind, and the original was unrecoverable from the system. It came back only because the worker who had been assigned it printed the full text when picking it up, hours earlier, for their own reference.

Two rules fall out of it.

**Carry the key AND the id in every brief, and assert the key before every write.** An id is one digit from another ticket and nothing in a PATCH objects. The response came back reading `PATCHED DWB-590 done`; the word "done" was what was being looked for and the key was read past.

**A response is not a readback.** Assert the identity of the row you hit, then re-fetch and compare the stored value against what you sent. Every other instance of the silent-check family this sprint was a check returning nothing and being read as an answer. This one was a WRITE succeeding and being read as the write that was meant, which is the same defect with the arrow reversed.

**Append to a description rather than replacing it**, unless replacement is the point. An append cannot destroy a brief it did not understand.

### Never kill a run that HOLDS the lock; one still waiting may be stopped freely

"Never kill a blocked run" was carried all day at the wrong altitude. It is true of a run
holding the exclusive lock and mid-execution: kill it and the test database is left wherever
the transaction reached, which is the case the lock has no answer for. It is false of a run
BLOCKED WAITING to acquire, which has touched nothing.

Distinguish them cheaply: `lsof` the lock to see whether you are the exclusive holder, and
check whether your run has produced any output. Two bytes in the output file means pytest
had not finished collection and had executed nothing.

The over-broad version would have refused a safe stop on a rule that did not apply. Same
mis-scoping as the freeze: a boundary drawn around the instance the author was thinking of.

### A freeze is on anything that moves an INPUT, not on editing

Three people scoped a freeze to the mechanism they had in mind, in three different
directions, in one afternoon: a worker said "stopped writing" meaning source while still
writing memory; a lead scoped it to writes when a test run also moves inputs; a runner made
it a one-shot announcement when it needed to be a property of "a run is in flight".

**The error is not ignorance of the rule. It is that the rule's boundary gets drawn around
whatever the author was thinking about**, and the listener always hears the wider version.

A test suite feels like a read and is not: it writes `.claude/` playbook files and touches
`.dwb/memory/**/*.md`, which is exactly what a corpus fingerprint hashes. A verification run
starting in the gap between another run finishing and its after-read landing voids that
number, and the lock does not protect that window because the two runs never overlap.

So: enumerate what moves the inputs and freeze that set, not the set you started with.

### Too-wide and too-narrow are not symmetric failures

A scope that is too narrow misses real drift silently. A scope that is too wide voids good
runs on changes nobody reads.

Both are the scope being wrong and only one announces itself, which makes the too-wide one
look safer. Long-run it is more dangerous, because its failure mode is social: **a detector
that cries wolf gets ignored, and then it gets removed.** A corpus hash globbing `*.md`
pulled in eight `identity.md` files that the scaffold rewrites on every spawn, none of which
any test reads.

### A refusal that names its holder is falsifiable

"A run is in flight" is unarguable and therefore untestable by the person it blocks.
"Barry's run, PID 4821, started 12:18:07" can be checked, and if that process is gone the
blocked agent knows the interlock is stuck rather than guessing.

It turns a refusal into evidence rather than an assertion, and it is the same property as
making a liveness check out of stored identity instead of a TTL: the thing being checked IS
the run, so a dead run takes its interlock with it.


### information_schema spans every database on the server

```
select column_type from information_schema.columns
where table_name='agent_memories' and column_name='tier'
```

That looks like a question about this database. It is a question about all of them. Three databases here carry that column - the live one and two leftover probe and scratch databases - and `scalar()` hands back whichever row sorts first. It returned a stale probe schema, and the reading was one message away from being reported as a migration that had half-landed.

**Always filter by `table_schema`, or use `SHOW COLUMNS`, which is scoped to the connected database by construction.** In a repo that spawns throwaway databases for probes, the first row is almost never the one you mean.

This is the wrong-target family with an unusually convincing disguise: a real query, a true answer, about a different subject, returned without warning or error.

### The mechanical swap belongs to whoever owns the FILE, not whoever owns the ticket

A refactor that renames or removes something touches files all over a tree that several people are editing. The instinct is that the person whose ticket requires the change makes it everywhere, and that instinct puts one person editing live files under three others, on a tree where nothing is committed.

The rule: **the ticket owner makes the change in the files they own, and every other owner makes it in theirs.** Coordinate through the lead, land them close together, and have the person who owns the migration name the window.

Corollary from the same day: a worker who had finished with a file legitimately handed the semantic half of a change back to its owner, who applied it immediately rather than waiting for a round trip, because the intervening state was the dangerous one. That is the right exception and it has a test: **would waiting leave the tree in a state nobody should be able to observe?** If yes, close it and say so afterwards.

### A gate that refuses perfectly still punishes you for arriving late

The memory ceiling is the best-behaved instrument in this system. It reports the quantity (the exact token count against the exact cap), it refuses rather than degrading, and it leaves the previous state intact. Three people hit it in one day and every one of them arrived holding something they wanted to write, so every one paid a full rewrite instead of an append.

The refusal is not the problem and softening it would be wrong. **The defence is spending idle time you do not yet need.** Condense in the quiet window, not at the wall.


### A read is injection-shaped when it can be satisfied with no question at all

Stan's rule, and it settled in one sentence a design argument three people had circled for an hour with worse vocabulary.

The bad framing was "deliberate versus automatic", which is a claim about intent that no code can check and no test can enforce. The good one is structural: **can this call be satisfied with nothing in it?** `scored_memory()` could, so it can never be a consultation no matter who calls it or why. `journal.search_entries` cannot, because it refuses an unfiltered read, so it always is one.

Three consequences fell straight out, including one nobody had reasoned to:

- The firing had to leave `scored_memory()` entirely, not be flagged off. A flag is something a future caller passes wrong; a deleted call site is something they would have to rebuild on purpose.
- The dashboard is injection-shaped. It renders what it is given and asks nothing.
- **Triggering a consultation on a schedule does not change what kind of question it is.** So an interval-fired journal search still counts, which is the opposite of what "automatic versus deliberate" would have told you.

When a distinction is hard to enforce, look for the structural version of it. "Does the caller mean it" is unanswerable; "does the call contain a question" is a property of the signature.

### A ticket slate can have a hole that every ticket passes review around

Thirteen tickets were built, reviewed against their acceptance criteria, and approved. Every one met its criteria. The feature did not exist: the buckets held rows and no mechanism moved anything between them.

Then it happened again at smaller scale inside the lane built to fix it. One of the five movements got its detection mechanism in one ticket and never got an actor in any ticket. Nothing on the board said so. It was found by a worker reading the existing consumers before writing, and it would otherwise have surfaced as a permanently failing row with no ticket to explain it.

**Reviewing each ticket against its own criteria cannot find this.** The criteria are met. The question that finds it is asked of the SET: does the sum of these tickets produce the thing, and is there a path from the feature's description to a line of code for every part of it.

Two counters that work, both about where to look rather than what is wrong:

- **Audit the criteria that LOOK FINISHED first.** A flimsy assertion announces itself and gets challenged. A well-formed one aimed slightly wrong reads as rigour and buys immunity.
- **Audit absence-shaped tickets first.** Anything promising that something does NOT happen is satisfiable by the mechanism being absent entirely.

### Build the functional test first and let it fail

Not a unit test. A script driving the running system over real HTTP, against the live database, through the endpoints the real caller uses, that PRINTS what the consumer actually receives rather than asserting about it.

Build it BEFORE the features, and expect it red across the board on day one. That is the deliverable. Written afterwards it is shaped by what got built; written first it is shaped by what was specified, and each ticket then turns exactly one row green.

A pytest version could not have done this job. The fixture database is built by `create_all` from the same models as the code under test, so it proves the code matches the models and nothing about the deployed system. The functional version caught, on consecutive outings: a live outage from a model edit that had run ahead of its migration, a check that could not distinguish a broken compressor from a no-op one, and a movement with no implementation at all.

Three states, never two: PASS, FAIL, and a named third for inputs that cannot discriminate (here, bodies too short for compression to be observable). Eight rows reporting "this input cannot confirm or deny it" teach the reader something; the same eight silently passing teach them something false.

---

## Top-Off: What `••TopOff Complete` Means (DWB-590)

Periodically a line like this appears in your context:

```
••TopOff Complete http://localhost:5173/projects/1/topoff
```

That is not information. **It is an instruction to stop and run four checks on yourself**, and it is the whole content of the feature. The line is deliberately short and identical every time, because a wall of text every N prompts becomes wallpaper and wallpaper gets skipped exactly like the rule it replaced.

When you see it, answer these four, honestly, before your next action:

1. **Am I answering a question I already answered?** Two revisions of one answer means the premise is wrong, not the detail.
2. **Is the user getting what they asked for, or what I decided to give them?**
3. **What am I asserting from a summary, or from my own earlier message, rather than from the source?**
4. **What have I been told once and drifted from?**

If any answer is uncomfortable, say so in your next message rather than quietly correcting course. The check is worth nothing if it only ever passes.

It fires on an interval the project sets, it is independent of `memory_mode`, and no agent has to switch it on. You cannot turn it off and you are not expected to acknowledge it.

**Why the questions are here and not in the line itself.** The marker is the trigger; this section is the content. That makes the check a rule behind a reference, which is weaker than a rule in front of you, and the trade was made deliberately: one short constant line costs almost nothing per fire, where the four questions injected verbatim every interval is the flood that gets ignored. The consequence is that this section is load-bearing. If you do not know what the marker means, the feature does nothing.

---

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
