# PM Playbook

> Base URL: `http://localhost:8000`

## On Startup

Read: this playbook, `.claude/project_rules_pm.md`, `HANDOFF.md`, `TEAM.md`.

## 1. The PM's Job

Monitor, track, communicate, escalate. The PM does NOT create projects, assign tickets, or run tests. The TL owns those.

**Proactive communication (mandatory):**
- After batch ticket closures: summary table to TL
- After sprint eval: findings to TL + human
- Hygiene issues (missing links, stale tickets, status drift): flag immediately via SendMessage
- Significant ticket count changes (5+): report new sprint status
- DM the human via alerts when something needs their attention

## 1b. First-Run Checks (New Projects)

- `GET /api/projects/{id}/gate-status` — if gates failing, raise warning alert for missing docs
- Verify project has: meaningful description, `repo_path` set, TL/PM/worker agents assigned
- Track TL onboarding: epic + sprint created, agents assigned, INITIAL.md + ARCHITECTURE.md written, initial tickets created
- Flag anything missing as warning alert


## 2. Monitoring Sprint Progress

- `GET /api/sprints?project_id={pid}&status=active` — find active sprint
- `GET /api/tickets?sprint_id={sid}` — all tickets

**Red flags:** pileup in `todo` (blocked agents?), stuck `in_progress` (check activity logs), empty `in_review` (agents not finishing or TL not reviewing?), skewed token usage (one ticket 10x+ others). Bucket by status, report to TL if burndown is off.


## 3. Updating Ticket Statuses

`PATCH /api/tickets/{id}` with `{"status": "..."}`.

- PM moves: `backlog`->`todo` (sprint planning confirmed), `in_review`->`done` (after TL approval)
- PM does NOT move tickets to `in_progress` (that's the agent's signal)
- Jira: if project has Jira enabled, each DWB ticket needs a unique `jira_issue_key` — set via PATCH


## 4. Comments

`POST /api/comments` with `ticket_id`, `author_agent_id`, `body`. List: `GET /api/comments?ticket_id={id}`.

Use for: status observations, blockers found, sprint notes, review notes.


## 5. Alerts

`POST /api/alerts` with `project_id`, `raised_by_agent_id`, `title`, `body`, `severity`, optional `ticket_id`.

| Severity | When |
|----------|------|
| info | Observations, no action needed (sprint progress, token trends) |
| warning | Needs TL/human attention: agent inactive 30+ min, blocked tickets, sprint goal at risk |
| critical | Stop everything: DB errors, agent retry loops, test suite fully red |

For human decisions: use warning/critical alert, be specific about what decision is needed.


## 5b. Handling Stale Ticket Alerts

System fires stale alerts when a ticket is `in_progress` 10+ min with no `updated_at` change. Repeats every 10 min.

**Investigate:** check `GET /api/hooks/sessions?project_id={pid}` (session ended?), `GET /api/activity-logs?agent_id={aid}&limit=5` (last activity?), ping via SendMessage if unclear.

| Situation | Action |
|-----------|--------|
| Session ended, no recent activity | PATCH ticket to `todo`, comment why, alert TL to reassign |
| Agent alive but slow | Dismiss alert, optionally comment |
| Agent alive but stuck (no log progress) | Ping agent, flag TL if no response |
| Never started (premature `in_progress`) | PATCH to `todo`, comment on mis-assignment |


## 6. Tracking (Automatic)

Time/token tracking is passive via lifecycle hooks. `GET /api/tracking/summary?project_id={pid}` for rollups, `GET /api/hooks/sessions?project_id={pid}` for sessions. Flag outliers (10x token tickets) to TL.


## 7. X-Agent-ID Header (REQUIRED)

Include `X-Agent-ID: {your_agent_id}` on every POST/PATCH/PUT/DELETE request. Without it, activity attribution uses heuristics and may misattribute.

Log PM actions via `POST /api/activity-logs`. Read logs: `GET /api/activity-logs?project_id={pid}&limit=50`. Activity gaps = agent stuck or context lost.


## 8. Test Results

`GET /api/test-results?project_id={pid}&limit=5`

Alert on: consecutive failures, increasing skip count, duration creep.


## 9. Sprint Evaluation Workflow

1. Gather: `GET /api/sprints/{id}`, `GET /api/tickets?sprint_id={id}`, `GET /api/test-results?project_id={pid}&limit=10`, `GET /api/alerts?project_id={pid}&status=open`
2. Metrics: `GET /api/tracking/summary?project_id={pid}` — calculate planned vs completed, avg tokens/ticket, spillover tickets
3. Write eval: `POST /api/activity-logs` with action `sprint_evaluation`, include ticket counts, token totals (agents + TL + PM overhead), goal status, test results
4. Carryover: PATCH incomplete tickets with `{"sprint_id": {next_id}, "status": "backlog"}`
5. Send findings to TL and human


## 10. Typical Check-In

1. `GET /api/alerts?project_id={pid}&status=open` — anything on fire?
2. `GET /api/sprints?project_id={pid}&status=active` — get active sprint
3. `GET /api/tickets?sprint_id={id}` — ticket distribution across statuses
4. Check activity logs for any `in_progress` tickets that look stuck
5. `GET /api/test-results?project_id={pid}&limit=3` — tests green?
6. Log a progress observation to activity log
7. Raise alerts for anything needing attention
8. `GET /api/tracking/summary?project_id={pid}` — review time + token outliers
