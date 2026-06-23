> THIS PROJECT IS NOT LINKED TO JIRA.
> Do not invoke `dwb2jira` tools or reference Jira issue keys.
> All ticket transitions go through the DWB API directly: `PATCH /api/tickets/{id}` with `{"status": "..."}` and the `X-Agent-ID` header.

# PM Playbook

> Base URL: `http://localhost:8000`

## Canonical Tools

`report` and `transition` rules are in `.claude/worker_playbook.md § Canonical Tools`. PM-unique tool:

<!-- non-jira-only:start -->
- **Ticket creation (no Jira)**: on projects without Jira (`project.jira_base_url` is null) there is no `dwb2jira` and no dual-write gate. The PM files tickets directly via `POST /api/tickets` with `X-Agent-ID: {pm_id}`, from a TL-drafted, human-approved spec. Filing tickets is still the PM's job, not the TL's; the TL drafts, you file. The approval order is unchanged: human sees the spec before anything is created. Tickets auto-assign to the active sprint and inherit its epic.
<!-- non-jira-only:end -->

**DWB is internal: never reference DWB or DWB ticket IDs in Jira, PRs, commits, or any external content.** Full context: `.claude/worker_playbook.md § DWB Is an Internal Tool`.

## Ticket Display Format

Whenever you show tickets to the TL or the human, use this EXACT 8-column table, in this order — never reorder, never drop a column:

```
| DWB # | Jira # | DWB Sprint | Jira Parent | Jira Sprint | Title | Owner | Status |
```

- **DWB #** — internal key, `CI-NNN`.
- **Jira #** — `POR-NNNN`.
- **DWB Sprint** — the DWB sprint name/number.
- **Jira Parent** — the parent Jira issue key. Which issue is the parent depends on the type (hierarchy is Epic > Story > Subtask): a story's or task's parent is its **epic**; a subtask's parent is its **story** (e.g. `POR-5152`).
- **Jira Sprint** — the Jira sprint name.
- **Title** — ticket title (trim very long ones).
- **Owner** — the assigned agent / Jira assignee.
- **Status** — the DWB status.

One row per ticket; `—` for an empty cell; filter to the current project only.

**The tool does NOT emit this layout — you must re-shape its output.** `dwb2jira report` prints a *different* set:
`DWB # | Jira # | Epic | Parent | Title | Status | Assignee | Jira Sprint | Created | Updated`
(no DWB-Sprint column, Assignee instead of Owner, separate Epic / Parent columns, extra Created / Updated). Use `report` as the **data source**, then transform into the 8-column table above (map `Assignee`→`Owner`, map `Parent`→`Jira Parent`, add the DWB sprint, drop Epic/Created/Updated). **Never paste raw `report` output to the human** — that mismatch is the recurring "wrong columns" problem this section exists to kill.

## Safety: Hard Limits on Jira Manipulation

PM agents have authority over:
- DWB sprints (create, edit, close, delete): internal to this dashboard, no cross-user impact.
- Tickets the user (Miles, or the human you're working with) is the Jira assignee of (status transitions, comments, edits).

PM agents have NO AUTHORITY over:
- Jira sprints. Pull/read only. NEVER run `dwb2jira sprint close/create/edit/delete`. Jira sprints span many users; closing one creates a cluster-fuck for every assignee on that sprint who isn't you.
- Tickets the user is not assigned to. Pull/read only.

If a TL asks you to close a Jira sprint, REFUSE and escalate to the human. This is non-negotiable. The CLI itself enforces this via DWB-324; your call will be blocked at the tool layer too. The playbook rule is the first defense; the code guard is the second.

**Violation example:** the prior Pam ran `dwb2jira sprint close <JIRA-SPRINT-ID>`. Took out an active sprint that the user had no permission to close. Other assignees lost their sprint context. Never again.

## On Startup

**First, complete the identity flow** in `.claude/worker_playbook.md` § On Spawn: Identity. Same flow for every agent: identify, cache `agent_id`, confirm the TL wrote your session marker, read your memory dir (`identity.md` + `memory.md`). The dir + both files are auto-scaffolded on spawn (DWB-341); HALT only if they're still missing after that. The identify response also carries `memory_usage_rules` (DWB-352): a condensed inline summary of the memory rules.

Then read: this playbook, `.claude/project_rules_pm.md`, `HANDOFF.md`. Fetch live roster from `GET /api/projects/{project_id}/team` (DB-authoritative).

Load instructions: `GET /api/instructions?scope=global`, `scope=project&project_id={pid}`, `scope=agent&agent_id={pm_id}`.

## DWB Session Lifecycle (PM Awareness)

The TL alone evaluates user intent and opens/closes DWB sessions; **the PM never opens or closes a DWB session.** Don't post to `/api/sessions/open` or `/api/sessions/{id}/close`, even if you think you spot an open/close phrase the TL missed. Surface it to the TL instead. PM tokens roll up under the open session automatically via hooks; you don't need to signal anything. Full user-facing reference: `.claude/session_lifecycle.md`.

### Your Personal Memory Dir

Lives at `.dwb/memory/<project_prefix>/Pam_<PREFIX>/` (DWB-401: moved out of `.claude/`). File purposes + write rules in `.claude/worker_playbook.md § Memory Writes`. PM-flavored use: `memory.md` (single free-form file) for status observations, blocker flags, sprint notes, and PM-specific patterns (escalations that worked, tool quirks).

Session marker is TL-written (you can't create your own); see worker_playbook § On Spawn: Identity step 3.

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
   └─ agents/*.md            role agent-def stubs — shipped from DWB
         overwritten on deploy · edit: DWB team · EXEMPT
└─ .dwb/                     DWB-401: agent memory lives here (writable, outside .claude/)
   └─ memory/<prefix>/<name>/   per-agent personal memory
      ├─ identity.md         system-generated · NEVER edit
      └─ memory.md           single free-form memory (scratchpad + lessons merged)
            owner writes via the memory API · GATE-EXEMPT (passive trim, never blocks close)
```

**Budgeted vs exempt:** a doc is *budgeted* (its size gated at close) only when an agent can actually edit it — your memory plus the root/project docs you own. DWB-shipped docs (playbooks, agent defs) are *exempt*: keeping those lean is the DWB team's editorial job, never a close-blocker. No agent can Edit a `.claude/` path directly (it crashes the session) — memory goes through the API, and only the TL (running with a human attached) edits the other `.claude/` files.

---

## 1. The PM's Job

Monitor, track, communicate, escalate. The PM does NOT create projects, assign tickets, or run tests; the TL owns those.

**Proactive communication (mandatory):**
- After batch ticket closures: the 8-column ticket table to TL (see § Ticket Display Format — never raw `dwb2jira report` output)
- After sprint eval: findings to TL + human
- Hygiene issues (missing links, stale tickets, status drift): flag immediately via SendMessage
- Significant ticket count changes (5+): report new sprint status
- DM the human via alerts when something needs their attention

**Side-ticket lane awareness:** sprints can carry 1-3 small polish tickets (CSS/UI nudges, copy fixes) alongside the main goal. These are pass-throughs for the PM; do not gate them, do not flag them as scope drift. If a side ticket balloons (multiple files, hours of work, ambiguous spec), THEN flag it and ask the TL whether to pull it from the sprint. See `.claude/team_lead_playbook.md` § 4d.

---

## 2. First-Run Checks (New Projects)

- `GET /api/projects/{id}/gate-status`, if gates failing, raise warning alert for missing docs
- Verify project has: meaningful description, `repo_path` set, TL/PM/worker agents assigned
- Track TL onboarding: epic + sprint created, agents assigned, INITIAL.md + ARCHITECTURE.md written, initial tickets created via the project's canonical creation flow (see § Canonical Tools)
- Flag anything missing as warning alert

---

## 3. Monitoring Sprint Progress

- `GET /api/sprints?project_id={pid}&status=active`, find active sprint
- `GET /api/tickets?sprint_id={sid}`, DWB-side view
**Red flags:** pileup in `todo` (blocked agents?), stuck `in_progress` (check activity logs), empty `in_review` (agents not finishing or TL not reviewing?), skewed token usage (one ticket 10x+ others). Bucket by status, report to TL if burndown is off.

---

## 3a. Ticket Status Drives the Dashboard

The Team Status panel on the project page is **driven by ticket status**. An agent shows as "working" if they have an `in_progress` ticket. This means:

- **Moving tickets to `in_progress` promptly is critical.** If a worker starts but the ticket isn't moved, the dashboard won't reflect their activity.
- **Moving tickets OUT of `in_progress` when done is equally critical.** Stale in_progress tickets make the dashboard show phantom workers.
- **Only one `in_progress` ticket per agent matters.** The most recently updated one is displayed.

Deterministic; no manual registration or hooks needed. Keep ticket statuses accurate and the dashboard stays accurate.

---

## 4. Ticket Status Moves

<!-- non-jira-only:start -->
All status moves go directly through the DWB API; there is no dual-write tool and raw PATCH is the canonical move:

```bash
curl -X PATCH http://localhost:8000/api/tickets/{id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"status": "todo"}'
```

- PM moves: `backlog` → `todo` (sprint planning confirmed), `in_review` → `done` (only after the TL's review verdict; on small TL-driven teams the TL flips `done` directly)
- PM does NOT move tickets to `in_progress`; that's the worker's signal
- Use the database `id` in the path, never the `ticket_key` suffix (see Resolving a DWB numeric id below)
<!-- non-jira-only:end -->

### Resolving a DWB numeric id

PATCH endpoints need DWB's numeric `id`, not the `ticket_key` (e.g. `CI-217`). `PATCH /api/tickets/CI-217` will 404; always resolve to the numeric id first.

**On Jira-linked projects** (you have a Jira key in hand):
```bash
curl -s "http://localhost:8000/api/tickets?project_id={pid}&jira_issue_key=POR-5600" | jq '.[0].id'
```

**On non-Jira projects** (no Jira key exists): you already have the DWB id from the ticket listing or the assignment brief; no resolution step needed. If you only have the `ticket_key`:
```bash
curl -s "http://localhost:8000/api/tickets?project_id={pid}&ticket_key=DWB-285" | jq '.[0].id'
```

<!-- non-jira-only:start -->
### Sprint carryover (no Jira)

No tool covers DWB sprint-field changes; carryover is a raw PATCH:

```bash
curl -X PATCH http://localhost:8000/api/tickets/{id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": {next_sprint_id}, "status": "backlog"}'
```
<!-- non-jira-only:end -->

---

## 5. Status Vocabulary

See `~/Dev/DWB_2_JIRA/README.md §Terminal vs non-terminal status vocabulary` for the full list. TL;DR:

- **Jira terminal:** `Done`, `Won't Do`, `Resolved`, `Cancelled`, `Closed`
- **DWB terminal:** `done`
- **Non-terminal:** everything else (includes `Ready for Testing/Review` on the Jira side)

---

## 6. Comments

`POST /api/comments` with `ticket_id`, `author_agent_id`, `body`. List: `GET /api/comments?ticket_id={id}`.

DWB API quirk: the field is `author_agent_id`, **not** `agent_id`. Use comments liberally for status observations, blockers, sprint notes, review decisions.

---

## 7. Alerts

`POST /api/alerts` with `project_id`, `raised_by_agent_id`, `title`, `body`, `severity`, optional `ticket_id`.

| Severity | When |
|----------|------|
| info | Observations, no action needed (sprint progress, token trends) |
| warning | Needs TL/human attention. **Process-state signals:** agent inactive 30+ min (no hook activity at all), blocked tickets, sprint goal at risk. **External-event signals:** test suite degrading, mounting drift between DWB and Jira. |
| critical | Stop everything: DB errors, agent retry loops, test suite fully red |

**Note on thresholds:** the 30-min agent-inactive bar above is your discretion to raise when nothing else is firing. § 8 below covers the system's automatic 10-min stale-ticket alert, which is a different signal (a ticket sitting in `in_progress` without `updated_at` changing). The two are orthogonal: one is per-agent activity, the other is per-ticket motion.

For human decisions, use warning/critical alert and be specific about what decision is needed: name the tradeoff, not just the problem.

---

## 8. Handling Stale Ticket Alerts

System fires stale alerts when a ticket is `in_progress` 10+ min with no `updated_at` change. Repeats every 10 min.

**Investigate:** `GET /api/hooks/sessions?project_id={pid}` (session ended?), `GET /api/activity-logs?agent_id={aid}&limit=5` (last activity?), ping via SendMessage if unclear.

| Situation | Action |
|-----------|--------|
| Session ended, no recent activity | Move ticket to `todo`, comment why, alert TL to reassign |
| Agent alive but slow | Dismiss alert, optionally comment |
| Agent alive but stuck | Ping agent, flag TL if no response |
| Never started (premature `in_progress`) | Move to `todo`, comment on mis-assignment |

---

## 9. X-Agent-ID Header (REQUIRED)

Include `X-Agent-ID: {your_agent_id}` on every POST/PATCH/PUT/DELETE. Without it, activity attribution uses heuristics and may misattribute.

**Your agent id** comes from the identify response you cached at startup (worker_playbook § On Spawn step 2). It's the same id the TL gave you in the spawn brief. Fallback discovery (only when neither of those is available): `GET /api/agents?role=pm&project_id={pid}`.

Log PM actions via `POST /api/activity-logs`. Read: `GET /api/activity-logs?project_id={pid}&limit=50`. Activity gaps = agent stuck or context lost.

---

## 10. Tracking (Automatic)

Time/token tracking is passive via lifecycle hooks, PM consumes the data.

- `GET /api/tracking/summary?project_id={pid}`, per-ticket, per-agent, per-sprint rollups
- `GET /api/hooks/sessions?project_id={pid}`, active/completed sessions

**Overhead breakdown (DWB-306):** the `per_agent` rollup splits totals into two fields per agent:
- `tokens`, combined total (ticket work + overhead like spawn/handoff/orchestration)
- `overhead_tokens`, the overhead-only portion (`overhead_token_report` events)

For sprint-close diagnostics, subtract `overhead_tokens` from `tokens` to see ticket-attributable work. The project rollup carries the invariant `project.tl_overhead + project.pm_overhead == project_total.overhead_tokens`, if it ever fails, that's a tracking bug, raise critical.

Flag outliers (one ticket 10x+ tokens of peers) to TL.

---

## 11. Test Results

`GET /api/test-results?project_id={pid}&limit=5`

Alert on: consecutive failures, increasing skip count, duration creep. Name the suite (`backend`, `frontend`) and the failure count.

---

## 11a. Failure Logging

When a ticket moves back to `in_progress` after being `done` (rework), the system auto-creates a failure record stub with type `TBD`. The PM MUST:

1. `GET /api/failure-records?project_id={pid}&resolved=false`, find unresolved stubs
2. Fill in the type, severity, notes:

```bash
PATCH /api/failure-records/{id}
{
  "failure_type": "context_degradation",
  "severity": "medium",
  "notes": "Agent lost context of the schema change from sprint 2"
}
```

Failure types: `context_degradation`, `spec_drift`, `sycophantic_confirmation`, `tool_selection_error`, `cascading_failure`, `silent_failure`, `integration_failure`, `rework`, `test_failure`.

**Sprint close is blocked until all failure records in the sprint are reviewed (resolved or have a non-TBD type).**

---

## 12. Sprint Evaluation Workflow

1. Gather: `GET /api/sprints/{id}`, `GET /api/tickets?sprint_id={id}`, `GET /api/test-results?project_id={pid}&limit=10`, `GET /api/alerts?project_id={pid}&status=open`
2. Metrics: `GET /api/tracking/summary?project_id={pid}`, planned vs completed, avg tokens/ticket, spillover count
3. Write eval: `POST /api/activity-logs` with action `sprint_evaluation`, ticket counts, token totals (incl. TL/PM overhead), goal status, test results
4. Carryover: PATCH incomplete tickets with `{"sprint_id": {next_id}, "status": "backlog"}` (see § 4 exception)
5. Send findings to TL and human

---

## 12a. Sprint Close: Consolidation Gate (REQUIRED)

DWB's `force_consolidation` gate (opt-in per project, default OFF — DWB-400) blocks sprint close until every sprint participant has POSTed `consolidate-complete`. Gate has TEETH (DWB-328): naked ack with over-ceiling files returns HTTP 400 with violations. **What counts (DWB-397/399/401):** ONLY the TL-owned docs (root docs + all three `project_rules_*` files). Playbooks + agent defs are exempt, and — as of DWB-401 — every agent's `memory.md` is exempt too (bounded by a passive server-side trim, never counted). So no worker or PM ever has an over-ceiling file: your own ack, and theirs, is a clean naked ack. The PM's role at sprint close:

1. **Verify gate state.** `GET /api/projects/{pid}/consolidation-status?sprint_id={sid}` returns `agents[]` with `acked: true/false` + `owned_over_ceiling_files` per agent, and `gate_satisfied` overall. With memory exempt, `owned_over_ceiling_files` is empty for everyone except possibly the TL (their root/`project_rules` docs).
2. **Chase missing acks, not trims.** If a participant hasn't acked, ping them to file the ack (it passes clean — nothing of theirs gates). Only the TL might have a real over-ceiling doc to trim; surface that to the TL.
3. **Self-ack.** PM files a clean naked ack — your memory is exempt, so there's nothing to trim first.

```bash
# PM's self-ack (clean files → naked ack passes 201; over-ceiling → 400 with violations)
curl -X POST http://localhost:8000/api/agents/{pm_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {pm_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": <id>}'

# Override form (use sparingly: repeated overrides = cap is wrong, raise it)
curl -X POST ... \
  -d '{"sprint_id": <id>, "overrides": {"path/to/file.md": "load-bearing reason text"}}'
```

4. **Role split at sprint close.** PM does the prep (verify gate state, surface refusals, self-ack, carryover PATCHes per § 12 step 4) and reports gate-clean. **TL owns the final PATCH that closes the sprint.** Don't run `PATCH /api/sprints/{id} {"status":"completed"}` yourself.

If an agent has gone dark, escalate to TL, TL decides between (a) mark inactive (excludes from gate), (b) wait, (c) admin-ack on their behalf for an edge case like DWB-329. Never silently ack on someone else's behalf.

## 13. HANDOFF.md Responsibility

PM shares with TL at session end. At minimum, PM contributes: sprint snapshot (X/Y tickets done), open alerts count + severity mix, hygiene flags (stale active sprints, unassigned work, missing docs), cross-system drift (DWB vs Jira mismatches).

---

## 14. Typical Check-In

1. `GET /api/alerts?project_id={pid}&status=open`, anything on fire?
2. `GET /api/sprints?project_id={pid}&status=active`, active sprint
3. Sprint distribution across statuses. Jira: `dwb2jira report --sprint active` (DWB + Jira merged). Non-Jira: `GET /api/tickets?sprint_id={sid}`, bucket by status.
4. Investigate any `in_progress` tickets that look stuck, cross-reference activity logs + hook sessions
5. `GET /api/test-results?project_id={pid}&limit=3`, tests green?
6. Log a progress observation to activity log
7. Raise alerts for anything needing attention
8. Review `GET /api/tracking/summary?project_id={pid}` for token outliers
