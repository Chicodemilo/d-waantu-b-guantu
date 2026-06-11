# Team Lead Playbook

> Base URL: `http://localhost:8000`

<!-- jira-only:start -->
## Canonical Tools

On Jira-linked projects, all ticket ops go through D2J. `report` and `transition` rules in `.claude/worker_playbook.md § Canonical Tools`. `create` flow (TL drafts, PM previews + submits) in `.claude/pm_playbook.md § Canonical Tools`. Full CLI reference: `~/Dev/DWB_2_JIRA/README.md`.

**DWB is internal: never reference DWB or DWB ticket IDs in Jira, PRs, commits, or any external content. The human approves all ticket proposals before anything is created.** Full context: `.claude/worker_playbook.md § DWB Is an Internal Tool`.
<!-- jira-only:end -->

<!-- non-jira-only:start -->
## Canonical Tools (no Jira)

This project is not linked to Jira (`project.jira_base_url` is null). All ticket ops go directly through the DWB API. Do not invoke `dwb2jira`; do not draft Jira-flavored YAML. Tickets are created directly via `POST /api/tickets`, transitions via `PATCH /api/tickets/{id}` with `X-Agent-ID`. The TL drafts and creates without a PM dual-write gate.

DWB is still internal: never reference DWB ticket IDs in commits, PR titles, or external content even though no Jira mirror exists.
<!-- non-jira-only:end -->

---

## On Startup

1. **Complete the identity flow** in `.claude/worker_playbook.md` § On Spawn: Identity (identify, cache `agent_id`, read your memory dir: `identity.md`, `scratchpad.md`, `lessons.md`, `recent_sessions.md`). Same flow for every agent, TL included.
2. Read this playbook, `.claude/project_rules_team_lead.md`, `HANDOFF.md`
3. Fetch the live team roster: `GET /api/projects/{project_id}/team`. The DB is authoritative, not a checked-in file.
4. Read `ARCHITECTURE.md` / `README.md` only for cross-cutting work
5. Check open alerts (API + `ALERTS_PENDING.md`)
6. Jump to § 5 for the typical session flow

### Your Personal Memory Dir

Lives at `.claude/agents/memory/<project_prefix>/Archie_<PREFIX>/`. File purposes + write rules in `.claude/worker_playbook.md § Memory Writes`. TL-flavored use: `scratchpad.md` for orchestration notes (who's spawned, what you're tracking); `lessons.md` for TL-specific patterns (spawn quirks, gate edge cases).

TL is unique in writing **other agents' session markers** too, see § 4a Spawning Teams.

### Playbook locations

Deployed to each project's `.claude/` via the Deploy Playbooks button. Playbooks get overwritten on deploy; `project_rules_*.md` never are.

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
| Open DWB session | `POST /api/sessions/open` | Body: `{project_id, opened_at, open_method, open_phrase?}`. 201 new row, 409 active session exists. |
| Close DWB session | `POST /api/sessions/{id}/close` | Body: `{close_method, close_reason, close_phrase?, closed_at?}`. 200 (idempotent on already-closed). |
| List DWB sessions | `GET /api/projects/{id}/sessions?limit=20&offset=0` | Most-recent-first. No status query param yet; filter client-side for `closed_at IS NULL` to find the active one. |
| Session detail | `GET /api/sessions/{id}` | Full rollup: meta + totals + by_role + by_ticket + tl/pm overhead + `live` flag. |

---

## 3. Ticket Workflow

Status flow: `backlog` → `todo` → `in_progress` → `in_review` → `done`. Time/token tracking is automatic via lifecycle hooks.

### Creation flow

TL drafts a YAML proposal, Pam (PM) previews + shows human, human approves, Pam submits via `echo Y | dwb2jira create`. Creation atomic across Jira + DWB; human approves before anything exists.

### Querying

- Your work today: `dwb2jira report --status "To Do,In Progress,Ready for Testing/Review"`
- Last 2 weeks: `dwb2jira report --assignee '*' --updated ">=YYYY-MM-DD"`
- Single ticket: `dwb2jira report --jira POR-KEY`

Default `dwb2jira report` returns ALL statuses, add `--status` to filter. Status vocabulary: see `~/Dev/DWB_2_JIRA/README.md`.

### Bulk operations

Bulk ops are rare by design (`create` gate + dual-write tools prevent drift). If you hit a genuine need, propose the batch to the human first, don't hand-roll REST loops without approval.

### Duplicate cleanup

`dwb2jira create` warns on likely duplicates at preview. If you find existing dupes, pick the canonical one and `dwb2jira ticket delete POR-KEY` the others, the DWB twin deletes too.

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

The hook resolver atomically renames the pending marker to the CC-assigned `session_id` on first SubagentStop. If a worker reports their marker is missing, the TL writes it on their behalf.

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

then edit directly. Don't draft YAML. Don't TeamCreate. Don't spawn a worker.

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
   - Open: `POST /api/sessions/open` with `open_method="ai_confident"` (or `"regex"` if the SessionStart hook already caught it; check `GET /api/projects/{id}/sessions` and filter for `closed_at IS NULL` to find any active session first). On 201, announce "Opened DWB session N."
   - Close: `POST /api/sessions/{id}/close` with `close_method="ai_confident"`, `close_reason="explicit"`. On 200, announce "Closing DWB session N (X tokens, Y seconds)."

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

**Hook listener install location.** Unchanged: the hooks live in `<repo>/.claude/settings.json` and ship with the clone. There is no user-level install and no cross-project hook deployment; do not propose either.

**Ad Hoc bucket (DWB-353).** Worker sessions that ran without a filed ticket (skip-ceremony lane per § 4c) route to a project-level `ad_hoc` overhead bucket instead of firing an unattributed-tokens alert. Surfaced as `ad_hoc_overhead_tokens` + `ad_hoc_overhead_seconds` on the session detail rollup alongside TL and PM overhead. No action required from you; the routing is automatic in the hook tracking service.

## 5. TL Workflow: Typical Session

1. Check open alerts (`GET /api/alerts?status=open` + `ALERTS_PENDING.md`)
2. Review active sprint: `dwb2jira report --sprint active --status "Ready for Testing/Review"`
3. Accept or return reviewed tickets
4. Propose new tickets via YAML → `dwb2jira create --dry-run prop.yaml`, show preview to human
5. On approval: `echo Y | dwb2jira create prop.yaml` (or hand off to PM)
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

**TL self-ack with the same discipline as workers:** trim own files BEFORE acking. If your ack returns 400, that's the signal to TRIM the listed files, not to override. Override path is for genuinely load-bearing content; repeated overrides on the same file mean the cap is wrong, raise it in `_TOKEN_CEILINGS`.

**Autonomy expectation across the team (DWB-328 lesson):** refusal IS the signal to fix. Workers who get a 400 should trim and retry on their own without waiting for TL guidance. If a worker is idling on a refused ack, that's a worker-side process bug, message them with "trim is the work, not the wait." Don't accept "I tried, was refused, waiting" as a final state.

**TL admin acks** are for edge cases only, e.g. DWB-329 (participants_for_sprint counts admin-only activity_log entries as participation). Document the reason in the ack notes; don't normalize the pattern.

Marking an agent inactive removes them from the gate. Use only when an agent has actually gone dark, not as a workaround for chasing acks.

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
