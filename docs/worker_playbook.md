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
4. **Read your memory dir.** The `memory_dir` returned by identify points to `.dwb/memory/<project_prefix>/<your_name>/` (DWB-401: moved out of the protected `.claude/` tree into the writable `.dwb/`). As of DWB-341, the dir + both files are guaranteed to exist on spawn: `spawn-prepare` auto-scaffolds idempotently (identity.md refreshed, memory.md preserved byte-for-byte when present, created empty when missing). Read both, and if either is still missing after scaffold, **HALT** and tell the TL:
   - **`identity.md`**: system-generated profile (who you are, file purpose, ISO 8601 rule, read order). **Do not edit by hand**: scaffold regenerates this file each time.
   - **`memory.md`**: your single free-form memory (DWB-401, replacing the old scratchpad + lessons + recent_sessions). In-flight working notes AND durable lessons worth keeping across sessions, append-only via the API. Future-you and other agents read this. The DWB dashboard/DB is the session index now, so there is no separate recent_sessions file.

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
      └─ memory.md           single free-form memory (scratchpad + lessons merged)
            owner writes via the memory API · GATE-EXEMPT (passive trim, never blocks close)
```

**Budgeted vs exempt:** the close/sprint gates count only the root/project docs the TL owns. DWB-shipped docs (playbooks, agent defs) are *exempt* — keeping those lean is the DWB team's job. As of DWB-401 your **memory is gate-exempt too**: `memory.md` is bounded by a passive server-side trim (oldest entries drop past a size ceiling), never a close-blocker, so you are never chased to trim it. Memory now lives under `.dwb/` (writable) rather than `.claude/`, but still write it through the API so the server applies the ISO heading and the trim consistently.

---

## Protected Files: Never Write These

The Claude Code permission dialog for editing files under `.claude/` crashes subagents in the ink renderer. Four sibling agents died across S66 from this exact pattern, including some that followed prior playbook guidance to "append yourself" inside the memory dir. The current ground truth is stricter:

- **NEVER** use `Edit`, `Write`, or `NotebookEdit` on ANY path under `.claude/`. This includes `.claude/settings.json`, `.claude/settings.local.json`, every playbook, and every project_rules file. The dialog fires the same way; subagents die the same way. (Your memory dir moved out to `.dwb/` in DWB-401, so it is no longer in this danger zone — but still write it through the API for the ISO heading + passive trim.)
- Anywhere outside `.claude/` is safe to write directly (project code, `docs/`, `README.md`, `HANDOFF.md`, etc.).
- Memory updates go through the API only: see Memory Writes below.
- If your work requires a `.claude/settings.json` (or other harness-config) change, flag it to the TL; they'll handle the edit directly from the main CC window where a user is attached for the permission dialog.

## Shared Code: Grep Callers Before You Delete

Before deleting or refactoring shared code another agent owns — especially the session close path (`services/dwb_session.py`) — grep ALL callers/importers FIRST, and give the owner a heads-up. A module deleted while something still imports it crashes the API on reload (this is exactly how the backend went down during a live keyword-dedup). On a hot shared file, ask the owner to diff-review your change and run the suite before you commit, and don't refactor it live under concurrent edits — coordinate, then make one clean change.

## Memory Writes: When and How

DWB-401 collapsed memory to a single free-form `memory.md` (identity.md is still system-generated). Write it through the API: the FastAPI process applies the ISO heading and the passive size-trim consistently. Two endpoints, one for in-flight notes and one for wrap-up.

**Canonical in-flight path: `POST /api/agents/{your_agent_id}/memory/append`** (DWB-358). Use this whenever you want to capture a note or a lesson mid-ticket. Body:

```json
{
  "file": "memory",
  "content": "Trying X, hit Y, working around with Z.",
  "session_id": "optional-cc-session-id"
}
```

- `file` enum: `memory` (the only writable file; DWB-401 collapsed scratchpad/lessons/recent_sessions into it). `identity.md` is system-managed; the Pydantic `Literal` rejects an `"identity"` value at 422, and the service layer also refuses it as a defense-in-depth check.
- `content`: required, non-empty. Empty or whitespace-only bodies return 400.
- Server prepends an ISO 8601 UTC heading (`## 2026-06-10T13:48:15+00:00`, or `## 2026-06-10T13:48:15+00:00 - session <id>` when you pass `session_id`).
- Append-only. Existing content is never overwritten. After the append, the server **passively trims** the oldest `##` blocks if `memory.md` exceeds its size ceiling (keeping the newest). This is mechanical and silent; it never errors and never blocks anything.
- Returns 201 with `{agent_id, file, path, timestamp, bytes_written}` on success.
- Errors: 422 (file value outside the Literal enum); 400 (empty content; agent has no project_id; project has no repo_path); 404 (agent not found, project row missing); 500 (memory dir or file unwritable).

**Wrap-up path: `POST /api/agents/{your_agent_id}/session-complete`.** The natural close at session end. Send a summary payload and the endpoint writes one timestamped block (summary + tokens + any lessons) to `memory.md`. Same ISO 8601 heading format. Use this to land the wrap; use the in-flight endpoint for everything before.

**What goes in `memory.md`:** anything worth carrying forward — in-flight thinking ("trying X, hit Y, working around with Z"), durable lessons ("next time you migrate enums in MySQL, autogenerate misses them; hand-write"), and session wrap-ups. One free-form file; you decide what's worth keeping. The session index lives in the DWB dashboard/DB, not a memory file.

**Never edit `identity.md`.** It is system-generated and regenerated on scaffold. The append endpoint refuses writes to it.

**Memory lives under `.dwb/` now (DWB-401), which is writable** — but still go through the API so the ISO heading and passive trim apply consistently. `.claude/` paths (settings, playbooks, project_rules) remain the no-touch danger zone.

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

## Sprint Close: Consolidation (REQUIRED)

DWB enforces a `force_consolidation` gate at sprint close. Every sprint participant must call `consolidate-complete` before the TL can close the sprint. The gate has TEETH (DWB-328): the ack endpoint REFUSES with HTTP 400 if your owned files are over ceiling, unless you provide per-file overrides with non-empty reasons.

**As of DWB-401, nothing of yours gates a close.** Your only authored file is `memory.md`, and it is gate-EXEMPT — bounded by a passive server-side trim, never counted toward the consolidation gate. `.claude/` docs (playbooks, agent defs) are exempt too; `project_rules` and root docs are TL-owned. So for a worker the consolidation ack is a clean naked ack: you have no over-ceiling files to clear. (The gate itself is also opt-in per project via `force_consolidation`, default OFF — DWB-400.)

**When to ack:** as soon as your last ticket hits `in_review` (or `done`). Don't wait for the TL, the ack is yours to file.

**How:**

```bash
curl -X POST http://localhost:8000/api/agents/{your_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {your_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": <active_sprint_id>}'
```

201 on success. 409 if already acked. For a worker the naked ack passes clean — your `owned_over_ceiling_files` is empty (memory is gate-exempt as of DWB-401). The over-ceiling refusal path (400 + per-file overrides) still exists in the endpoint, but it now only ever applies to the TL's owned root/`project_rules` docs, never to a worker's memory.

You can optionally curate `memory.md` any time with `POST /api/agents/{your_agent_id}/memory/compact {file: "memory", content}` (full-file replace). DWB-401: this **no longer 422s** on over-ceiling — if your replacement is large, the server passively trims the oldest blocks after writing rather than refusing. Curate for clarity if you want, but you are never *required* to trim memory to ack or close.

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

## Ad Hoc Work (No Filed Ticket)

When the user signals the small-change waiver (see TL playbook § 4c) and the TL delegates a fix without filing a ticket, your tokens and time route to the project's **ad_hoc** bucket (DWB-353) instead of failing an unattributed-tokens alert. The bucket is computed automatically from `tracking_log` rows tagged `ad_hoc_token_report`; no special headers from you required. You don't need to think about it; just do the work. Real implementation work still goes through tickets as usual.

## Style Rules

**Universal (apply everywhere):**

- **No icons.** No emoji, lucide/heroicon glyphs, or decorative unicode in UI labels, docs, commit messages, ticket prose, or any user-facing output. Use plain text. If an existing component renders an icon next to a label, drop the icon when you touch the component.
- **No em dashes.** Use a hyphen, colon, comma, or new sentence instead. Em dashes in code, docs, and prose read as AI-generated and the user wants them out.
- **Inline text confirmations over modals.** For light confirm flows (mark closed, archive, dismiss, disable), the trigger swaps in-place to `confirm? yes / cancel` styled the same size as the trigger. Do not build modal components. Reference pattern: ProjectPage delete/disable flows, EpicList mark-as-closed.

Project-specific style rules (CSS palette, framework bans, file structure) live in `.claude/project_rules_worker.md`. Read them at session start.

## STOP Means Stop

When the user says **STOP**, **PAUSE**, or **HALT**: immediately cease ALL activity. No tool calls, no messages, no cleanup. This overrides everything.
