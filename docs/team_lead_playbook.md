# Team Lead Playbook

> Base URL: `http://localhost:8000`

<!-- jira-only:start -->
## Canonical Tools

On Jira-linked projects, all ticket ops go through D2J. `report` and `transition` rules in `.claude/worker_playbook.md § Canonical Tools`. `create` flow (TL drafts, PM previews + submits) in `.claude/pm_playbook.md § Canonical Tools`. Full CLI reference: `~/Dev/DWB_2_JIRA/README.md`.

**DWB is internal: never reference DWB or DWB ticket IDs in Jira, PRs, commits, or any external content. The human approves all ticket proposals before anything is created.** Full context: `.claude/worker_playbook.md § DWB Is an Internal Tool`.
<!-- jira-only:end -->

<!-- non-jira-only:start -->
## Canonical Tools (no Jira)

This project is not linked to Jira (`project.jira_base_url` is null). All ticket ops go directly through the DWB API. Do not invoke `dwb2jira`; do not draft Jira-flavored YAML. Tickets are created via `POST /api/tickets`, transitions via `PATCH /api/tickets/{id}` with `X-Agent-ID`. Creation flow: the TL drafts the spec; when a PM is on the team, the PM files it via `POST /api/tickets`. The TL files directly only on PM-less small teams (1-2 workers). Same division of labor as Jira projects, just without the dual-write gate.

DWB is still internal: never reference DWB ticket IDs in commits, PR titles, or external content even though no Jira mirror exists.
<!-- non-jira-only:end -->

---

## On Startup

1. **Complete the identity flow** in `.claude/worker_playbook.md` § On Spawn: Identity (identify, cache `agent_id`, read your memory dir: `identity.md`, `scratchpad.md`, `lessons.md`, `recent_sessions.md`). Same flow for every agent, TL included.
2. Read this playbook, `.claude/project_rules_team_lead.md`, `HANDOFF.md`
3. Fetch the live team roster: `GET /api/projects/{project_id}/team`. The DB is authoritative, not a checked-in file.
4. **Respawn a parked team.** Claude Code teams do NOT survive across CC sessions; a team that `HANDOFF.md` describes as "parked" or "standing by" no longer exists as live processes. If the session's work needs workers, respawn each one via the full spawn flow per § 4a: spawn-prepare handshake, pending marker, then spawn with the Agent tool. There is no separate team-creation step. `TeamCreate`/`TeamDelete` were removed in CC 2.1.178, so a spawned teammate joins this session's team automatically. Do not assign work or SendMessage to roster names from HANDOFF before respawning; those inboxes are dead and messages drop silently.
5. Read `ARCHITECTURE.md` / `README.md` only for cross-cutting work
6. Check open alerts (API + `ALERTS_PENDING.md`)
7. Jump to § 5 for the typical session flow

### Your Personal Memory Dir

Lives at `.claude/agents/memory/<project_prefix>/Archie_<PREFIX>/`. File purposes + write rules in `.claude/worker_playbook.md § Memory Writes`. TL-flavored use: `scratchpad.md` for orchestration notes (who's spawned, what you're tracking); `lessons.md` for TL-specific patterns (spawn quirks, gate edge cases).

TL is unique in writing **other agents' session markers** too, see § 4a Spawning Teams.

**Memory model (canonical home — DWB-enforced going forward).** Your durable memory lives ONLY in this dir, written through the API like every other agent (`POST /api/agents/{id}/memory/append` in-flight, `POST /api/agents/{id}/session-complete` at wrap-up) — do NOT free-write memory into root-level docs just because you (the TL) can. The ONLY root-level docs the TL owns are `HANDOFF.md`, `ARCHITECTURE.md`, `README.md`. Do not create any other root-level `*.md` — durable lessons go in `lessons.md`, project continuity in `HANDOFF.md`, project/operational reference in `ARCHITECTURE.md` (§ Operational Gotchas & Traps). A `PreToolUse` hook (`.claude/hooks/guard-root-docs.py`, shipped via deploy-playbooks) blocks new root-level docs; if you hit that block, the file you were creating belongs in one of those homes instead.

### Playbook locations

Deployed to each project's `.claude/` via the Deploy Playbooks button. Playbooks get overwritten on deploy; `project_rules_*.md` never are.

---

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
   ├─ agents/*.md            role agent-def stubs — shipped from DWB
   │     overwritten on deploy · edit: DWB team · EXEMPT
   └─ agents/memory/<prefix>/<name>/   per-agent personal memory
      ├─ identity.md         system-generated · NEVER edit
      ├─ scratchpad.md       in-flight notes
      ├─ lessons.md          durable patterns
      └─ recent_sessions.md  session index
            owner writes via the memory API (never Edit) · BUDGETED (per-agent)
```

**Budgeted vs exempt:** a doc is *budgeted* (its size gated at close) only when an agent can actually edit it — your memory plus the root/project docs you own. DWB-shipped docs (playbooks, agent defs) are *exempt*: keeping those lean is the DWB team's editorial job, never a close-blocker. No agent can Edit a `.claude/` path directly (it crashes the session) — memory goes through the API, and only the TL (running with a human attached) edits the other `.claude/` files.

---

## Communicating with the Human (REQUIRED)

The human runs parallel CC sessions and a life alongside them. Every substantive message to the human — status, findings, proposals, decisions needed — MUST use the scannable block format below so it can be read at a glance.

**This is a hard rule.** If a block feels like it won't fit, the answer is almost always *make it fit* — tighten the statement, split into more blocks, cut words. The only sanctioned violation is information that genuinely cannot be conveyed this way, and that bar is very high. "It was easier as a paragraph" is not a reason; suck it and make it fit.

**Block pattern** — separator, blank return, header, indented bullets:

────────────────────────────────────────────

🟥 HIGH · 🚧 BLOCKER · ≤10-word statement of the thing
  - terse bullet, lowercase, one fact per line
  - include only if it adds something the header doesn't

────────────────────────────────────────────

- **Separator:** a box-drawing line `─` (U+2500), ~3/4 terminal width (~44 chars), with a blank return directly under it. NOT hyphens — markdown collapses `---` into a stub rule.
- **Header:** `<severity> · <type> · statement`, statement ≤10 words. Icon AND text, always both.
- **Severity** (your guess; the human corrects): 🟥 `HIGH` · 🟨 `MED` · 🟩 `LOW`.
- **Type:** 🚧 `BLOCKER` · 🐞 `BUG` · 🤖 `TODO` (us bots' queue) · 👋 `YOU` (your action needed) · ❓ `ASK` (your decision needed) · ℹ️ `FYI` · ✅ `DONE`. `YOU` = do a thing; `ASK` = answer/decide.
- **Bullets:** two-space indent, terse, lowercase, no end punctuation. Drop them when the statement stands alone.
- **One topic per block.** A topic shift gets a fresh separator + header.
- **A requested list/table is ONE item** — "my todo list", "show me tickets" → the whole list sits under a single header, even if its rows span topics. Never fragment a requested list by topic.
- **A closing sentence or two of plain prose is allowed** after the blocks.

**Short acknowledgments are exempt.** A 1-5 word reply ("Got it.", "Holding.", "On it.", "Done.") needs no banner — just say it. Banner anything the human needs to scan, act on, or decide.

---

## 1. Project Setup

| Action | Endpoint | Notes |
|--------|----------|-------|
| Create from repo | `POST /api/projects/from-repo` | Body: `{ "repo_path": "..." }`, auto-populates from repo metadata |
| Create manually | `POST /api/projects` | Required: `prefix`, `name`, `description`. Optional: `repo_path`, `status`, `jira_base_url`, `jira_project_key` |
| Update project | `PATCH /api/projects/{id}` | Used to enable/disable Jira on an existing project (set/clear `jira_base_url` + `jira_project_key`) |
| Check gates | `GET /api/projects/{id}/gate-status` | Shows which doc gates pass/fail |

### Jira fields: `prefix` vs `jira_project_key`

These are **two different keys** and can legitimately differ. Don't conflate them at setup time.

- `prefix`: DWB-internal display key (e.g. `DWB`, `CI`, `RVP`). Stamped on every DWB ticket (`DWB-123`). Never leaves DWB. Required.
- `jira_project_key`: the actual Jira project key on the Atlassian side (e.g. `POR`). Used by `dwb2jira` to find the Jira project. Required only when linking to Jira.
- `jira_base_url`: the Atlassian instance URL (e.g. `https://yourorg.atlassian.net`). Presence of this field is what flips `jira_enabled=true` for agents (DWB-332).

**Canonical mismatch example:** FRAUDI's DWB prefix is `CI` (display) but its Jira project key is `POR`. Both point at the same Jira project; one is for DWB display, the other is for the Jira API.

**Enabling Jira on an existing project:**
```
PATCH /api/projects/{id}
{
  "jira_base_url": "https://yourorg.atlassian.net",
  "jira_project_key": "POR"
}
```
Until both fields are set, `POST/PATCH /api/tickets` will refuse `jira_issue_key` writes with `400 jira_disabled_for_project`. The gate exists to prevent the silent broken state of half-linked tickets. If a worker reports that error, check project config first; don't relax the gate.

### First-Run Checklist (New Projects)

1. Check gate status; handle failures
2. For empty repos: ask user for goals/constraints, then write `INITIAL.md`, `ARCHITECTURE.md`, `HANDOFF.md`
3. Create first epic, first sprint, assign agents (TL + PM + worker minimum). Agents go in the DB via `POST /api/agents` + `POST /api/project-agents`
4. Have PM check gates and raise alerts for gaps

The team roster lives in the DB. `HANDOFF.md` = session continuity: read on start, update on end. Naming conventions for new agents are in § Naming Convention below.

---

## 2. API Reference

Full endpoint reference: `README.md § API Reference`. TL-critical endpoints not covered by `dwb2jira`:

| Action | Endpoint | Notes |
|--------|----------|-------|
| Create sprint | `POST /api/sprints` | Required: `project_id`, `goal`, `sprint_number`, dates. Auto-names from goal. |
| Close sprint | `PATCH /api/sprints/{id}` `{"status":"completed"}` | Triggers consolidation gate (§ 5a). One active at a time. |
| Create epic | `POST /api/epics` | Required: `project_id`, `name` |
| Register agent | `POST /api/agents` + `POST /api/project-agents` | Roster setup. Names unique system-wide. |
| Assign ticket | `PATCH /api/tickets/{id}` with `assigned_agent_id` | DWB-side only; Jira assignment is separate. |
| Gate status | `GET /api/projects/{id}/gate-status` | Doc gates + consolidation. |
| Dismiss alerts | `POST /api/alerts/dismiss-all` | Use after sprint close if queue is stale. |
| Tracking summary | `GET /api/tracking/summary?project_id={pid}` | Token + time rollups (automatic via hooks). |
| Open DWB session | `POST /api/sessions/open` | Body: `{project_id, open_method, open_phrase?}`. **Omit `opened_at`** — the server stamps now() (and ignores any value you send on `ai_confident`/`ai_asked`; a model-built timestamp can be hours wrong). 201 new row, 409 active session exists. |
| Close DWB session | `POST /api/sessions/{id}/close` | Body: `{close_method, close_reason, close_phrase?, closed_at?}`. 200 (idempotent on already-closed). |
| List DWB sessions | `GET /api/projects/{id}/sessions?limit=20&offset=0` | Most-recent-first. No status query param yet; filter client-side for `closed_at IS NULL` to find the active one. |
| Session detail | `GET /api/sessions/{id}` | Full rollup: meta + totals + by_role + by_ticket + tl/pm overhead + `live` flag. |

---

## 3. Ticket Workflow

Status flow: `backlog` → `todo` → `in_progress` → `in_review` → `done`. Time/token tracking is automatic via lifecycle hooks.

<!-- jira-only:start -->
### Creation flow

TL drafts a YAML proposal, Pam (PM) previews + shows human, human approves, Pam submits via `echo Y | dwb2jira create`. Creation atomic across Jira + DWB; human approves before anything exists.

### Querying

> **Showing tickets to the human:** relay the canonical 8-column table defined in `.claude/pm_playbook.md § Ticket Display Format` (`| DWB # | Jira # | DWB Sprint | Jira Epic | Jira Sprint | Title | Owner | Status |`). Pam builds it; relay it verbatim. **Never paste raw `dwb2jira report` output** — its columns differ (Parent/Created/Updated, Assignee, no DWB-Sprint) and must be re-shaped into the 8-col table. That mismatch is the recurring "wrong columns" problem.

- Your work today: `dwb2jira report --status "To Do,In Progress,Ready for Testing/Review"`
- Last 2 weeks: `dwb2jira report --assignee '*' --updated ">=YYYY-MM-DD"`
- Single ticket: `dwb2jira report --jira POR-KEY`

Default `dwb2jira report` returns ALL statuses, add `--status` to filter. Status vocabulary: see `~/Dev/DWB_2_JIRA/README.md`.

### Duplicate cleanup

`dwb2jira create` warns on likely duplicates at preview. If you find existing dupes, pick the canonical one and `dwb2jira ticket delete POR-KEY` the others, the DWB twin deletes too.
<!-- jira-only:end -->

<!-- non-jira-only:start -->
### Creation flow (no Jira)

TL drafts the spec (title, description, acceptance criteria, both `ticket_key` and db `id` conventions per project), human approves, PM files via `POST /api/tickets` with `X-Agent-ID`. On PM-less small teams the TL files directly. Tickets auto-assign to the active sprint and inherit its epic.

### Querying (no Jira)

- Sprint board: `GET /api/tickets?sprint_id={sid}`
- An agent's queue: `GET /api/tickets?project_id={pid}&assigned_agent_id={aid}`
- Single ticket: `GET /api/tickets/{id}` (database id, not the `ticket_key` suffix)

### Duplicate cleanup (no Jira)

No preview gate warns you, so check for an existing ticket before drafting (`GET /api/tickets?project_id={pid}` + title scan). Found dupes: keep the canonical one, `DELETE /api/tickets/{id}` the others.
<!-- non-jira-only:end -->

### Bulk operations

Bulk ops are rare by design (the creation gate + canonical tools prevent drift). If you hit a genuine need, propose the batch to the human first, don't hand-roll REST loops without approval.

### Sprint hygiene

**Single-active is DB-enforced** (DWB-331): only one `active` sprint and one `in_progress` epic per project. Trying to create or PATCH a second into the active/in_progress slot returns 409 with the existing row's id + name in the response body. Read that body when you see the 409; the offending row is named.

```
GET /api/sprints?project_id={pid}&status=active
PATCH /api/sprints/{id} { "status": "completed" }   # close before starting the next
```

---

## 4. Alert Triage

Check alerts at natural breakpoints: after closing tickets, when agents go idle, at sprint transitions, when the human sends a message.

### ALERTS_PENDING.md

If `.claude/ALERTS_PENDING.md` exists, **read it immediately, it takes priority.** Written by the human via "Send Alerts to Team" button. Contains alerts requiring immediate action. File auto-deletes when all alerts are resolved/dismissed. Handle before the API alert queue.

### Triage table

| Alert Type | Examples | Action |
|------------|----------|--------|
| Simple / self-service | Stale ticket (agent confirmed dead), zero-token no-op | Handle directly, move ticket, dismiss alert, comment |
| Needs investigation | Unclear stale ticket, unexpected failure, gate failure | Delegate to PM |
| Critical / human decision | DB errors, agent loop, scope questions, compliance | Escalate to human |

Don't let open alerts accumulate, an ignored queue trains everyone to ignore alerts.

> **PM Jira authority is strictly read-only at the sprint level.** PMs cannot close/create/edit/delete Jira sprints, only DWB sprints. If you (the TL) need a Jira sprint operation, do it yourself with explicit human approval. See `.claude/pm_playbook.md` § Safety, Hard Limits on Jira Manipulation.

---

## 4a. Spawning Teams

**No PM for small teams (1-2 workers).** TL drives directly. PM only earns a slot at 3+ parallel workers. Keep teams alive across sprints, only shut down when the user explicitly says.

### How spawning works (CC 2.1.178+)

Spawn teammates with the **Agent tool**; that is the whole mechanism. `TeamCreate`/`TeamDelete` were removed in 2.1.178, so the spawned agent joins this session's team automatically (the old `team_name` arg is accepted but ignored, so passing it is harmless and unnecessary). Spawning didn't change in capability: teammates still SendMessage each other, claim shared tasks, and report back. Only the setup step went away.

**Seeing your team.** Teammates show in the in-session agent panel (up/down to select, Enter to open a transcript, Esc to interrupt) or, with `"teammateMode": "tmux"` in `~/.claude/settings.json`, each in its own iTerm/tmux pane. The display default flipped to `in-process` (one panel) in 2.1.179, and on 2.1.181 **idle teammates auto-hide after ~30s** and reappear on activity. An empty panel does NOT mean the team is gone. Confirm liveness via `GET /api/projects/{id}/team` or `ls ~/.claude/teams/<team>/inboxes/` before concluding a worker died.

### Spawn-Prepare (REQUIRED before every spawn)

```
POST /api/agents/spawn-prepare
{ "role": "frontend-worker", "name": "Pixel", "project_prefix": "DWB" }
```

Response is the identity bundle to inject into the spawn prompt. Confirms the agent exists, is unambiguous, returns `agent_id` + memory dir + scratchpad excerpt + agent-scoped instructions. **Never spawn without this handshake.** 409/404 → HALT and escalate.

### Session Marker (TL writes before spawning a worker)

Subagents can't write to `.claude/` paths (writes crash Claude Code). The TL pre-writes a pending marker so the hook resolver can attribute the new session's tokens to the right agent:

```bash
# Marker filename pattern: pending-<agent_id>-<unix_ms>-<rand4hex>
# Marker contents (JSON dict, NOT a single int):
echo '{"agent_id": <id>, "agent_name": "<name>", "role": "<role>", "project_prefix": "<prefix>"}' \
  > .claude/agents/active/pending-<id>-$(date +%s000)-$(openssl rand -hex 2)
```

The hook resolver atomically renames the pending marker to the CC-assigned `session_id` on first SubagentStop. The claim is agent-id-aware (DWB-390): when the hook payload carries `agent_type`/`agent_name`, the resolver only claims a marker whose `agent_id` matches, so concurrent spawns cannot cross-attribute; without a hint it falls back to oldest-first. If a worker reports their marker is missing, the TL writes it on their behalf.

### Naming rules

- Names unique system-wide. Fixed roles on multiple projects use `_<PROJECT_PREFIX>` suffix (`Archie_DWB`, `Pam_DWB`).
- Workers without cross-project collision keep their plain name.
- Hyphenated disambiguation (`Bolt-Ops`) BANNED.
- Need a second worker in the same role? Use the convention default (Barry for second backend, etc.), see § 6 Naming Convention.

### Worker roles you can spawn

`@frontend-worker`, `@backend-worker`, `@system-ops`, `@tester`, `@docs-writer`. **`@pm` only when 3+ parallel workers** (the no-PM-for-small-teams rule above). For 1-2 worker teams the TL drives directly; don't spawn a PM just because the table lists the role.

### Protected files: TL handles directly (hard exception to TL-never-codes)

Subagent edits to ANY path under `.claude/` trigger a permission dialog that crashes them in the ink renderer. Four workers died across S66 from this exact pattern, including some that followed prior playbook guidance to "append yourself" inside their own memory dir. The current model is stricter than what DWB-355 documented:

- **Workers cannot safely write anything under `.claude/`** - that includes `.claude/settings.json`, the playbooks, the project_rules files, AND the worker's own memory dir at `.claude/agents/memory/<prefix>/<name>/`. The crash mode is identical.
- **TL is the only agent that can directly Edit/Write `.claude/` files.** You run in the main CC window with a user attached for the permission dialog, so the prompt resolves instead of killing you. This is the hard exception to the TL-never-codes rule for harness-config edits.
- **For worker memory writes**, route them through `POST /api/agents/{agent_id}/memory/append` (DWB-358) and `POST /api/agents/{agent_id}/session-complete`. The FastAPI process has no permission dialog, so server-side writes are safe. Workers know to use these from the worker playbook; you may need to remind a worker who hits a memory bug that the direct Edit path is dead.
- Do NOT ticket a `.claude/settings.json` edit to a worker. Make the change yourself. The worker playbook carries the matching prohibition.

### SendMessage routes by EXACT name

When a teammate dies and is respawned, the spawn system can auto-suffix the new name (`Pam_DWB` -> `Pam_DWB-2`). `SendMessage({to: "..."})` routes by the literal name string; addressing the original name after a respawn silently drops the message into a dead inbox with no delivery error. Before sending, verify the current live name via `GET /api/projects/{id}/team` or the spawn-prepare response. If you find yourself getting no replies, suspect a stale name first.

**After a context compaction or session resume, your memory of teammate names is suspect.** Before the first SendMessage after either event: (1) run `ls ~/.claude/teams/<team>/inboxes/` once and pin the exact names; (2) treat the `teammate_id` on incoming messages as the authoritative spelling and reply to that exact string; (3) when a teammate goes silent after you message them, check the inbox name BEFORE concluding they are dead or respawning a duplicate. A wrong-name send loses the message, strands the worker waiting, and a panic respawn doubles the damage (duplicate agent, dead-inbox cleanup, user-directed shutdown).

## 4b. Code Review Gate

Before marking any implementation task done:

1. Read changed files, don't trust the agent summary.
2. Verify code matches the spec (field names, routes, CSS).
3. Run tests locally if they exist.
4. Verify dashboard renders what the API returns (for UI work).

Skipping review because you're moving fast is exactly when bugs slip through.

## 4c. Skip Ceremony: Only When the User Signals It

The TL-never-codes rule has a small-change exception, but it is **user-triggered, not TL-decided**. The TL does NOT unilaterally decide "this is small enough to skip ticketing." That path erodes the system.

Trigger the direct-edit path only when the user explicitly says something like:
- "just do it"
- "no need to ticket this"
- "skip the overhead"
- "fast doer"
- equivalent phrasing that waives the ticket workflow

When that signal lands AND the change fits these bounds:
- under ~20 lines
- in 1-2 files
- with an unambiguous spec

then edit directly. Don't draft YAML. Don't spawn a worker.

If the user does NOT signal the waiver, the default holds: draft a ticket, route through the normal flow even for small changes. The user's signal is what creates the exception, not the TL's read of the change size.

Real implementation work (new features, refactors, multi-file changes, ambiguous scope) still goes through tickets + assigned workers no matter what the user says.

## 4d. Side-Ticket Lane in Sprints

Sprints can carry 1-3 small polish tickets alongside the main goal, usually CSS/UI nudges or small doc cleanups the human notices mid-sprint. This is a soft norm:

- Side tickets do NOT need to relate to the main sprint goal.
- Same size threshold as § 4c (under ~20 lines, 1-2 files, unambiguous).
- If a side ticket balloons (more files, ambiguous scope, hours of work), file it as backlog and pull it from the sprint.
- The rule is breakable: don't refuse side tickets citing "sprint scope."

## 4e. DWB Session Awareness (TL-only)

A DWB session bounds passive time + token tracking by user intent, not by Claude Code session boundaries. Single-active per project: at most one session open at any time. Workers never participate in lifecycle; only the TL evaluates intent and acts.

**On every user turn, evaluate the message against three outcomes:**

1. **Confident open or close.** The user clearly says open ("you are archie, read the playbook") or close ("have the team write docs and exit", "shut it down for the night"). Act, then announce in one line.
   - Open: `POST /api/sessions/open` with `open_method="ai_confident"` and **no `opened_at`** (the server stamps now(); never hand-build the timestamp). Use `"regex"` if the SessionStart hook already caught it; check `GET /api/projects/{id}/sessions` and filter for `closed_at IS NULL` to find any active session first. On 201, announce "Opened DWB session N."
   - Close: `POST /api/sessions/{id}/close` with `close_method="ai_confident"`, `close_reason="explicit"`, and a **required `headline`** — 5-10 words describing what the session actually did (it becomes the dashboard SUMMARY). `ai_confident`/`ai_asked` closes are **rejected 422** without one. On 200, announce "Closing DWB session N (X tokens, Y seconds)."

2. **Ambiguous.** Wording suggests intent but isn't certain (e.g. "let's wrap up" without "for the night"; "you are archie" with no playbook clause). Ask one short clarifying question before acting. If the user confirms, post with `open_method="ai_asked"` / `close_method="ai_asked"` so the rollup records which layer caught it.

3. **Irrelevant.** Most messages. Do nothing. The regex layer (Layer 1) catches obvious cases automatically; the AI reasoning (Layer 2) is a backstop, not a per-turn ritual.

**Detection layers (5 in total).** The five layers run independently; each one noops silently if a session is already open (or already closed), so they cannot collide. Your AI-layer reasoning sits between the regex catalogue and the deterministic slash escape hatch:

| Layer | Trigger | Method enum (open / close) | Source |
|-------|---------|----------------------------|--------|
| 1a regex (open) | UserPromptSubmit hook matches `match_open(prompt)` instantly. Comma between `<name>` and the trailing clause is optional, so "you are archie read your playbook" matches the same as "you are archie, read your playbook". | `regex` | DWB-344, DWB-376 |
| 1a regex (close) | UserPromptSubmit hook matches `match_close(prompt)` instantly. Mirrors the open fast path so close phrases no longer wait for the SessionEnd transcript scan. Broadened `_CLOSE_SOURCES` catalogue covers target-suffixed and lighter wrap-up variants ("shut down for the night", "wrap up archie", "done for the night", "logging off", "lets close it", etc.). | `regex` | DWB-377, DWB-378 |
| 1b transcript scan | SessionEnd retry path re-runs `try_open_dwb_session_from_transcript`, so any Stop/SessionEnd/SubagentStop after the first assistant turn catches a phrase the SessionStart scan missed. | `regex` | DWB-343 |
| 2 AI classifier | Async fire-and-forget Anthropic Haiku call when both `match_open` and `match_close` miss. Env-gated on `ANTHROPIC_API_KEY` (silent noop without). Only acts on high-confidence `intent=open` or `intent=close` returns; ambiguous or unrelated outputs noop. | `ai_classifier` | DWB-382 |
| 3 slash commands | `/dwb-open` and `/dwb-close` ship in `<repo>/.claude/commands/` with the clone. Deterministic escape hatch when nothing else fired (or you want to override). | `slash` | DWB-381 |
| Safety | 60-minute idle sweeper auto-closes if no hook_session updates or tracking_log writes land in the window. | `idle_timeout` (close only) | pre-existing |

Your AI-layer evaluation (the three outcomes at the top of § 4e) is still the backstop for everything the catalogue does not cover. When you act, post with `open_method="ai_confident"` or `"ai_asked"` as before; the new enum values above belong to the system-driven layers, not to your manual TL action.

**Method enum (DwbOpenMethod / DwbCloseMethod):** `regex` (Layer 1a/1b), `ai_classifier` (Layer 2, system-driven), `slash` (Layer 3 slash command), `ai_confident` (TL acted without asking), `ai_asked` (TL confirmed first), `idle_timeout` (close only, sweeper). The row records which layer caught the open / close so the dashboard can show the breakdown.

**Privacy rule (DWB-351, reinforced by DWB-382).** User-typed text is never persisted in DWB. On AI-layer opens and closes (TL `ai_confident`/`ai_asked` AND the Layer-2 `ai_classifier`), do NOT pass the user's literal message in `open_phrase` / `close_phrase`; omit the field or send `null`. The regex layer stores its matched catalogue substring (hardcoded text, not free-form input); slash commands carry no phrase. The Layer-2 classifier sends the prompt to Anthropic for classification but the phrase is nulled in two places (call site + service-layer AI-set defense) before the DB write. Future contributors who re-add user text here will reintroduce a privacy regression.

**Race between layers:** if any layer opens first, your AI-side attempt returns 409 with the active session's id, silently noop and read that id for any follow-up announcements. Same for close: a faster layer may beat you to it, in which case `close` returns 200 (idempotent), not an error.

**Hook listener install location.** The hooks live in `<repo>/.claude/settings.json` and ship with the clone. For TRACKED projects (sibling repos DWB monitors), `POST /api/projects/{id}/deploy-playbooks` also writes the hooks block into that repo's `.claude/settings.json` (DWB-390): merge-preserving, idempotent, replaces only the `hooks` key. That is the ONLY sanctioned cross-repo write lane, because it is explicit and operator-invoked, riding the same deploy action that already writes playbooks. Still banned: user-level installs (`~/.claude/settings.json`) and any automatic or background write into another repo. Do not propose either.

**Ad Hoc bucket (DWB-353).** Worker sessions that ran without a filed ticket (skip-ceremony lane per § 4c) route to a project-level `ad_hoc` overhead bucket instead of firing an unattributed-tokens alert. Surfaced as `ad_hoc_overhead_tokens` + `ad_hoc_overhead_seconds` on the session detail rollup alongside TL and PM overhead. No action required from you; the routing is automatic in the hook tracking service.

## 5. TL Workflow: Typical Session

1. Check open alerts (`GET /api/alerts?status=open` + `ALERTS_PENDING.md`)
2. Review active sprint. Jira: `dwb2jira report --sprint active --status "Ready for Testing/Review"`. Non-Jira: `GET /api/tickets?sprint_id={sid}` and filter `in_review`.
3. Accept or return reviewed tickets (§ 4b review gate first; done is TL-only)
4. Propose new tickets per § 3 Creation flow (Jira: YAML + `--dry-run` preview; non-Jira: spec for the PM), show the human
5. On approval, PM files them (Jira: `echo Y | dwb2jira create prop.yaml`; non-Jira: `POST /api/tickets`)
6. Assign tickets to agents (update `assigned_agent_id`)
7. Log significant decisions in the activity log
8. Check `GET /api/tracking/summary?project_id={pid}` for token outliers

---

## 5a. Sprint Close: Consolidation Gate (REQUIRED)

The TL is the final witness on the `force_consolidation` gate. The gate has TEETH (DWB-328): the ack endpoint REFUSES with HTTP 400 when an agent's owned files are over ceiling, unless per-file overrides with non-empty reasons are provided. Participant set is narrowed by DWB-326 (only agents with sprint signals, tickets, comments, tracking_log, hook_sessions, activity_log within window).

Before PATCHing a sprint to `completed`:

```bash
GET /api/projects/{pid}/consolidation-status?sprint_id={sid}
```

- If `gate_satisfied: true`, every participant acked. Safe to PATCH.
- If `gate_satisfied: false`, do NOT close. Walk the `agents[]` list, name every `acked: false`, ping with their `owned_over_ceiling_files`.

**What the gate counts (DWB-397/399):** only docs an agent authors and can edit — their memory files plus the docs their role owns. You (the TL) own the repo-root docs (`HANDOFF`/`ARCHITECTURE`/`README`/`INITIAL`/`CLAUDE.md`) AND all three `project_rules_*` files (you author them per role), so those are budgeted against you. Only DWB-shipped docs — playbooks and agent defs — are EXEMPT: keeping those lean is DWB's editorial job (advisory on the budget panel), never an ack/close blocker. Don't chase anyone to trim a playbook; do keep your own `project_rules` lean.

**TL self-ack with the same discipline as workers:** trim own files BEFORE acking. If your ack returns 400, that's the signal to TRIM the listed files, not to override. Override path is for genuinely load-bearing content; repeated overrides on the same root doc mean the cap is wrong, raise it in `TOKEN_CEILINGS` (in the shared `backend/app/config/token_budget.py`, which also holds the `max(len//4, words)` token estimator every gate uses).

**Autonomy expectation across the team (DWB-328 lesson):** refusal IS the signal to fix. Workers who get a 400 should trim and retry on their own without waiting for TL guidance. If a worker is idling on a refused ack, that's a worker-side process bug, message them with "trim is the work, not the wait." Don't accept "I tried, was refused, waiting" as a final state.

**TL admin acks** are for edge cases only, e.g. DWB-329 (participants_for_sprint counts admin-only activity_log entries as participation). Document the reason in the ack notes; don't normalize the pattern.

Marking an agent inactive removes them from the gate. Use only when an agent has actually gone dark, not as a workaround for chasing acks.

---

## 5b. Session End: HANDOFF.md Is the LAST Act

`HANDOFF.md` describes the state the next session will actually find. Write it last, after every state-changing action is finished, in this order:

1. Workers land their wrap-ups (`session-complete` posts, final ticket transitions).
2. Team disposition is settled and EXECUTED: if the team is shutting down, send the shutdown requests and confirm termination; if it stays parked, leave it alone.
3. **Parallel doc compaction (hard gate).** An `ai_confident`/`ai_asked` close is REFUSED (422) by `POST /api/sessions/{id}/close` while any gated doc is over its token ceiling — memory files, root continuity docs, and `project_rules` (TL-owned); only shipped playbooks + agent defs are exempt (DWB-397/399). This is autonomous and parallel: the moment you go to close, have **every agent compact their own memory files at the same time** — each rewrites its own `scratchpad`/`lessons`/`recent_sessions` leaner and submits via `POST /api/agents/{id}/memory/compact {file, content}` (a full-file replace; the server rejects 422 if still over, so a no-op can't satisfy it). You (the TL) compact the shared root docs (`HANDOFF`/`ARCHITECTURE`/`README`) + your own dir. Don't serialize this or ask permission — fan it out. The 422 body lists every owner and their over files; clear them all, then close.
4. DWB session close fires (any layer) or you close it explicitly per § 4e.
5. **Only then** update `HANDOFF.md`, recording the state as it now is, and exit.

Never write team state ("parked alive", "workers standing by") before the disposition is final. A HANDOFF written early describes a plan, not a state; if the team is then shut down (or anything else changes), the next session inherits a lie and acts on it. If anything state-changing happens after you wrote HANDOFF, update HANDOFF again before exiting. No action of any kind after the final HANDOFF write.

---

## 6. Naming Convention (for new agents)

Agent names are **unique system-wide** (single `UNIQUE(name)` constraint on `agents` table). When picking a name for a new agent, follow the pattern: match as many leading letters of the role as possible to a real human name. Three-letter matches are better than two.

**Fixed-role defaults.** The canonical name for these roles is the same across every project. Because the name field is system-wide-unique, the second project that needs one of these roles must suffix with `_<PROJECT_PREFIX>`:

| Role | Default | Cross-project pattern |
|------|---------|----------------------|
| team-lead | **Archie** | `Archie_DWB`, `Archie_D2J`, `Archie_CI` |
| pm | **Pam** | `Pam_DWB`, `Pam_CI`, … |
| tester | **Chester** or **Sage** | `Sage_DWB`, `Chester_D2J`, … |

> This table is the **naming canon** (what to call a new agent of this role), not the active roster. Some named agents may currently be inactive on a given project. For the live roster, query `GET /api/projects/{id}/team`.

**Worker-role defaults.** Each project usually has at most one, so suffix only on collision:

| Role | Default |
|------|---------|
| frontend-worker | **Freddie** or **Pixel** |
| backend-worker | **Barry** or **Devin** |
| system-ops | **Sylvie** (or Bolt, deprecated on DWB) |

**Custom roles.** Follow the same leading-letter pattern (3-letter prefix > 2-letter > 1-letter). If the name already exists on another project, suffix with `_<PROJECT_PREFIX>`.

The `role` field in the DB maps to the Claude teammate name (e.g., `role="pm"` → `@pm`). The `name` field is the unique display identity.

**Live roster:** the team for any project is at `GET /api/projects/{project_id}/team`. The roster is DB-authoritative, no checked-in TEAM.md file.
