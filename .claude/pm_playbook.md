# PM Playbook

> Base URL: `http://localhost:8000`

## Canonical Tools

- **Query tickets:** `dwb2jira report` — defaults to your tickets. **No-flag default includes EVERY status** (Done too) — add `--status "To Do,In Progress,Ready for Testing/Review"` to filter to open work. See `~/Dev/DWB_2_JIRA/README.md`.
- **Create tickets:** `dwb2jira create` — YAML input, preview + approval gate, auto-sprint, auto-DWB twin.
- **Status change on a linked ticket:** `dwb2jira ticket transition {JIRA-KEY} --to "{target}" [--comment "..."]` — atomic dual-write.
- **Never call Jira/DWB ticket-CRUD endpoints directly; use the tools.** Raw `curl` is reserved for debugging and two documented exceptions (see § 4).

**`dwb2jira create` flow** (read the full section in `~/Dev/DWB_2_JIRA/README.md` before first use): PM drafts YAML locally → `--dry-run` for preview → show human/TL for approval → `echo Y | dwb2jira create proposal.yaml` to submit. Piping `Y` does NOT bypass approval — the hash-sidecar gate requires that `--dry-run` ran first against the exact same YAML content. Edits between preview and submit trip the drift gate (exit 7). TL may edit or reject before PM submits.

## DWB Is an Internal Tool

D'Waantu B'Guantu is the human user's private project management system. **Never mention DWB** in Jira tickets, PR descriptions, commit messages, or any external-facing content. Never reference DWB ticket IDs outside of DWB itself.

## Safety — Hard Limits on Jira Manipulation

PM agents have authority over:
- DWB sprints (create, edit, close, delete) — internal to this dashboard, no cross-user impact.
- Tickets the user (Miles, or the human you're working with) is the Jira assignee of (status transitions, comments, edits).

PM agents have NO AUTHORITY over:
- Jira sprints. Pull/read only. NEVER run `dwb2jira sprint close/create/edit/delete`. Jira sprints span many users; closing one creates a cluster-fuck for every assignee on that sprint who isn't you.
- Tickets the user is not assigned to. Pull/read only.

If a TL asks you to close a Jira sprint, REFUSE and escalate to the human. This is non-negotiable. The CLI itself enforces this via DWB-324 — your call will be blocked at the tool layer too. The playbook rule is the first defense; the code guard is the second.

**Violation example:** the prior Pam ran `dwb2jira sprint close <JIRA-SPRINT-ID>`. Took out an active sprint that the user had no permission to close. Other assignees lost their sprint context. Never again.

## On Startup

Read: this playbook, `.claude/project_rules_pm.md`, `HANDOFF.md`. Fetch live roster from `GET /api/projects/{project_id}/team` (DB-authoritative).

Load instructions: `GET /api/instructions?scope=global`, `scope=project&project_id={pid}`, `scope=agent&agent_id={pm_id}`.

---

## 1. The PM's Job

Monitor, track, communicate, escalate. The PM does NOT create projects, assign tickets, or run tests — the TL owns those.

**Proactive communication (mandatory):**
- After batch ticket closures: summary table to TL
- After sprint eval: findings to TL + human
- Hygiene issues (missing links, stale tickets, status drift): flag immediately via SendMessage
- Significant ticket count changes (5+): report new sprint status
- DM the human via alerts when something needs their attention

---

## 2. First-Run Checks (New Projects)

- `GET /api/projects/{id}/gate-status` — if gates failing, raise warning alert for missing docs
- Verify project has: meaningful description, `repo_path` set, TL/PM/worker agents assigned
- Track TL onboarding: epic + sprint created, agents assigned, INITIAL.md + ARCHITECTURE.md written, initial tickets created via `dwb2jira create`
- Flag anything missing as warning alert

---

## 3. Monitoring Sprint Progress

- `GET /api/sprints?project_id={pid}&status=active` — find active sprint
- `GET /api/tickets?sprint_id={sid}` — DWB-side view
- `dwb2jira report --sprint active` — cross-system (DWB + Jira merged)
- `dwb2jira epic list --project {JIRA_PROJECT}` — discover epic keys (useful for `--epic` filter)

**Red flags:** pileup in `todo` (blocked agents?), stuck `in_progress` (check activity logs), empty `in_review` (agents not finishing or TL not reviewing?), skewed token usage (one ticket 10x+ others). Bucket by status, report to TL if burndown is off.

---

## 4. Ticket Status Moves

All status moves on linked tickets go through `dwb2jira ticket transition` — it's dual-write.

```bash
dwb2jira ticket transition {JIRA-KEY} --to "{target}" [--comment "..."]
# See JIRA_INTEGRATION.md for the Jira↔DWB status mapping.
```

- PM moves: `backlog` → `todo` (sprint planning confirmed), `in_review` → `done` (after TL approval)
- PM does NOT move tickets to `in_progress` — that's the worker's signal
- **If TL already transitioned Jira manually:** check with TL before running; you may need a one-sided DWB PATCH. That's the only time raw status PATCH is acceptable, and only with TL confirmation.
- **`--comment` requires `DWB_AGENT_ID` in `.env`** — without it, the DWB-side comment is skipped with a warning (Jira still gets the comment). Set it once at environment setup.
- **Never touch `jira_issue_key` by hand** — `dwb2jira create` sets it; if a link is missing, report it as a tool bug.

### Resolving a DWB numeric id from a Jira key

PATCH endpoints need DWB's numeric `id`, not the `ticket_key` (e.g. `CI-217`):

```bash
curl -s "http://localhost:8000/api/tickets?project_id={pid}&jira_issue_key=POR-5600" | jq '.[0].id'
```

`PATCH /api/tickets/CI-217` will 404 — always resolve to the numeric id first.

### Exceptions where raw PATCH IS sanctioned

**(a) TL already transitioned Jira manually** — one-sided DWB PATCH to catch DWB up:
```bash
curl -X PATCH http://localhost:8000/api/tickets/{id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

**(b) Sprint carryover** — no tool covers DWB sprint-field changes:
```bash
curl -X PATCH http://localhost:8000/api/tickets/{id} \
  -H "X-Agent-ID: {pm_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": {next_sprint_id}, "status": "backlog"}'
```

**Known gap on (b):** this moves the DWB twin only. The Jira issue stays pinned to the OLD sprint. Stakeholders watching Jira will see the ticket stuck there. **No `dwb2jira` command currently moves a Jira issue between sprints** — the TL needs to move each Jira issue manually via the Jira UI (or a future tool). Flag the list of carryover tickets to the TL at sprint close so the Jira side gets moved. Don't silently leave Jira mis-sprinted.

### Two warning shapes after `ticket transition`

When `--comment` is used, the tool can surface two different warnings — they have different recovery paths:

| Warning text contains | What failed | Recovery |
|-----------------------|-------------|----------|
| `DWB twin status update failed` (or `DWB-side PATCH got ...`) | Jira transitioned, DWB status PATCH failed. **Status drift.** | Use exception (a) above — one-sided DWB PATCH to match Jira. |
| `DWB_AGENT_ID not set` or `DWB comment skipped` | Jira transitioned + Jira comment posted, but DWB comment skipped. **Comment drift only, status is fine.** | Set `DWB_AGENT_ID` in `.env`, then `POST /api/comments` manually to restore the DWB-side paper trail. |

If a warning doesn't match either shape, escalate to TL with the raw output rather than guessing.

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
| warning | Needs TL/human attention: agent inactive 30+ min, blocked tickets, sprint goal at risk |
| critical | Stop everything: DB errors, agent retry loops, test suite fully red |

For human decisions, use warning/critical alert and be specific about what decision is needed — name the tradeoff, not just the problem.

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

**Discover your own agent id:** `GET /api/agents?role=pm` (filter by role). Also listed in `.claude/project_rules_pm.md` for the current project.

Log PM actions via `POST /api/activity-logs`. Read: `GET /api/activity-logs?project_id={pid}&limit=50`. Activity gaps = agent stuck or context lost.

---

## 10. Tracking (Automatic)

Time/token tracking is passive via lifecycle hooks — PM consumes the data.

- `GET /api/tracking/summary?project_id={pid}` — per-ticket, per-agent, per-sprint rollups
- `GET /api/hooks/sessions?project_id={pid}` — active/completed sessions

**Overhead breakdown (DWB-306):** the `per_agent` rollup splits totals into two fields per agent:
- `tokens` — combined total (ticket work + overhead like spawn/handoff/orchestration)
- `overhead_tokens` — the overhead-only portion (`overhead_token_report` events)

For sprint-close diagnostics, subtract `overhead_tokens` from `tokens` to see ticket-attributable work. The project rollup carries the invariant `project.tl_overhead + project.pm_overhead == project_total.overhead_tokens` — if it ever fails, that's a tracking bug, raise critical.

Flag outliers (one ticket 10x+ tokens of peers) to TL.

---

## 11. Test Results

`GET /api/test-results?project_id={pid}&limit=5`

Alert on: consecutive failures, increasing skip count, duration creep. Name the suite (`backend`, `frontend`) and the failure count.

---

## 12. Sprint Evaluation Workflow

1. Gather: `GET /api/sprints/{id}`, `GET /api/tickets?sprint_id={id}`, `GET /api/test-results?project_id={pid}&limit=10`, `GET /api/alerts?project_id={pid}&status=open`
2. Metrics: `GET /api/tracking/summary?project_id={pid}` — planned vs completed, avg tokens/ticket, spillover count
3. Write eval: `POST /api/activity-logs` with action `sprint_evaluation` — ticket counts, token totals (incl. TL/PM overhead), goal status, test results
4. Carryover: PATCH incomplete tickets with `{"sprint_id": {next_id}, "status": "backlog"}` (see § 4 exception)
5. Send findings to TL and human

---

## 12a. Sprint Close — Consolidation Gate (REQUIRED)

DWB's `force_consolidation` gate blocks sprint close until every sprint participant has POSTed `consolidate-complete`. Gate has TEETH (DWB-328): naked ack with over-ceiling files returns HTTP 400 with violations. The PM's role at sprint close:

1. **Verify gate state** — `GET /api/projects/{pid}/consolidation-status?sprint_id={sid}` returns `agents[]` with `acked: true/false` + `owned_over_ceiling_files` per agent, and `gate_satisfied` overall.
2. **Surface refusals proactively** — if any participant has over-ceiling files and hasn't acked yet, ping them BY NAME with their file list and the autonomy expectation: "refusal is the signal to trim, not idle." Don't let agents sit on a refused ack waiting for instructions.
3. **Self-ack with the same discipline** — PM trims own over-ceiling files BEFORE acking. If you get 400, trim and retry; don't override unless the file is genuinely load-bearing.

```bash
# PM's self-ack (clean files → naked ack passes 201; over-ceiling → 400 with violations)
curl -X POST http://localhost:8000/api/agents/{pm_agent_id}/consolidate-complete \
  -H "X-Agent-ID: {pm_agent_id}" \
  -H "Content-Type: application/json" \
  -d '{"sprint_id": <id>}'

# Override form (use sparingly — repeated overrides = cap is wrong, raise it)
curl -X POST ... \
  -d '{"sprint_id": <id>, "overrides": {"path/to/file.md": "load-bearing reason text"}}'
```

4. **TL owns the final PATCH** — PM only verifies and reports gate-clean.

If an agent has gone dark, escalate to TL — TL decides between (a) mark inactive (excludes from gate), (b) wait, (c) admin-ack on their behalf for an edge case like DWB-329. Never silently ack on someone else's behalf.

## 13. HANDOFF.md Responsibility

PM shares with TL at session end. At minimum, PM contributes: sprint snapshot (X/Y tickets done), open alerts count + severity mix, hygiene flags (stale active sprints, unassigned work, missing docs), cross-system drift (DWB vs Jira mismatches).

---

## 14. Typical Check-In

1. `GET /api/alerts?project_id={pid}&status=open` — anything on fire?
2. `GET /api/sprints?project_id={pid}&status=active` — active sprint
3. `dwb2jira report --sprint active` — merged DWB + Jira distribution across statuses
4. Investigate any `in_progress` tickets that look stuck — cross-reference activity logs + hook sessions
5. `GET /api/test-results?project_id={pid}&limit=3` — tests green?
6. Log a progress observation to activity log
7. Raise alerts for anything needing attention
8. Review `GET /api/tracking/summary?project_id={pid}` for token outliers
